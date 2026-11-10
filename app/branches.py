"""第三层·决策层（二）：按意图分流的六个分支。

每个分支只做一件事，拥有独立的提示词（真实模型）或处理逻辑（演示模式）：
    presale    售前 → 查商品参数
    order      订单物流 → 查订单 / 物流接口
    after_sale 售后 → 查政策 + 调退换货接口
    policy     政策 → 只依据知识库
    chitchat   闲聊 → 寒暄或知识库兜底
    handoff    投诉 → 不查知识库，直接转人工
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime

from . import boundary
from .knowledge import KnowledgeBase
from .session import ORDER_ID_RE, Session, extract_order_id
from .tools import execute_tool

BRANCH_TOOLS: dict[str, list[str]] = {
    "presale": ["query_product"],
    "order": ["query_order", "query_logistics"],
    "after_sale": ["create_refund", "query_after_sale", "query_order"],
    "policy": [],
    "chitchat": [],
    "handoff": ["handoff_to_human"],
}

BRANCH_LABELS = {
    "presale": "售前咨询",
    "order": "订单物流",
    "after_sale": "售后申请",
    "policy": "政策咨询",
    "chitchat": "闲聊其他",
    "handoff": "投诉转人工",
}

# 商品库里没有的常见参数：命中且工具回答未覆盖时，明确告知「未标注」，避免编造
PRESALE_ATTR_HINTS = {
    "重量": ["重量", "多重", "克"],
    "兼容性": ["苹果", "ios", "安卓", "android", "配对"],
    "冰块": ["冰块", "碎冰"],
    "清洗": ["机洗", "洗碗机"],
    "碳酸": ["碳酸", "汽水", "可乐"],
    "表带": ["表带"],
    "颜色": ["颜色", "配色"],
}

BRANCH_PROMPTS = {
    "presale": (
        "你是「潮品优选」的售前顾问，只负责商品参数、价格、库存、优惠和发货时效。\n"
        "必须调用 query_product 获取实时商品数据，禁止编造价格、库存和规格。\n"
        "知识片段只用于补充售后/发货说明，不能覆盖工具返回的实时数据。\n"
        "【硬约束】重量、尺寸、材质、颜色、适配性（手机/系统兼容）、能否机洗或进洗碗机、"
        "能否装碳酸饮料、表带能否更换等参数，只能照抄 query_product 返回的 specs。\n"
        "工具返回中没有明确写出的参数，必须原样回答「该信息未标注，建议联系人工确认」，"
        "禁止推测、补全，也禁止用「应该可以」「一般支持」「通常没问题」这类模糊结论代替。\n"
        "适配性同样属于未标注项：即使用户问「支持苹果/安卓吗」「能配对我的手机吗」，"
        "也不得根据蓝牙版本或常识推断兼容，必须回答「该信息未标注，建议联系人工确认」。\n"
        "回答控制在 200 字内，用短列表列参数；最后给一句购买建议。"
    ),
    "order": (
        "你是订单物流专员，只负责订单状态、金额、商品明细和物流轨迹。\n"
        "必须调用 query_order 或 query_logistics 获取实时数据，禁止编造订单号和物流节点。\n"
        "用户只要问到运单号、快递单号、哪家快递、承运商、到哪了、物流进度、是否签收，"
        "必须调用 query_logistics，不能只查订单状态，也不能用订单状态代替物流信息。\n"
        "回答物流问题必须写明承运商和运单号（工具结果里有就必须原样给出），"
        "例如「顺丰速运，运单号 SF1234567890123」；不要把订单号当成运单号，"
        "禁止回答「无法提供」「查不到」。\n"
        "禁止向用户提及函数名，禁止询问「需要我调用 query_logistics 吗」，直接调用工具。\n"
        "用户说「这个订单/我的订单」时，直接使用【会话事实】中的订单号，不要重复索要。\n"
        "物流只播报最新 3 条轨迹，回答控制在 200 字内。"
    ),
    "after_sale": (
        "你是售后专员，负责退换货流程引导、发起退款/退货、查询售后进度。\n"
        "先依据【知识片段】确认当前政策，再调用 create_refund 或 query_after_sale。\n"
        "政策没有覆盖的内容不要编造，明确说明「知识库暂时没有相关规定」。\n"
        "发起申请前必须确认订单号；提交后用一句话给出售后单号和下一步。"
    ),
    "policy": (
        "你是政策解释专员。只能依据【知识片段】回答，禁止凭记忆补充。\n"
        "要求：1) 先给结论；2) 分条说明；3) 每条后用（来源：文档名·段落）标注依据。\n"
        "【硬约束】【知识片段】不为空且与问题相关时，必须基于片段作答并标注来源，"
        "不得回答「知识库里没有」「暂时没有相关规定」。\n"
        "只有片段为空、或片段与问题完全无关时，才说「我们知识库里暂时没有这方面的规定」，不要猜测。\n"
        "回答控制在 250 字内。"
    ),
    "chitchat": (
        "你是「潮品优选」的在线客服小易。这里是闲聊/寒暄分支。\n"
        "简短友好回应；如果用户问题其实涉及商品、订单、售后，引导他说出订单号或具体问题。\n"
        "不要编造业务信息。"
    ),
}


def build_prompt(intent: dict, session: Session, retrieval_context: str) -> str:
    branch = intent.get("branch", "chitchat")
    facts = [
        f"- 已记住的订单号：{session.last_order_id or '暂无'}",
        f"- 已记住的手机尾号：{session.last_phone_tail or '暂无'}",
        f"- 已记住的售后单号：{session.last_after_sale_id or '暂无'}",
        f"- 当前是否已转人工：{'是，工单 ' + session.handoff['ticket_id'] if session.handoff else '否'}",
    ]
    knowledge_block = retrieval_context or "（本轮没有检索到相关知识片段）"
    return f"""{BRANCH_PROMPTS.get(branch, BRANCH_PROMPTS['chitchat'])}
