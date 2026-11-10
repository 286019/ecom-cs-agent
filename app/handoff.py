"""第四层·兜底层：硬规则转人工。

所有触发条件都是确定性的硬规则，不交给模型自由判断：
1. 用户主动要求人工
2. 命中能力边界「不该接」（投诉/举报、退款纠纷、人身安全、法律问题）
3. 情绪激烈（情绪词 + 感叹号/重复标点）
4. 知识检索置信度低于阈值
5. 连续两轮未解决
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import boundary
from .rules import contains_any, load_rules
from .session import Session


@dataclass
class HandoffDecision:
    triggered: bool
    rule_key: str = ""
    label: str = ""
    reason: str = ""
    detail: str = ""
    hard: bool = True
    signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "triggered": self.triggered,
            "rule": self.rule_key,
            "label": self.label,
            "reason": self.reason,
            "detail": self.detail,
            "hard": self.hard,
            "signals": self.signals,
        }


def decide(
    text: str,
    session: Session,
    intent: dict | None = None,
    retrieval: dict | None = None,
) -> HandoffDecision:
    rules = load_rules()["handoff"]
    intent = intent or {}
    lowered = boundary.normalize(text)

    # 1) 用户明确要人工
    explicit = rules["explicit_human"]
    hits = [w for w in explicit["keywords"] if w.lower() in lowered]
    if hits:
        return HandoffDecision(
            triggered=True,
            rule_key="explicit_human",
            label=explicit["label"],
            reason="用户主动要求转人工",
            detail=f"命中关键词：{'、'.join(hits)}",
            signals=hits,
        )

    # 2) 能力边界拦截（投诉、退款纠纷、法律、人身安全）
    hit = boundary.detect_rejected(text)
    if hit:
        return HandoffDecision(
            triggered=True,
            rule_key=hit.key,
            label=hit.label,
            reason=hit.reason,
            detail=hit.detail,
            signals=hit.keywords,
        )

    # 3) 知识库明确不覆盖的主题：不检索、不猜测，直接转人工
    gaps = load_rules()["retrieval"].get("unsupported_topics", [])
    gap_hits = contains_any(lowered, [w.lower() for w in gaps])
    if gap_hits:
        return HandoffDecision(
            triggered=True,
            rule_key="unsupported_topic",
            label="知识库未覆盖主题",
            reason="知识库无相关内容",
            detail=f"命中知识库未覆盖主题：{'、'.join(gap_hits)}",
            signals=gap_hits,
        )

    # 4) 情绪激烈：情绪词 + 标点信号
    signals = boundary.emotion_signals(text)
    if signals:
        return HandoffDecision(
            triggered=True,
            rule_key="emotion",
            label=rules["emotion"]["label"],
            reason="情绪激烈",
            detail=f"情绪信号：{'、'.join(signals)}",
            signals=signals,
        )

    # 4) 投诉意图直接转人工，不查知识库
    if intent.get("intent") in rules.get("always_handoff_intents", []):
        return HandoffDecision(
            triggered=True,
            rule_key="intent_complaint",
            label="投诉意图",
            reason="投诉转人工",
            detail=f"意图识别为「{intent.get('label')}」，按边界不查知识库直接转接",
        )

    # 5) 检索置信度低于阈值：禁止模型凭记忆硬答
    if retrieval and retrieval.get("required") and not retrieval.get("passed"):
        return HandoffDecision(
            triggered=True,
            rule_key="low_confidence",
            label="知识库置信度不足",
            reason="知识库无可靠依据",
            detail=(
                f"检索方式 {retrieval.get('method_label')}，"
                f"置信度 {retrieval.get('confidence')} 低于阈值 {retrieval.get('threshold')}"
            ),
            signals=[],
        )

    # 6) 连续两轮未解决
    limit = int(rules.get("unresolved_turns", 2))
    if session.unresolved_streak >= limit:
        return HandoffDecision(
            triggered=True,
            rule_key="unresolved_streak",
            label="连续两轮未解决",
            reason="连续两轮无法解答",
            detail=f"已连续 {session.unresolved_streak} 轮未能提供有效答案",
        )

    return HandoffDecision(triggered=False)


def build_context(
    intent: dict | None,
    decision: HandoffDecision,
    retrieval: dict | None = None,
    order_text: str | None = None,
    product: str | None = None,
    suggestion: str | None = None,
) -> dict:
    """把转人工所需上下文整理成工单摘要素材。"""
    retrieval_summary = None
    if retrieval:
        retrieval_summary = (
            f"{retrieval.get('method_label')}，置信度 {retrieval.get('confidence')}"
            f"（阈值 {retrieval.get('threshold')}，{'通过' if retrieval.get('passed') else '未通过'}）"
        )
    return {
        "intent_label": (intent or {}).get("label"),
        "rule_detail": decision.label + (f"｜{decision.detail}" if decision.detail else ""),
        "retrieval_summary": retrieval_summary,
        "order_text": order_text,
        "product": product,
        "suggestion": suggestion,
    }
