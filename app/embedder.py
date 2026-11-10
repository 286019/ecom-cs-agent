"""向量检索的 embedding 客户端。

- 有真实 Key 且供应商提供 embedding 模型时，调用 OpenAI 兼容的 /embeddings 接口
  （智谱 embedding-3、百炼 text-embedding-v3 都走这个协议）。
- 向量与文本哈希一起缓存在 data/embedding_cache.json，重启不重复计费。
- 无 Key / 调用失败时由 knowledge.py 自动降级到 BM25，不阻塞启动。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import httpx
import numpy as np

from .config import Settings

log = logging.getLogger("ecom.embedding")


class EmbeddingError(RuntimeError):
    pass


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class Embedder:
    def __init__(self, settings: Settings, cache_path: Path | None = None):
        self.settings = settings
        self.model = settings.embedding_model
        self.endpoint = f"{settings.base_url}/embeddings"
        self.cache_path = cache_path or (settings.data_dir / "embedding_cache.json")
        self._cache: dict[str, list[float]] = {}
        self._load_cache()

    # ---------- 缓存 ----------

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._cache = raw.get(self.model, {})
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("读取 embedding 缓存失败，将重新计算：%s", exc)

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {}
        if self.cache_path.exists():
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload[self.model] = self._cache
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")

    # ---------- 调用 ----------

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "input": texts}
        try:
            with httpx.Client(timeout=self.settings.request_timeout) as client:
                resp = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"网络请求失败：{exc}") from exc
        if resp.status_code >= 400:
            raise EmbeddingError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        items = sorted(body.get("data") or [], key=lambda i: i.get("index", 0))
        vectors = [item.get("embedding") for item in items]
        if len(vectors) != len(texts) or any(not v for v in vectors):
            raise EmbeddingError("embedding 返回结构不完整")
        return vectors

    def embed(self, texts: list[str]) -> np.ndarray:
        """返回 L2 归一化后的矩阵，形状 (len(texts), dim)。"""
        missing = [t for t in texts if _digest(t) not in self._cache]
        for start in range(0, len(missing), 32):
            batch = missing[start : start + 32]
            vectors = self._embed_batch(batch)
            for text, vector in zip(batch, vectors):
                self._cache[_digest(text)] = vector
            log.info("embedding 新增 %d 条（%s）", len(batch), self.model)
        if missing:
            self.save_cache()

        matrix = np.array([self._cache[_digest(t)] for t in texts], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms
