"""第一层·能力边界：显式声明该接 / 不该接，不该接的一律硬规则拦截。

本模块只做「判定」，不做回复；转人工动作由 handoff.py 统一执行。
判定结果会被记录到日志、SSE 事件和 /health 里，便于运营审计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import contains_any, load_rules

# 全角标点统一成半角，避免词表匹配漏掉
_PUNCT_MAP = str.maketrans({"！": "!", "？": "?", "，": ",", "。": "."})


def normalize(text: str) -> str:
    return (text or "").translate(_PUNCT_MAP).lower()


@dataclass
class BoundaryHit:
    key: str
    label: str
    reason: str
    keywords: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "reason": self.reason,
            "keywords": self.keywords,
            "detail": self.detail,
        }


def snapshot() -> dict:
    """给 /health 与 README 用的边界清单。"""
    rules = load_rules()["boundaries"]
    return {
        "accepted": [{"key": i["key"], "label": i["label"], "desc": i["desc"]} for i in rules["accepted"]],
        "rejected": [{"key": i["key"], "label": i["label"], "desc": i["desc"]} for i in rules["rejected"]],
    }


def detect_rejected(text: str) -> BoundaryHit | None:
    """命中「不该接」清单即返回，调用方必须转人工，不允许模型自由发挥。"""
    lowered = normalize(text)
    for item in load_rules()["boundaries"]["rejected"]:
        hits = contains_any(lowered, [w.lower() for w in item.get("keywords", [])])
        if hits:
            return BoundaryHit(
                key=item["key"],
                label=item["label"],
                reason=item["handoff_reason"],
                keywords=hits,
                detail=f"命中边界「{item['label']}」：{'、'.join(hits)}",
            )
    return None


def emotion_signals(text: str) -> list[str]:
    """情绪信号：强情绪词直接命中；弱情绪词必须叠加标点/重复字符信号。

    这样「太差了」「无语」这类日常抱怨不会单独触发转人工，
    只有「无语！！！」「气死我了」这种强烈表达才升级处理。
    """
    rules = load_rules()["handoff"]["emotion"]
    raw = text or ""
    lowered = normalize(raw)

    punctuation_signals: list[str] = []
    bangs = raw.count("！") + raw.count("!")
    if bangs >= int(rules.get("exclamation_threshold", 2)):
        punctuation_signals.append(f"感叹号×{bangs}")

    for token in rules.get("repeated_punctuation", []):
        if token in raw:
            punctuation_signals.append(f"重复标点「{token}」")
            break

    # 连续 4 个以上相同字符，通常是刷屏式情绪表达
    if re.search(r"(.)\1{4,}", raw):
        punctuation_signals.append("连续重复字符")

    strong_words = rules.get("strong_words")
    mild_words = rules.get("mild_words")
    if strong_words is None and mild_words is None:
        # 兼容旧配置：单一词表 + 标点信号
        signals = contains_any(lowered, [w.lower() for w in rules.get("words", [])])
        return signals + punctuation_signals

    signals = contains_any(lowered, [w.lower() for w in (strong_words or [])])
    mild_hits = contains_any(lowered, [w.lower() for w in (mild_words or [])])
    if mild_hits and punctuation_signals:
        signals.extend(mild_hits)
    return signals + punctuation_signals


def format_boundary_for_prompt() -> str:
    """给真实模型的系统提示词用的边界说明（模型只在该范围内作答）。"""
    rules = load_rules()["boundaries"]
    accepted = "；".join(f"{i['label']}（{i['desc']}）" for i in rules["accepted"])
    rejected = "；".join(i["label"] for i in rules["rejected"])
    return f"【能力边界】可处理：{accepted}。不处理：{rejected}（由系统硬规则转人工，你不要自行处理）。"
