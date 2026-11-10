"""第二层·知识层：语义段落切块 + 向量检索（可降级 BM25）。

设计要点
1. 切块：按 Markdown 二级标题划分语义段落，长段落再按句号/空行切分，
   每块保留 doc_title、chunk_id、原文，便于前端展开溯源。
2. 检索：配置了支持 embedding 的真实 Key 时用余弦相似度；否则自动降级
   BM25 关键词检索，并在返回结果里明确标注当前方式（前端会显示）。
3. 置信度：向量取 top1 余弦值；BM25 取 top1 原始分，并用归一化值展示。
4. 低置信不硬答：是否存在知识由调用方（agent）判断，低于阈值直接转人工。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .embedder import Embedder, EmbeddingError
from .rules import load_rules

CJK = r"\u4e00-\u9fff"
MAX_CHUNK = 340
MIN_CHUNK = 70
# 查询侧停用词：不参与词覆盖度计算，也不参与 BM25，避免「可以/吗/支持」造成假命中或稀释覆盖度
STOPWORDS = {
    "可以", "能不能", "是否", "支持", "怎么", "如何", "你们", "我的", "请问", "一下",
    "这个", "那个", "什么", "需要", "我想", "帮我", "现在", "还有", "就是", "的话",
    "吗", "呢", "吧", "啊", "的", "了", "是", "有", "能", "和", "在",
}


def tokenize(text: str) -> list[str]:
    """英文/数字按词切分，中文按单字 + 二元组切分。"""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    for run in re.findall(f"[{CJK}]+", text):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _split_paragraphs(body: str) -> list[str]:
    """先按空行分段，超长段落再按句子边界切分。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    out: list[str] = []
    for para in paras:
        if len(para) <= 260:
            out.append(para)
            continue
        buffer = ""
        for sentence in re.split(r"(?<=[。！？；])", para):
            if buffer and len(buffer) + len(sentence) > MAX_CHUNK:
                out.append(buffer.strip())
                buffer = sentence
            else:
                buffer += sentence
        if buffer.strip():
            out.append(buffer.strip())
    return out


def _merge_paragraphs(paras: list[str]) -> list[str]:
    """把相邻短段落合并成约 340 字的语义块，避免碎片化。"""
    merged: list[str] = []
    for para in paras:
        if merged and len(merged[-1]) + len(para) <= MAX_CHUNK:
            merged[-1] = merged[-1] + "\n" + para
        else:
            merged.append(para)
    # 极短块并入前一块，保持语义完整
    result: list[str] = []
    for item in merged:
        if result and len(item) < MIN_CHUNK and len(result[-1]) + len(item) <= MAX_CHUNK + 80:
            result[-1] = result[-1] + "\n" + item
        else:
            result.append(item)
    return result


@dataclass
class Chunk:
    chunk_id: str
    doc_title: str
    title: str
    source: str
    text: str
    locator: str
    tokens: list[str]
    length: int


def _split_markdown(raw: str, source: str) -> list[Chunk]:
    doc_title = ""
    for line in raw.splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
            break

    sections: list[tuple[str, str]] = []
    current_title = doc_title
    buffer: list[str] = []
    for line in raw.splitlines():
        if line.startswith("## "):
            if buffer:
                sections.append((current_title, "\n".join(buffer)))
            current_title = line[3:].strip()
            buffer = []
        elif line.startswith("# "):
            continue
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_title, "\n".join(buffer)))

    stem = Path(source).stem
    chunks: list[Chunk] = []
    for index, (title, body) in enumerate(sections, 1):
        parts = _merge_paragraphs(_split_paragraphs(body))
        total = len(parts)
        for part_index, text in enumerate(parts, 1):
            text = text.strip()
            if not text:
                continue
            locator = f"{source} › {title}"
            if total > 1:
                locator += f"（第 {part_index}/{total} 段）"
            chunk_id = f"{stem}#{index}-{part_index}"
            # 标题拼进正文，保证 embedding/BM25 都能利用章节语义
            enriched = f"【{doc_title} - {title}】\n{text}"
            tokens = tokenize(enriched)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_title=doc_title,
                    title=title,
                    source=source,
                    text=text,
                    locator=locator,
                    tokens=tokens,
                    length=len(tokens),
                )
            )
    return chunks


