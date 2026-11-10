"""全量评测脚本。

用法：
    .venv\\Scripts\\python.exe scripts\\evaluate.py                          # 主测试集 -> eval/report.md
    .venv\\Scripts\\python.exe scripts\\evaluate.py --testset eval/adversarial.jsonl \
        --report eval/adversarial_report.md --badcases eval/adversarial_badcases.jsonl
    .venv\\Scripts\\python.exe scripts\\evaluate.py --limit 20               # 快速抽样
    .venv\\Scripts\\python.exe scripts\\evaluate.py --verbose                # 打印每条实际回复

指标口径（报告里也会写明）：
    自助解决率 = 未转人工且回答命中的样本数 / 总样本数（旧口径，分母含「本该转人工」）
    误转人工率 = 误转人工样本数 / 应自助样本数（本文件新增的核心指标）
    转人工率   = 触发硬规则转人工的样本数 / 总样本数
    答非所问率 = 未转人工但回答未命中期望关键词的样本数 / 总样本数
    幻觉率     = 知识库外问题中「未转人工且仍在编造答案」的占比
    平均轮次   = 所有会话的用户消息数总和 / 会话数（含多轮用例）
"""

from __future__ import annotations

import argparse
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

REFUSAL_MARKERS = [
    "没有找到",
    "没有这方面",
    "不知道",
    "暂时没有",
    "无法确认",
    "不猜测",
    "建议您联系人工",
    "转接人工",
    "转人工",
    "不在我的服务范围",
]


def load_testset(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def run_case(agent: Agent, case: dict) -> dict:
    mock_data.reset()
    session = Session("eval-" + case["id"])
    events = [event async for event in agent.chat(session, case["question"])]

    reply = "".join(e.get("content", "") for e in events if e["type"] == "text")
    intent_event = next((e for e in events if e["type"] == "intent"), {})
    retrieval_event = next((e for e in events if e["type"] == "retrieval"), {})
    handoff_event = next((e for e in events if e["type"] == "handoff"), None)

    turns = 1
    followup_replies = []
    for followup in case.get("followup") or []:
        turns += 1
        follow_events = [event async for event in agent.chat(session, followup)]
        followup_replies.append(
            {
                "question": followup,
                "reply": "".join(e.get("content", "") for e in follow_events if e["type"] == "text"),
                "handoff": any(e["type"] == "handoff" for e in follow_events),
            }
        )

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expect_intents": case.get("expect_intents") or [],
        "expect_handoff": bool(case.get("expect_handoff")),
        "expect_any": case.get("expect_any") or [],
        "intent": intent_event.get("intent"),
        "intent_label": intent_event.get("label"),
        "branch": intent_event.get("branch"),
        "intent_ok": intent_event.get("intent") in (case.get("expect_intents") or []),
        "handoff": handoff_event is not None,
        "handoff_rule": (handoff_event or {}).get("rule", {}).get("label") if handoff_event else None,
        "retrieval_method": retrieval_event.get("method_label"),
        "retrieval_confidence": retrieval_event.get("confidence"),
        "reply": reply,
        "answer_ok": any(keyword in reply for keyword in (case.get("expect_any") or [])),
        "turns": turns,
        "followups": followup_replies,
    }


def build_metrics(results: list[dict]) -> dict:
    total = len(results)
    handoff = sum(1 for r in results if r["handoff"])
    self_service = sum(
        1 for r in results if not r["handoff"] and r["answer_ok"] and r["expect_any"]
    ) + sum(1 for r in results if not r["handoff"] and not r["expect_any"] and r["intent_ok"])
    off_topic = sum(1 for r in results if not r["handoff"] and not r["answer_ok"] and r["expect_any"])

    expected_handoff = sum(1 for r in results if r["expect_handoff"])
    expected_self = total - expected_handoff
    mis_handoff = sum(1 for r in results if r["handoff"] and not r["expect_handoff"])
    missed_handoff = sum(1 for r in results if r["expect_handoff"] and not r["handoff"])

    out_of_kb = [r for r in results if r["category"] == "out_of_kb"]
    hallucinated = [
        r for r in out_of_kb
        if not r["handoff"] and not any(marker in r["reply"] for marker in REFUSAL_MARKERS)
    ]

    complaint = [r for r in results if r["category"] == "complaint"]
    complaint_intent_hit = sum(1 for r in complaint if r["intent"] == "complaint")
    complaint_branch_hit = sum(
        1 for r in complaint if r["intent"] == "complaint" and r["branch"] == "handoff"
    )

    turns = sum(r["turns"] for r in results)
    return {
        "total": total,
        "handoff": handoff,
        "handoff_rate": handoff / total if total else 0,
        "expected_handoff": expected_handoff,
        "expected_self_service": expected_self,
        "mis_handoff": mis_handoff,
        "mis_handoff_rate": mis_handoff / expected_self if expected_self else 0,
        "missed_handoff": missed_handoff,
        "self_service": self_service,
        "self_service_rate": self_service / total if total else 0,
        "off_topic": off_topic,
        "off_topic_rate": off_topic / total if total else 0,
        "out_of_kb": len(out_of_kb),
        "hallucinated": len(hallucinated),
        "hallucination_rate": len(hallucinated) / len(out_of_kb) if out_of_kb else 0,
        "avg_turns": turns / total if total else 0,
        "intent_accuracy": sum(1 for r in results if r["intent_ok"]) / total if total else 0,
        "complaint_intent_hit": complaint_intent_hit,
        "complaint_branch_hit": complaint_branch_hit,
        "complaint_total": len(complaint),
    }