今天是 {datetime.now().strftime('%Y-%m-%d')}。

{boundary.format_boundary_for_prompt()}

【会话事实】
{chr(10).join(facts)}

【知识片段】
{knowledge_block}
"""


class DemoEngine:
    """无 API Key 时的本地引擎：同一套知识库 + 同一套工具，分支行为与真实模型对齐。"""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    async def handle(
        self, session: Session, text: str, intent: dict, retrieval: dict | None
    ) -> AsyncIterator[dict]:
        reply, events = self._dispatch(session, text, intent, retrieval or {})
        for event in events:
            yield event
            await asyncio.sleep(0.03)
        async for chunk in self._stream_text(reply):
            yield chunk
        session.add_message("assistant", reply)

    async def _stream_text(self, text: str) -> AsyncIterator[dict]:
        for i in range(0, len(text), 28):
            yield {"type": "text", "content": text[i : i + 28]}
            await asyncio.sleep(0.01)

    # ---------- 分支分发 ----------

    def _dispatch(
        self, session: Session, text: str, intent: dict, retrieval: dict
    ) -> tuple[str, list[dict]]:
        branch = intent.get("branch", "chitchat")
        action = intent.get("action") or ""
        lowered = text.lower()
        events: list[dict] = []

        if any(w in text for w in ["谢谢", "感谢", "辛苦了"]) and len(text) <= 20:
            return "不客气，能帮到您就好。还有其他问题随时找我。", events

        if branch == "order":
            if action == "logistics":
                return self._do_logistics(session, intent, events)
            return self._do_order(session, intent, events)

        if branch == "after_sale":
            if action == "query":
                return self._do_after_sale_query(session, intent, events)
            return self._do_refund(session, text, intent, retrieval, events)

        if branch == "presale":
            return self._do_presale(session, text, intent, retrieval, events)

        if branch == "policy":
            return self._do_policy(session, intent, retrieval, events)

        # chitchat
        if any(w in lowered for w in ["你好", "您好", "hi", "hello", "在吗", "在么", "嗨"]) and len(text) <= 15:
            return (
                "您好，我是小易，很高兴为您服务。\n"
                "我可以帮您：查订单状态、查物流、咨询商品、办理退换货、查询售后进度。\n"
                "您可以直接发订单号（例如 EC20241108001），或说“手机尾号 8821 的订单”。",
                events,
            )
        if intent.get("needs_knowledge") and retrieval.get("results"):
            return self._do_policy(session, intent, retrieval, events)
        return (
            "这个不在我的服务范围内，我主要负责商品咨询、订单物流、退换货和售后政策。\n"
            "如果您有这些方面的问题，告诉我订单号或商品名即可。",
            events,
        )

    # ---------- 各分支实现 ----------

    def _do_order(self, session: Session, intent: dict, events: list[dict]) -> tuple[str, list[dict]]:
        slots = intent.get("slots") or {}
        args: dict = {}
        if slots.get("order_id"):
            args["order_id"] = slots["order_id"]
        elif slots.get("phone_tail"):
            args["phone_last4"] = slots["phone_tail"]
        reply, events = self._run_tool("query_order", args, session, events)
        if reply is None:
            return "请提供订单号，或收货手机号后四位，我来帮您查询订单。", events
        session.unresolved_streak = 0
        if "已发货" in reply or "已签收" in reply:
            reply += "\n需要我帮您查最新物流轨迹吗？"
        return reply, events

    def _do_logistics(self, session: Session, intent: dict, events: list[dict]) -> tuple[str, list[dict]]:
        target = (intent.get("slots") or {}).get("order_id") or session.last_order_id
        if not target:
            return "请把订单号发给我（例如 EC20241108001），我马上帮您查物流。", events
        reply, events = self._run_tool("query_logistics", {"order_id": target}, session, events)
        session.unresolved_streak = 0
        return reply or "暂时查不到物流信息，请稍后再试。", events

    def _do_after_sale_query(
        self, session: Session, intent: dict, events: list[dict]
    ) -> tuple[str, list[dict]]:
        slots = intent.get("slots") or {}
        args: dict = {}
        if slots.get("order_id"):
            args["order_id"] = slots["order_id"]
        if session.last_after_sale_id:
            args["after_sale_id"] = session.last_after_sale_id
        if not args:
            return "请提供订单号或售后单号，我帮您查询售后进度。", events
        reply, events = self._run_tool("query_after_sale", args, session, events)
        session.unresolved_streak = 0
        return reply or "暂时没有查到售后记录。", events

    def _do_refund(
        self,
        session: Session,
        text: str,
        intent: dict,
        retrieval: dict,
        events: list[dict],
    ) -> tuple[str, list[dict]]:
        order_id = (intent.get("slots") or {}).get("order_id") or session.last_order_id
        if not order_id:
            session.pending_action = "refund"
            return (
                "好的，我帮您办理退款/退货。\n请提供订单号（例如 EC20241108001），"
                "我确认订单状态后马上提交申请。",
                events,
            )

        order = next(
            (o for o in [self._order_snapshot(order_id)] if o),
            None,
        )
        refund_type = (
            "退货退款"
            if order and order.get("status_code") in ("delivered", "completed")
            else "退款"
        )
        reason = ORDER_ID_RE.sub("", text)
        reason = re.sub(r"^[\s，,。]*(?:订单)?[\s，,。]*", "", reason).strip(" ，,。！!") or "用户申请退款"
        args = {"order_id": order_id, "refund_type": refund_type, "reason": reason[:80]}
        reply, events = self._run_tool("create_refund", args, session, events)
        session.unresolved_streak = 0

        policy_tip = ""
        if retrieval.get("passed") and retrieval.get("results"):
            top = retrieval["results"][0]
            policy_tip = f"\n\n政策依据：{top['locator']}"
        return (reply or "退款申请提交失败，请稍后再试。") + policy_tip, events

    def _do_presale(
        self,
        session: Session,
        text: str,
        intent: dict,
        retrieval: dict,
        events: list[dict],
    ) -> tuple[str, list[dict]]:
        product_id = (intent.get("slots") or {}).get("product_id")
        product_reply = None
        if product_id:
            product_reply, events = self._run_tool(
                "query_product", {"product_id": product_id}, session, events
            )
        elif retrieval.get("passed") and retrieval.get("results"):
            product_reply = None

        if product_reply:
            missing = [
                word
                for group in PRESALE_ATTR_HINTS.values()
                for word in group
                if word in text.lower() and word not in product_reply.lower()
            ]
            if missing:
                product_reply += "\n\n商品详情页暂时没有标注这项参数，建议转人工确认。"
            session.unresolved_streak = 0
            return product_reply, events

        if retrieval.get("passed") and retrieval.get("results"):
            return self._knowledge_reply(retrieval, session), events

        session.unresolved_streak += 1
        return (
            "这个问题我在知识库里没有找到确切依据，为避免给您错误信息，先不猜测。\n"
            "您可以换个说法，或直接说商品名称（例如“耳机”“手环”）我帮您查参数。",
            events,
        )

    def _do_policy(
        self, session: Session, intent: dict, retrieval: dict, events: list[dict]
    ) -> tuple[str, list[dict]]:
        if retrieval.get("passed") and retrieval.get("results"):
            session.unresolved_streak = 0
            return self._knowledge_reply(retrieval, session), events

        session.unresolved_streak += 1
        return (
            "我们知识库里暂时没有这方面的明确规定，为了不给您错误信息，我先不猜测。\n"
            "如果比较着急，我可以帮您转人工客服确认。",
            events,
        )

    def _knowledge_reply(self, retrieval: dict, session: Session) -> str:
        results = retrieval.get("results") or []
        body_parts = []
        for item in results[:2]:
            body_parts.append(f"{item['text'].strip()}\n（来源：{item['locator']}）")
        body = "\n\n".join(body_parts)
        if len(body) > 620:
            body = body[:620].rstrip() + "…"
        session.last_retrieval = retrieval
        return (
            f"根据平台规则，为您整理如下：\n{body}\n\n"
            "如果这和您订单页显示的不一致，以订单页说明为准。需要我帮您办理具体的退款或退货吗？"
        )

    # ---------- 工具调用 ----------

    def _run_tool(
        self, name: str, args: dict, session: Session, events: list[dict]
    ) -> tuple[str | None, list[dict]]:
        events.append({"type": "tool_call", "name": name, "arguments": args})
        result = execute_tool(name, args, session)
        events.append(
            {
                "type": "tool_result",
                "name": name,
                "ok": bool(result.get("ok")),
                "message": str(result.get("message", ""))[:600],
                "source": result.get("source"),
                "degraded": result.get("degraded", False),
            }
        )
        return result.get("message"), events

    @staticmethod
    def _order_snapshot(order_id: str) -> dict | None:
        from . import mock_data

        return mock_data.ORDERS.get(order_id.upper())
