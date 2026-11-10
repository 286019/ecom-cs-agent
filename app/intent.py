"""第三层·决策层（一）：独立意图识别模块。

输出结构化意图，规则全部来自 config/rules.json，方便运营维护。
识别顺序按 priority 从高到低，先命中先返回；投诉类永远排在最前。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import contains_any, load_rules
from .session import Session, extract_order_id, extract_phone_tail

PRODUCT_HINTS = {
    "P1001": ["耳机", "airsound", "降噪"],
    "P1002": ["榨汁", "榨汁杯", "果汁", "榨果"],
    "P1003": ["手环", "pacefit"],
    "P1004": ["保温杯", "水杯", "杯子", "杯"],
}

# 常见错别字/口语写法，统一成业务词后再匹配（词典来自 rules.json branch_actions.typos）
TYPO_MAP = {
    "而机": "耳机",
    "手坏": "手环",
    "血痒": "血氧",
    "保问": "保温",
    "康康": "看看",
    "多钱": "多少钱",
    "啥价": "多少钱",
}


def _normalize(text: str) -> str:
    rules = load_rules().get("branch_actions", {}).get("typos") or TYPO_MAP
    normalized = text or ""
    for source, target in rules.items():
        normalized = normalized.replace(source, target)
    return normalized


@dataclass
class IntentResult:
    key: str
    label: str
    branch: str
    confidence: float
    needs_knowledge: bool
    slots: dict = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)
    reason: str = ""
    action: str = ""

    def as_dict(self) -> dict:
        return {
            "intent": self.key,
            "label": self.label,
            "branch": self.branch,
            "confidence": round(self.confidence, 2),
            "needs_knowledge": self.needs_knowledge,
            "slots": self.slots,
            "matched": self.matched,
            "reason": self.reason,
            "action": self.action,
        }


def _match_product(text: str) -> str | None:
    lowered = _normalize(text).lower()
    for product_id, hints in PRODUCT_HINTS.items():
        if any(hint in lowered for hint in hints):
            return product_id
    return None


def _is_question(text: str) -> bool:
    words = load_rules()["branch_actions"].get("question_words", [])
    return any(w in text for w in words)


def _is_greeting(text: str) -> bool:
    words = load_rules()["branch_actions"].get("greeting_words", [])
    return len(text.strip()) <= 15 and any(w in text.lower() for w in words)


def classify(text: str, session: Session | None = None) -> IntentResult:
    rules = load_rules()
    lowered = _normalize(text or "").lower()
    order_id = extract_order_id(text)
    phone_tail = extract_phone_tail(text)
    product_id = _match_product(text)

    slots = {
        "order_id": order_id or (session.last_order_id if session else None),
        "phone_tail": phone_tail or (session.last_phone_tail if session else None),
        "product_id": product_id,
    }

    # 命中具体商品时售前优先；但如果问的是退换/保修/发票等政策，仍走政策分支
    POLICY_SIGNALS = [
        "退货", "退款", "换货", "能退", "退吗", "能换", "换吗", "要退", "保修",
        "发票", "运费", "到账", "无理由", "政策", "流程", "条件", "坏了", "声音",
    ]

    def sort_key(item: dict) -> int:
        priority = item.get("priority", 0)
        asks_policy = any(word in lowered for word in POLICY_SIGNALS)
        if product_id and item["key"] == "presale" and not asks_policy:
            priority += 30
        return priority

    for item in sorted(rules["intents"], key=sort_key, reverse=True):
        rule_key = item["key"]
        is_fallback = rule_key == "chitchat"
        key = item.get("intent_key") or rule_key
        matched: list[str] = []

        all_of = item.get("all_of") or []
        all_ok = True
        for group in all_of:
            hits = contains_any(lowered, [w.lower() for w in group])
            if not hits:
                all_ok = False
                break
            matched.extend(hits)
        if all_of and not all_ok:
            continue

        any_of = item.get("any_of") or []
        if any_of:
            hits = contains_any(lowered, [w.lower() for w in any_of])
            if not hits:
                continue
            matched.extend(hits)

        if not all_of and not any_of and not is_fallback:
            continue

        if rule_key == "order_logistics" and not matched:
            continue

        # 只提供订单号（例如「EC20241108001」）也视为订单查询
        if is_fallback and (order_id or phone_tail):
            rule_key, key, item = "order_logistics", "order_logistics", _find_item("order_logistics")
            matched = [order_id or phone_tail]

        needs_knowledge = bool(item.get("needs_knowledge"))
        if rule_key == "chitchat":
            # 闲聊里如果是「真问题」（非寒暄），也要走知识库；查不到就转人工
            needs_knowledge = _is_question(text) and not _is_greeting(text)

        return IntentResult(
            key=key,
            label=item["label"],
            branch=item.get("branch", "chitchat"),
            confidence=0.95 if matched else (0.55 if needs_knowledge else 0.4),
            needs_knowledge=needs_knowledge,
            slots=slots,
            matched=list(dict.fromkeys(matched)),
            reason=f"命中分支规则：{'、'.join(dict.fromkeys(matched))}" if matched else "未命中业务分支，按闲聊处理",
            action=_resolve_action(rule_key, lowered),
        )

    return IntentResult(
        key="chitchat",
        label="闲聊其他",
        branch="chitchat",
        confidence=0.4,
        needs_knowledge=_is_question(text) and not _is_greeting(text),
        slots=slots,
        matched=[],
        reason="未命中任何业务分支，按闲聊/通用问题处理",
        action="question" if _is_question(text) else "smalltalk",
    )


def _find_item(key: str) -> dict:
    for item in load_rules()["intents"]:
        if item["key"] == key:
            return item
    return {"key": key, "label": key, "branch": "order", "needs_knowledge": False}


def _resolve_action(key: str, text: str) -> str:
    actions = load_rules().get("branch_actions", {})
    if key == "after_sale_query":
        return "query"
    if key == "order_logistics":
        words = actions.get("logistics_words", [])
        return "logistics" if any(w in text for w in words) else "order"
    if key == "after_sale":
        action_words = ["申请", "我要", "帮我", "发起", "办理", "想退", "要退", "提交", "退了"]
        query_words = actions.get("after_sale_query_words", [])
        has_action = any(w in text for w in action_words)
        has_query = any(w in text for w in query_words)
        if has_query and not has_action:
            return "query"
        return "apply"
    return ""