class KnowledgeBase:
    def __init__(self, root: Path, settings: Settings | None = None, embedder: Embedder | None = None):
        self.root = Path(root)
        self.settings = settings
        self.k1 = 1.5
        self.b = 0.75
        self.chunks: list[Chunk] = []
        self._df: dict[str, int] = {}
        self._avg_len = 0.0
        self._vectors: np.ndarray | None = None
        self._embedder = embedder
        self.degraded = False
        self.method_reason = "未配置 API Key，使用 BM25 关键词检索"
        self._load()
        self._build_index()

    # ---------- 加载 ----------

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            self.chunks.extend(_split_markdown(raw, path.name))
        if not self.chunks:
            return
        for chunk in self.chunks:
            for term in set(chunk.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._avg_len = sum(c.length for c in self.chunks) / len(self.chunks)

    def _build_index(self) -> None:
        """有 Key 就建向量索引，失败或无 Key 则保持 BM25。"""
        if not self.settings or not self.settings.can_embed or not self.chunks:
            return
        try:
            self._embedder = self._embedder or Embedder(self.settings)
            texts = [f"{c.doc_title} {c.title}\n{c.text}" for c in self.chunks]
            self._vectors = self._embedder.embed(texts)
            self.method_reason = f"已配置 {self.settings.embedding_model}，使用余弦相似度语义检索"
        except (EmbeddingError, ValueError, OSError) as exc:
            self._vectors = None
            self.degraded = True
            self.method_reason = f"向量索引构建失败（{exc}），已降级为 BM25 关键词检索"

    # ---------- BM25 ----------

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _query_terms(self, query: str) -> list[str]:
        """查询词 = 分词结果 + 同义词扩展，去掉停用词。"""
        terms = [t for t in tokenize(query) if t not in STOPWORDS]
        synonyms = load_rules()["retrieval"].get("synonyms", {})
        for key, values in synonyms.items():
            if key in query:
                for value in values:
                    terms.extend(t for t in tokenize(value) if t not in STOPWORDS)
        return terms

    def _bm25(self, query: str) -> list[tuple[float, Chunk]]:
        q_tokens = self._query_terms(query)
        if not q_tokens:
            return []
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            length = chunk.length or 1
            tf: dict[str, int] = {}
            for term in chunk.tokens:
                tf[term] = tf.get(term, 0) + 1
            score = 0.0
            for term in q_tokens:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                score += self._idf(term) * (freq * (self.k1 + 1)) / (
                    freq + self.k1 * (1 - self.b + self.b * length / self._avg_len)
                )
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _coverage(self, query: str, chunk: Chunk) -> float:
        """查询词被该知识块覆盖的比例，用于过滤「只碰到一两个常用词」的假命中。"""
        terms = set(self._query_terms(query))
        if not terms:
            return 0.0
        chunk_tokens = set(chunk.tokens)
        return len([t for t in terms if t in chunk_tokens]) / len(terms)

    # ---------- 统一检索入口 ----------

    def search(self, query: str, top_k: int | None = None) -> dict:
        rules = load_rules()["retrieval"]
        top_k = top_k or int(rules.get("top_k", 3))
        empty = {
            "method": "bm25",
            "method_label": rules["bm25"]["label"],
            "method_reason": self.method_reason,
            "degraded": self.degraded,
            "confidence": 0.0,
            "threshold": rules["bm25"]["threshold"],
            "passed": False,
            "results": [],
        }
        if not self.chunks or not query.strip():
            return empty

        if self._vectors is not None and self._embedder is not None:
            return self._search_vector(query, top_k, rules)
        return self._search_bm25(query, top_k, rules)

    def _search_vector(self, query: str, top_k: int, rules: dict) -> dict:
        assert self._embedder is not None and self._vectors is not None
        try:
            q_vec = self._embedder.embed([query])[0]
        except EmbeddingError as exc:
            self.degraded = True
            self._vectors = None
            self.method_reason = f"查询向量化失败（{exc}），本轮降级为 BM25"
            return self._search_bm25(query, top_k, rules)

        scores = self._vectors @ q_vec
        order = np.argsort(-scores)[:top_k]
        confidence = float(scores[order[0]]) if len(order) else 0.0
        threshold = float(rules["vector"]["threshold"])
        results = []
        for idx in order:
            chunk = self.chunks[int(idx)]
            results.append(self._result(chunk, float(scores[idx]), float(scores[idx])))
        return {
            "method": "vector",
            "method_label": rules["vector"]["label"],
            "method_reason": self.method_reason,
            "degraded": self.degraded,
            "confidence": round(confidence, 4),
            "threshold": threshold,
            "passed": confidence >= threshold,
            "results": results,
        }

    def _search_bm25(self, query: str, top_k: int, rules: dict) -> dict:
        scored = self._bm25(query)[:top_k]
        threshold = float(rules["bm25"]["threshold"])
        min_coverage = float(rules["bm25"].get("min_coverage", 0))
        confidence = float(scored[0][0]) if scored else 0.0
        coverage = self._coverage(query, scored[0][1]) if scored else 0.0
        # 归一化到 0-1 仅用于展示；是否通过用原始分 + 词覆盖度双重判断
        shown = confidence / (confidence + 3.0) if confidence else 0.0
        results = [self._result(chunk, score, score / (score + 3.0)) for score, chunk in scored]
        return {
            "method": "bm25",
            "method_label": rules["bm25"]["label"],
            "method_reason": self.method_reason,
            "degraded": self.degraded,
            "confidence": round(shown, 4),
            "raw_score": round(confidence, 4),
            "coverage": round(coverage, 3),
            "threshold": threshold,
            "passed": bool(scored) and confidence >= threshold and coverage >= min_coverage,
            "results": results,
        }

    @staticmethod
    def _result(chunk: Chunk, score: float, confidence: float) -> dict:
        return {
            "chunk_id": chunk.chunk_id,
            "doc_title": chunk.doc_title,
            "title": chunk.title,
            "source": chunk.source,
            "locator": chunk.locator,
            "text": chunk.text,
            "score": round(score, 4),
            "confidence": round(confidence, 4),
        }

    def format_context(self, results: list[dict]) -> str:
        if not results:
            return ""
        blocks = []
        for i, item in enumerate(results, 1):
            blocks.append(f"[知识片段 {i}｜chunk_id={item['chunk_id']}｜来源：{item['locator']}]\n{item['text']}")
        return "\n\n".join(blocks)

    def sources_payload(self, results: list[dict]) -> list[dict]:
        """给前端的可展开来源列表（文档名 + 段落定位 + 原文片段）。"""
        return [
            {
                "chunk_id": item["chunk_id"],
                "doc_title": item["doc_title"],
                "title": item["title"],
                "locator": item["locator"],
                "snippet": item["text"][:240],
                "confidence": item["confidence"],
            }
            for item in results
        ]