def collect_badcases(results: list[dict]) -> list[dict]:
    bad = []
    for r in results:
        problems = []
        if r["handoff"] != r["expect_handoff"]:
            problems.append("转人工不符合预期")
        if not r["handoff"] and r["expect_any"] and not r["answer_ok"]:
            problems.append("回答未命中期望内容")
        if r["category"] == "out_of_kb" and not r["handoff"]:
            if not any(marker in r["reply"] for marker in REFUSAL_MARKERS):
                problems.append("知识库外仍编造答案")
        if problems:
            bad.append({**r, "problems": problems})
    return bad


def category_table(results: list[dict]) -> str:
    lines = [
        "| 分类 | 样本数 | 转人工率 | 自助解决率 | 答非所问率 | 误转人工率 |",
        "|---|---|---|---|---|---|",
    ]
    categories = []
    for r in results:
        if r["category"] not in categories:
            categories.append(r["category"])
    for category in categories:
        subset = [r for r in results if r["category"] == category]
        total = len(subset)
        handoff = sum(1 for r in subset if r["handoff"])
        self_service = sum(
            1 for r in subset if not r["handoff"] and r["answer_ok"] and r["expect_any"]
        ) + sum(1 for r in subset if not r["handoff"] and not r["expect_any"] and r["intent_ok"])
        off_topic = sum(
            1 for r in subset if not r["handoff"] and not r["answer_ok"] and r["expect_any"]
        )
        expected_self = sum(1 for r in subset if not r["expect_handoff"])
        mis = sum(1 for r in subset if r["handoff"] and not r["expect_handoff"])
        mis_rate = f"{mis / expected_self:.1%}" if expected_self else "-"
        lines.append(
            f"| {category} | {total} | {handoff / total:.1%} | "
            f"{self_service / total:.1%} | {off_topic / total:.1%} | {mis_rate} |"
        )
    return "\n".join(lines)


def comparison_table(baseline: dict | None, metrics: dict) -> list[str]:
    if not baseline:
        return []
    before = baseline["metrics"]
    rows = [
        ("自助解决率", "self_service_rate", "pct"),
        ("误转人工率", "mis_handoff_rate", "pct"),
        ("答非所问率", "off_topic_rate", "pct"),
        ("幻觉率", "hallucination_rate", "pct"),
        ("意图命中率", "intent_accuracy", "pct"),
        ("平均轮次", "avg_turns", "num"),
    ]
    lines = [
        "## 优化前后对比",
        "",
        f"- 对比基线：{baseline.get('label', '优化前')}（{baseline.get('note', '')}）",
        "",
        "| 指标 | 优化前 | 优化后 | 变化 |",
        "|---|---|---|---|",
    ]
    for label, key, kind in rows:
        old = before.get(key)
        new = metrics.get(key)
        if old is None or new is None:
            continue
        if kind == "pct":
            delta = new - old
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {label} | {old:.1%} | {new:.1%} | {sign}{delta:.1%} |")
        else:
            delta = new - old
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {label} | {old:.2f} | {new:.2f} | {sign}{delta:.2f} |")
    lines.append("")
    lines.append(
        f"- 投诉类主分支命中：优化前 {before.get('complaint_branch_hit', '-')}/"
        f"{before.get('complaint_total', '-')} → 优化后 {metrics['complaint_branch_hit']}/{metrics['complaint_total']}"
    )
    lines.append(
        f"- 应自助样本 {metrics['expected_self_service']} 条，误转人工 {metrics['mis_handoff']} 条；"
        f"应转人工 {metrics['expected_handoff']} 条，漏转 {metrics['missed_handoff']} 条"
    )
    lines.append("")
    return lines


