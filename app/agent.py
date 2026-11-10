"""对话编排：边界 → 意图 → 检索 → 分支 → 兜底。

一次对话的固定顺序（真实模型与演示模式完全一致）：
1. 记住订单号等事实，记录用户消息
2. 意图识别（结构化输出，SSE 推给前端）
3. 硬规则兜底（人工/投诉/情绪/安全/法律）→ 直接转人工
4. 按分支需要检索知识库，返回检索方式与置信度
5. 低置信 / 连续两轮未解决 → 转人工
6. 进入分支：真实模型用分支独立提示词，演示模式用本地引擎
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

from . import handoff, postcheck
from .branches import BRANCH_TOOLS, DemoEngine, build_prompt
from .config import Settings
from .intent import classify
from .knowledge import KnowledgeBase
from .llm import LLMClient, LLMError
from .session import Session
from .tools import TOOL_SCHEMAS, execute_tool

log = logging.getLogger("ecom.agent")

UNRESOLVED_MARKERS = ["无法回答", "无法帮您", "暂时无法", "没有找到相关", "不确定", "不清楚", "建议您联系人工"]

BRANCH_SUGGESTIONS = {
    "handoff": "投诉/纠纷类诉求，请人工优先安抚并按平台赔付流程处理。",
    "policy": "用户询问政策但知识库无依据，请人工确认后回复。",
    "presale": "商品参数问题知识库未覆盖，请人工核实商品资料。",
    "after_sale": "售后问题机器人未能解决，请人工核对订单与售后单。",
}


class Agent:
    def __init__(self, settings: Settings, kb: KnowledgeBase):
        self.settings = settings
        self.kb = kb
        self.local = DemoEngine(kb)
        self.llm = LLMClient(settings) if settings.mode == "live" else None

    async def chat(self, session: Session, text: str) -> AsyncIterator[dict]:
        text = (text or "").strip()
        if not text:
            yield {"type": "text", "content": "您好，请说说您遇到的问题，我来帮您处理。"}
            return

        session.remember_facts(text)
        session.add_message("user", text)
        log.info("session=%s user=%s", session.session_id, text[:120])

        intent = classify(text, session)
        intent_payload = intent.as_dict()
        session.record_intent(intent_payload)
        yield {"type": "intent", **intent_payload}

        # 1) 硬规则兜底：投诉、赔偿、情绪、安全、法律、主动要人工
        decision = handoff.decide(text, session, intent_payload, retrieval=None)
        if decision.triggered:
            async for event in self._transfer(session, decision, intent_payload, None):
                yield event
            return

        # 2) 知识检索（只有需要知识的分支才检索，避免无谓开销）
        retrieval = None
        if intent.needs_knowledge:
            result = self.kb.search(text, top_k=3)
            required = not (intent.key == "after_sale" and intent.action == "apply")
            # 售前只要命中了具体商品，参数/价格以工具实时数据为准，不因知识库低分转人工
            if intent.key == "presale" and (intent.slots or {}).get("product_id"):
                required = False
            result["required"] = required
            result["used"] = True
            retrieval = result
            if result["results"]:
                yield {
                    "type": "knowledge",
                    "sources": self.kb.sources_payload(result["results"]),
                    "method": result["method"],
                }
        yield {"type": "retrieval", **(retrieval or {
            "method": "none",
            "method_label": "未使用知识库",
            "method_reason": "当前分支依赖工具实时数据，无需检索",
            "confidence": 0.0,
            "threshold": 0.0,
            "passed": True,
            "degraded": False,
            "results": [],
            "used": False,
            "required": False,
        })}

        # 3) 检索置信度不足 / 连续两轮未解决 → 硬规则转人工
        decision = handoff.decide(text, session, intent_payload, retrieval=retrieval)
        if decision.triggered:
            async for event in self._transfer(session, decision, intent_payload, retrieval):
                yield event
            return

        # 4) 进入分支
        if self.llm:
            emitted = False
            try:
                async for event in self._live_chat(session, text, intent_payload, retrieval):
                    if event["type"] == "text" and event.get("content"):
                        emitted = True
                    yield event
                return
            except LLMError as exc:
                log.warning("模型调用失败，回退本地引擎：%s", exc)
                if emitted:
                    yield {"type": "text", "content": "\n\n（模型连接中断，本轮回复不完整，请稍后重试。）"}
                    return
                yield {
                    "type": "notice",
                    "content": f"真实模型调用失败（{exc}），已自动切换到本地演示引擎。",
                }

        async for event in self.local.handle(session, text, intent_payload, retrieval):
            yield event

    # ---------- 真实模型链路 ----------

    async def _live_chat(
        self,
        session: Session,
        text: str,
        intent: dict,
        retrieval: dict | None,
    ) -> AsyncIterator[dict]:
        assert self.llm is not None
        branch = intent.get("branch", "chitchat")
        allowed = BRANCH_TOOLS.get(branch, [])
        tools = [
            schema
            for schema in TOOL_SCHEMAS
            if schema["function"]["name"] in allowed
        ] or None

        context = self.kb.format_context(retrieval["results"]) if retrieval else ""
        messages: list[dict] = [
            {"role": "system", "content": build_prompt(intent, session, context)}
        ] + session.history()

        final_text = ""
        tool_results: list[dict] = []
        for _ in range(self.settings.max_tool_rounds):
            buffer = ""
            display = ""
            guard = postcheck.RefusalGuard()
            calls: list[dict] = []
            async for kind, payload in self.llm.stream_turn(messages, tools):
                if kind == "text":
                    buffer += payload
                    visible = guard.feed(payload)
                    if visible:
                        display += visible
                        yield {"type": "text", "content": visible}
                else:
                    calls = payload
            tail = guard.flush()
            if tail:
                display += tail
                yield {"type": "text", "content": tail}

            if not calls:
                final_text = display.strip()
                break

            messages.append({"role": "assistant", "content": buffer or "", "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "name": name, "arguments": args}
                started = datetime.now()
                result = execute_tool(name, args, session)
                tool_results.append({"name": name, "result": result})
                elapsed = (datetime.now() - started).total_seconds() * 1000
                log.info(
                    "session=%s tool=%s args=%s ok=%s %.1fms",
                    session.session_id, name, args, result.get("ok"), elapsed,
                )
                yield {
                    "type": "tool_result",
                    "name": name,
                    "ok": bool(result.get("ok")),
                    "message": str(result.get("message", ""))[:600],
                    "source": result.get("source"),
                    "degraded": result.get("degraded", False),
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if name == "handoff_to_human" and result.get("ok") and session.handoff:
                    yield {"type": "handoff", "ticket": session.handoff, "rule": {"label": "模型主动转接"}}

            if session.handoff:
                final_text = buffer.strip() or "已为您转接人工客服，请稍候。"
                break
        else:
            decision = handoff.HandoffDecision(
                triggered=True,
                rule_key="tool_rounds",
                label="工具调用轮次超限",
                reason="处理轮次超限",
                detail=f"超过 {self.settings.max_tool_rounds} 轮仍未完成",
            )
            async for event in self._transfer(session, decision, intent, retrieval):
                yield event
            return

        if not final_text:
            final_text = "抱歉，我暂时没有组织好答案，请再描述一下您的问题。"

        # 确定性后校验：工具已返回的规格字段，不允许被回答成「未标注」；多订单必须列出单号
        if not session.handoff:
            corrections = [
                postcheck.correct_unstated_fields(text, final_text, tool_results),
                postcheck.correct_missing_orders(final_text, tool_results),
            ]
            for correction in corrections:
                if not correction:
                    continue
                log.warning("session=%s postcheck corrected: %s", session.session_id, correction)
                yield {"type": "text", "content": "\n\n" + correction}
                final_text = f"{final_text}\n\n{correction}"

        if not session.handoff and any(marker in final_text for marker in UNRESOLVED_MARKERS):
            session.unresolved_streak += 1
            decision = handoff.decide(text, session, intent, retrieval=None)
            if decision.triggered:
                async for event in self._transfer(session, decision, intent, retrieval):
                    yield event
            else:
                yield {"type": "text", "content": "\n\n（如果还需要帮助，可以直接说“转人工”。）"}
        elif final_text:
            session.unresolved_streak = 0

        session.add_message("assistant", final_text)
        log.info("session=%s assistant=%s", session.session_id, final_text[:120])

    # ---------- 硬规则转人工 ----------

    async def _transfer(
        self,
        session: Session,
        decision: handoff.HandoffDecision,
        intent: dict,
        retrieval: dict | None,
    ) -> AsyncIterator[dict]:
        context = handoff.build_context(
            intent,
            decision,
            retrieval=retrieval,
            suggestion=BRANCH_SUGGESTIONS.get(intent.get("branch"), ""),
        )
        yield {
            "type": "tool_call",
            "name": "handoff_to_human",
            "arguments": {"reason": decision.reason},
        }
        result = execute_tool(
            "handoff_to_human",
            {"reason": decision.reason},
            session,
        )
        if not session.handoff:
            session.create_handoff(decision.reason, None, context)
        else:
            # 补齐触发规则等上下文字段
            session.handoff["rule"] = decision.rule_key
            session.handoff["summary"] = session.build_summary(decision.reason, context)

        yield {
            "type": "tool_result",
            "name": "handoff_to_human",
            "ok": bool(result.get("ok")),
            "message": str(result.get("message", ""))[:600],
        }
        ticket = session.handoff
        yield {
            "type": "handoff",
            "ticket": ticket,
            "rule": decision.as_dict(),
        }

        message = (
            f"已为您转接人工客服，工单号 {ticket['ticket_id'] if ticket else '处理中'}。\n"
            f"转接原因：{decision.reason}。\n"
            "人工客服会带着完整上下文继续处理，您无需重复描述。"
        )
        async for chunk in self.local._stream_text(message):
            yield chunk
        session.add_message("assistant", message)
        log.info(
            "session=%s handoff rule=%s reason=%s ticket=%s",
            session.session_id, decision.rule_key, decision.reason,
            ticket and ticket.get("ticket_id"),
        )
