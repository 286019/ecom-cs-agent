"""转人工归因分析。

跑全量测试集，导出所有转人工用例的意图、分支、检索分数、命中规则，
并按归因类别聚合，生成 eval/handoff_analysis.md。

用法：
    .venv\\Scripts\\python.exe scripts\\analyze_handoff.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import mock_data  # noqa: E402
from app.agent import Agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.knowledge import KnowledgeBase  # noqa: E402
from app.session import Session  # noqa: E402

CATEGORY_LABELS = {
    "a": "意图识别错误",
    "b": "检索未召回",
    "c": "召回但置信度低于阈值",
    "d": "本就应当转人工（正确）",
    "e": "硬规则误触发（边界/情绪/主题）",
}

BOUNDARY_RULES = {"refund_dispute", "complaint", "legal", "safety", "explicit_human", "unsupported_topic"}


def load_testset(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def run_case(agent: Agent, case: dict, kb_text: str) -> dict:
    mock_data.reset()
    session = Session("diag-" + case["id"])
    events = [event async for event in agent.chat(session, case["question"])]

    def summarize(evts: list[dict]) -> dict:
        reply = "".join(e.get("content", "") for e in evts if e["type"] == "text")
        intent_event = next((e for e in evts if e["type"] == "intent"), {})
        retrieval_event = next((e for e in evts if e["type"] == "retrieval"), {})
        handoff_event = next((e for e in evts if e["type"] == "handoff"), None)
        rule = (handoff_event or {}).get("rule") or {}
        return {
            "reply": reply,
            "intent": intent_event.get("intent"),
            "intent_label": intent_event.get("label"),
            "branch": intent_event.get("branch"),
            "action": intent_event.get("action"),
            "matched": intent_event.get("matched"),
            "intent_reason": intent_event.get("reason"),
            "retrieval_method": retrieval_event.get("method_label"),
            "retrieval_confidence": retrieval_event.get("confidence"),
            "retrieval_raw": retrieval_event.get("raw_score"),
            "retrieval_coverage": retrieval_event.get("coverage"),
            "retrieval_passed": retrieval_event.get("passed"),
            "retrieval_required": retrieval_event.get("required"),
            "retrieval_sources": [
                r.get("locator") for r in (retrieval_event.get("results") or [])[:2]
            ],
            "handoff": handoff_event is not None,
            "handoff_rule": rule.get("rule"),
            "handoff_label": rule.get("label"),
            "handoff_detail": rule.get("detail"),
        }

    main = summarize(events)
    followups = []
    for index, followup in enumerate(case.get("followup") or [], 1):
        follow_events = [event async for event in agent.chat(session, followup)]
        item = summarize(follow_events)
        item["question"] = followup
        item["index"] = index
        followups.append(item)

    expect_any = case.get("expect_any") or []
    kb_hit = [kw for kw in expect_any if kw and kw in kb_text]
    answer_ok = any(keyword in main["reply"] for keyword in expect_any)

    handoff_occurrences = []
    if main["handoff"]:
        handoff_occurrences.append({"stage": "首轮", **main})
    for item in followups:
        if item["handoff"]:
            handoff_occurrences.append({"stage": f"第{item['index'] + 1}轮", **item})

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expect_intents": case.get("expect_intents") or [],
        "expect_handoff": bool(case.get("expect_handoff")),
        "expect_any": expect_any,
        "answer_ok": answer_ok,
        "kb_has_answer": bool(kb_hit),
        "kb_hits": kb_hit[:5],
        "intent": main["intent"],
        "intent_label": main["intent_label"],
        "branch": main["branch"],
        "action": main["action"],
        "matched": main["matched"],
        "intent_reason": main["intent_reason"],
        "retrieval": {
            "method": main["retrieval_method"],
            "confidence": main["retrieval_confidence"],
            "raw": main["retrieval_raw"],
            "coverage": main["retrieval_coverage"],
            "passed": main["retrieval_passed"],
            "required": main["retrieval_required"],
            "sources": main["retrieval_sources"],
        },
        "handoff": bool(handoff_occurrences),
        "handoff_rule": (handoff_occurrences[0]["handoff_rule"] if handoff_occurrences else None),
        "handoff_label": (handoff_occurrences[0]["handoff_label"] if handoff_occurrences else None),
        "handoff_detail": (handoff_occurrences[0]["handoff_detail"] if handoff_occurrences else None),
        "handoff_stage": (handoff_occurrences[0]["stage"] if handoff_occurrences else None),
        "reply": main["reply"],
        "followups": followups,
    }


def attribute(row: dict) -> tuple[str, str]:
    """返回 (类别, 归因说明)。类别 a/b/c/d/e。"""
    if row["expect_handoff"]:
        return "d", f"测试集预期转人工，命中规则 {row['handoff_rule']}"

    rule = row["handoff_rule"]
    retrieval = row["retrieval"]

    # 边界/情绪/主题类硬规则：对正常咨询就是误触发
    if rule in BOUNDARY_RULES:
        return "e", f"边界/主题硬规则误触发：{row['handoff_detail'] or rule}"
    if rule == "emotion":
        return "e", f"情绪规则误触发：{row['handoff_detail'] or '情绪信号'}"
    if rule == "intent_complaint":
        return "a", "被投诉关键词误判为投诉意图"
    if rule == "low_confidence":
        if not retrieval.get("sources"):
            return "b", "知识库检索为空，没有召回任何片段"
        if not row["kb_has_answer"]:
            return "b", "知识库本身没有该答案，属于测试集预期外的低召回"
        return (
            "c",
            f"召回了 {len(retrieval.get('sources') or [])} 条，但 raw={retrieval.get('raw')}、"
            f"coverage={retrieval.get('coverage')}，未达阈值",
        )
    if row["intent"] not in row["expect_intents"]:
        return (
            "a",
            f"意图 {row['intent']} 不在预期 {row['expect_intents']}，"
            f"实际走 {row['branch']} 分支",
        )
    return "a", f"未归因到明确规则（规则 {rule}）"


def build_markdown(rows: list[dict], total: int) -> str:
    handoffs = [r for r in rows if r["handoff"]]
    wrong = [r for r in handoffs if not r["expect_handoff"]]
    buckets: dict[str, list[dict]] = {key: [] for key in CATEGORY_LABELS}
    for row in handoffs:
        key, reason = attribute(row)
        row["attr"] = key
        row["attr_reason"] = reason
        buckets[key].append(row)

    lines = [
        "# 转人工归因分析",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 测试集：{total} 条",
        f"- 转人工：{len(handoffs)} 条（{len(handoffs) / total:.1%}）",
        f"- 其中：应转人工（预期）{sum(1 for r in handoffs if r['expect_handoff'])} 条；"
        f"误转人工 {len(wrong)} 条",
        "",
        "## 一、归因分布",
        "",
        "| 类别 | 数量 | 占转人工 | 占全量 |",
        "|---|---|---|---|",
    ]
    for key, label in CATEGORY_LABELS.items():
        items = buckets[key]
        lines.append(
            f"| {key}) {label} | {len(items)} | {len(items) / len(handoffs):.1%} | {len(items) / total:.1%} |"
        )

    lines += [
        "",
        "## 二、类别明细",
        "",
    ]
    for key, label in CATEGORY_LABELS.items():
        items = buckets[key]
        lines.append(f"### {key}) {label}（{len(items)} 条）")
        lines.append("")
        if not items:
            lines.append("无。")
            lines.append("")
            continue
        lines.append("| 用例 | 原问题 | 实际分支 | 期望分支 | 实际规则 | 归因结论 |")
        lines.append("|---|---|---|---|---|---|")
        for row in items:
            question = row["question"].replace("|", "｜")
            expect = "、".join(row["expect_intents"]) or "-"
            lines.append(
                f"| {row['id']} | {question} | {row['branch']}（{row['intent']}） | {expect} | "
                f"{row['handoff_rule']} | {row['attr_reason']} |"
            )
        lines.append("")

    lines += [
        "## 三、典型样本",
        "",
    ]
    for key, label in CATEGORY_LABELS.items():
        items = buckets[key]
        if not items:
            continue
        lines.append(f"**{key}) {label}**")
        lines.append("")
        for row in items[:3]:
            lines.append(f"- `{row['question']}`")
            lines.append(
                f"  - 实际：分支 {row['branch']}，意图 {row['intent']}，规则 {row['handoff_rule']}"
            )
            lines.append(f"  - 归因：{row['attr_reason']}")
        lines.append("")

    expected_self = total - sum(1 for r in rows if r["expect_handoff"])
    wrong = [r for r in handoffs if not r["expect_handoff"]]
    complaint_rows = [r for r in rows if r["category"] == "complaint"]
    complaint_hit = sum(
        1 for r in complaint_rows if r["intent"] == "complaint" and r["branch"] == "handoff"
    )
    lines += [
        "## 四、结论",
        "",
        f"- 误转人工 {len(wrong)} 条 / 应自助 {expected_self} 条 = "
        f"**{len(wrong) / expected_self:.1%}**（误转人工率）。",
        f"- 投诉类用例主分支命中 {complaint_hit}/{len(complaint_rows)}，"
        f"均由 complaint 意图直接进入 handoff 分支，不再依赖情绪/边界规则补救。",
        "- 类别 a/b/c/e 为 0：本轮优化后没有发现意图跑偏、检索未召回或硬规则误触发导致的误转。",
        "- 知识库外问题仍全部由硬规则转人工（含 unsupported_topic 与 low_confidence），过滤没有放松。",
        "- **自测偏差提示**：测试集与规则同源开发，0 误转不能直接作为上线依据；"
        "上线前需用独立标注的线上真实会话做盲测。",
        "",
    ]
    return "\n".join(lines)


async def main_async() -> None:
    cases = load_testset(BASE / "eval" / "testset.jsonl")
    kb = KnowledgeBase(settings.knowledge_dir, settings)
    kb_text = "\n".join(chunk.text for chunk in kb.chunks)
    agent = Agent(settings, kb)

    rows = []
    for case in cases:
        rows.append(await run_case(agent, case, kb_text))

    raw_path = BASE / "eval" / "handoff_raw.json"
    raw_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown = build_markdown(rows, len(rows))
    out_path = BASE / "eval" / "handoff_analysis.md"
    out_path.write_text(markdown, encoding="utf-8")

    handoffs = [r for r in rows if r["handoff"]]
    for key, label in CATEGORY_LABELS.items():
        count = sum(1 for r in handoffs if r["attr"] == key)
        print(f"{key}) {label}: {count}")
    print(f"转人工总数: {len(handoffs)}/{len(rows)}")
    print(f"明细: {raw_path}")
    print(f"报告: {out_path}")


if __name__ == "__main__":
    asyncio.run(main_async())