def write_report(
    metrics: dict,
    results: list[dict],
    bad: list[dict],
    elapsed: float,
    report_path: Path,
    title: str,
    baseline: dict | None,
    testset_name: str,
) -> Path:
    kb = KnowledgeBase(settings.knowledge_dir, settings)
    lines = [
        f"# {title}",
        "",
        f"- 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 运行模式：**{settings.mode_label}**（provider={settings.provider}，model={settings.model if settings.mode == 'live' else 'local-rules'}）",
        f"- 检索方式：**{kb.method_reason}**",
        f"- 知识片段：{len(kb.chunks)} 个；数据源：{settings.tool_backend}",
        f"- 测试集：`{testset_name}`，{metrics['total']} 条"
        f"（知识库外诱导问题 {metrics['out_of_kb']} 条，应转人工 {metrics['expected_handoff']} 条）",
        f"- 总耗时：{elapsed:.1f}s",
        "",
        "## 一、核心指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "|---|---|---|",
        f"| 自助解决率（旧口径） | **{metrics['self_service_rate']:.1%}** | 未转人工且回答命中 / 总样本；分母含本该转人工，会低估系统 |",
        f"| 误转人工率（核心） | **{metrics['mis_handoff_rate']:.1%}** | 误转人工 {metrics['mis_handoff']} 条 / 应自助 {metrics['expected_self_service']} 条 |",
        f"| 转人工率 | **{metrics['handoff_rate']:.1%}** | 硬规则触发转人工 / 总样本 |",
        f"| 答非所问率 | **{metrics['off_topic_rate']:.1%}** | 未转人工但答非所问 / 总样本 |",
        f"| 幻觉率 | **{metrics['hallucination_rate']:.1%}** | 知识库外问题仍编造答案 / {metrics['out_of_kb']} 条知识库外问题 |",
        f"| 平均轮次 | **{metrics['avg_turns']:.2f}** | 用户消息数 / 会话数（含多轮用例） |",
        f"| 意图命中率（辅助） | {metrics['intent_accuracy']:.1%} | 意图识别结果落在预期集合内 |",
        "",
        "## 二、分类表现",
        "",
        category_table(results),
        "",
        "## 指标定义",
        "",
        "- **自助解决率（旧口径）**：未转人工且答案命中关键信息 / 全部样本。分母包含「本该转人工」的投诉与超纲问题，因此会低估系统能力。",
        "- **误转人工率（核心）**：误转人工数 / 应自助样本数。只统计「本就该机器人处理」的样本中被错误转人工的比例，更贴近线上体验。",
        "- **转人工率**：命中硬规则（投诉/纠纷/安全/法律/情绪/低置信/两轮未解决）的样本占比。",
        "- **答非所问率**：没有转人工、但回答没有覆盖预期关键信息的比例。",
        "- **幻觉率**：知识库外问题中，机器人未转人工且仍在给出具体答案（而非明确说不知道）的比例。",
        "- **平均轮次**：会话内用户消息的平均条数，轮次越低说明一次说清的比例越高。",
        "",
        "## Badcase 摘要",
        "",
    ]

    if baseline:
        compare = comparison_table(baseline, metrics)
        insert_at = lines.index("## 指标定义")
        lines[insert_at:insert_at] = compare
    if bad:
        lines.append(f"共 {len(bad)} 条，完整明细见同目录 badcases 文件。")
        lines.append("")
        lines.append("| 用例 | 分类 | 问题 | 实际意图 | 实际转人工 | 问题 |")
        lines.append("|---|---|---|---|---|---|")
        for item in bad[:20]:
            question = item["question"].replace("|", "｜")
            lines.append(
                f"| {item['id']} | {item['category']} | {question} | "
                f"{item['intent_label']} | {'是' if item['handoff'] else '否'} | "
                f"{'、'.join(item['problems'])} |"
            )
    else:
        lines.append("本轮没有 badcase。")

    if settings.mode == "live":
        mode_limit = (
            f"- 当前为真实模型（{settings.model}）跑分，检索方式见上方「检索方式」；"
            "与 `eval/report.md` 的规则引擎分数**不可直接比较**，两套结果只做能力对照、不混算总分。"
        )
        wording_limit = (
            "- 「回答命中」按预期关键词匹配，真实模型措辞自由，"
            "语义正确但未包含关键词的回答会被判为答非所问，需结合 badcase 人工复核。"
        )
    else:
        mode_limit = "- 当前为演示模式（本地规则引擎），数字只反映规则与知识库能力；接真实模型后需重跑。"
        wording_limit = ""

    lines += [
        "",
        "## 评测方法限制（重要）",
        "",
        "- 主测试集与意图/兜底规则是同一轮开发产出，属于**自查自测**；0 误转、0 幻觉不能直接作为上线依据。",
        "- 业务方需要独立标注一批线上真实会话作为盲测集，并定期复核 `eval/handoff_analysis.md` 里的归因。",
        "- 对抗集 `eval/adversarial.jsonl` 单独统计、单独出报告，不与主测试集混算总分。",
        mode_limit,
    ]
    if wording_limit:
        lines.append(wording_limit)
    lines += [
        "",
        "## 复现方式",
        "",
        "```powershell",
        ".venv\\Scripts\\python.exe scripts\\build_testset.py",
        ".venv\\Scripts\\python.exe scripts\\evaluate.py",
        ".venv\\Scripts\\python.exe scripts\\evaluate.py --testset eval/adversarial.jsonl "
        "--report eval/adversarial_report.md --badcases eval/adversarial_badcases.jsonl",
        "```",
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


async def main_async(args: argparse.Namespace) -> None:
    started = datetime.now()
    testset_path = BASE / args.testset
    cases = load_testset(testset_path)
    if args.limit:
        cases = cases[: args.limit]

    kb = KnowledgeBase(settings.knowledge_dir, settings)
    agent = Agent(settings, kb)
    print(f"模式：{settings.mode_label}｜检索：{kb.method_reason}｜样本：{len(cases)}")

    results = []
    for index, case in enumerate(cases, 1):
        result = await run_case(agent, case)
        results.append(result)
        if args.verbose:
            flag = "OK" if result["handoff"] == result["expect_handoff"] else "!!"
            print(f"[{index:03d}] {flag} {case['question']} -> {result['reply'][:80]!r}")
        elif index % 20 == 0:
            print(f"  已跑 {index}/{len(cases)}")

    metrics = build_metrics(results)
    bad = collect_badcases(results)
    elapsed = (datetime.now() - started).total_seconds()

    baseline = None
    if args.baseline:
        baseline = json.loads((BASE / args.baseline).read_text(encoding="utf-8"))

    badcase_path = BASE / args.badcases
    with badcase_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in bad:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    report_path = write_report(
        metrics,
        results,
        bad,
        elapsed,
        BASE / args.report,
        args.title,
        baseline,
        args.testset,
    )

    if args.json_out:
        payload = {
            "label": args.title,
            "metrics": metrics,
            "note": f"{args.testset}，{settings.mode_label}",
        }
        (BASE / args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print("\n===== 指标 =====")
    print(f"样本数        : {metrics['total']}")
    print(f"自助解决率    : {metrics['self_service_rate']:.1%}")
    print(f"误转人工率    : {metrics['mis_handoff_rate']:.1%}（{metrics['mis_handoff']}/{metrics['expected_self_service']}）")
    print(f"转人工率      : {metrics['handoff_rate']:.1%}")
    print(f"答非所问率    : {metrics['off_topic_rate']:.1%}")
    print(f"幻觉率        : {metrics['hallucination_rate']:.1%}（{metrics['hallucinated']}/{metrics['out_of_kb']}）")
    print(f"平均轮次      : {metrics['avg_turns']:.2f}")
    print(f"意图命中率    : {metrics['intent_accuracy']:.1%}")
    print(f"投诉主分支    : {metrics['complaint_branch_hit']}/{metrics['complaint_total']}")
    print(f"badcase       : {len(bad)} 条 -> {badcase_path}")
    print(f"报告          : {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--testset", default="eval/testset.jsonl")
    parser.add_argument("--report", default="eval/report.md")
    parser.add_argument("--badcases", default="eval/badcases.jsonl")
    parser.add_argument("--baseline", default="", help="优化前指标 JSON，用于生成对比表")
    parser.add_argument("--json-out", default="", help="把本次指标写入 JSON")
    parser.add_argument("--title", default="电商客服 Agent 评测报告")
    main_args = parser.parse_args()
    asyncio.run(main_async(main_args))


if __name__ == "__main__":
    main()
