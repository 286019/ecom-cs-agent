"""会话状态与工单：全部保存在进程内存中，重启即清空（演示足够）。"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

ORDER_ID_RE = re.compile(r"(?<![A-Za-z0-9])(EC\d{8,}|[A-Z]{2}\d{8,})(?![A-Za-z0-9])", re.IGNORECASE)
PHONE_TAIL_RE = re.compile(r"(?:尾号|后四位|手机号?)\D{0,6}([0-9lIO]{4})(?![0-9lIO])")

MAX_HISTORY = 20  # 送给模型的历史消息条数上限


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search(text or "")
    return match.group(1).upper() if match else None


def extract_phone_tail(text: str) -> str | None:
    match = PHONE_TAIL_RE.search(text or "")
    if not match:
        return None
    # 兼容 OCR/手误：l、I 视作 1，O 视作 0
    return match.group(1).replace("l", "1").replace("I", "1").replace("O", "0")


@dataclass
class Session:
    session_id: str
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    messages: list[dict] = field(default_factory=list)
    last_order_id: str | None = None
    last_phone_tail: str | None = None
    pending_action: str | None = None  # 等待用户补充订单号的待办动作，例如 refund
    unresolved_streak: int = 0
    handoff: dict | None = None
    tool_events: list[dict] = field(default_factory=list)
    intent_history: list[dict] = field(default_factory=list)
    last_after_sale_id: str | None = None
    last_retrieval: dict | None = None

    def remember_facts(self, text: str) -> None:
        """从用户输入里记住订单号 / 手机尾号，供后续多轮对话使用。"""
        order_id = extract_order_id(text)
        if order_id:
            self.last_order_id = order_id
        phone_tail = extract_phone_tail(text)
        if phone_tail:
            self.last_phone_tail = phone_tail
        after_sale = re.search(r"\bAS\d{8,}\b", text or "", re.IGNORECASE)
        if after_sale:
            self.last_after_sale_id = after_sale.group(0).upper()

    def record_intent(self, intent: dict) -> None:
        entry = {
            "intent": intent.get("intent"),
            "label": intent.get("label"),
            "branch": intent.get("branch"),
            "action": intent.get("action"),
        }
        self.intent_history.append(entry)
        if len(self.intent_history) > 20:
            self.intent_history = self.intent_history[-20:]

    def add_message(self, role: str, content: str) -> None:
        if not content:
            return
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_HISTORY:
            self.messages = self.messages[-MAX_HISTORY:]

    def history(self) -> list[dict]:
        return [m for m in self.messages if m["role"] in ("user", "assistant")]

    def create_handoff(self, reason: str, summary: str | None = None, context: dict | None = None) -> dict:
        if self.handoff:
            return self.handoff
        ticket = {
            "ticket_id": "T" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:3].upper(),
            "session_id": self.session_id,
            "reason": reason,
            "order_id": self.last_order_id,
            "phone_tail": self.last_phone_tail,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary or self.build_summary(reason, context),
        }
        self.handoff = ticket
        return ticket

    def build_summary(self, reason: str, context: dict | None = None) -> str:
        """转人工时必须携带的完整上下文，用户不需要再重复描述。"""
        context = context or {}
        lines = [f"【用户诉求】{reason}"]

        facts: list[str] = []
        if context.get("order_text"):
            facts.append(context["order_text"])
        if self.last_order_id:
            facts.append(f"订单号 {self.last_order_id}")
        if self.last_phone_tail:
            facts.append(f"手机尾号 {self.last_phone_tail}")
        if self.last_after_sale_id:
            facts.append(f"售后单号 {self.last_after_sale_id}")
        if context.get("product"):
            facts.append(f"相关商品 {context['product']}")
        lines.append("【已确认信息】" + ("；".join(facts) if facts else "用户尚未提供订单信息"))

        judgement = []
        if context.get("intent_label"):
            judgement.append(f"意图：{context['intent_label']}")
        if context.get("rule_detail"):
            judgement.append(f"触发规则：{context['rule_detail']}")
        if context.get("retrieval_summary"):
            judgement.append(f"检索情况：{context['retrieval_summary']}")
        if judgement:
            lines.append("【机器人判断】" + "；".join(judgement))

        lines.append("【对话要点】")
        for msg in self.history()[-6:]:
            speaker = "用户" if msg["role"] == "user" else "客服"
            content = msg["content"].replace("\n", " ")[:120]
            lines.append(f"  - {speaker}：{content}")

        if context.get("suggestion"):
            lines.append(f"【建议处理】{context['suggestion']}")
        return "\n".join(lines)

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "turns": len([m for m in self.messages if m["role"] == "user"]),
            "last_order_id": self.last_order_id,
            "last_phone_tail": self.last_phone_tail,
            "last_after_sale_id": self.last_after_sale_id,
            "unresolved_streak": self.unresolved_streak,
            "handoff": self.handoff,
            "intents": self.intent_history[-6:],
        }


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None) -> Session:
        sid = (session_id or "").strip() or uuid.uuid4().hex
        with self._lock:
            if sid not in self._data:
                self._data[sid] = Session(session_id=sid)
            return self._data[sid]

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._data.get(session_id)

    def reset(self, session_id: str) -> bool:
        with self._lock:
            return self._data.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._data)


store = SessionStore()
