"""端到端自测脚本：模拟网页端的 SSE 调用，打印完整对话过程。

用法（服务已启动）：
    .venv\\Scripts\\python.exe scripts\\selftest.py
    .venv\\Scripts\\python.exe scripts\\selftest.py --base http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent

SCENARIOS = [
    ("查订单", "帮我查一下订单 EC20241108001", "A"),
    ("多轮记忆·查物流", "那这个订单的物流到哪了", "A"),
    ("退换货政策", "你们支持七天无理由退货吗？退货运费谁承担？", "B"),
    ("发起退款", "订单 EC20241105004 我要申请退货退款，杯盖有划痕", "B"),
    ("查询售后进度", "售后进度怎么样了", "B"),
    ("商品咨询", "AirSound Pro 耳机多少钱，还有货吗？", "C"),
    ("转人工", "我要投诉！你们发错货了，必须赔偿我双倍！", "D"),
]


def resolve_base(explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip("/")
    url_file = ROOT / "logs" / "server_url.txt"
    if url_file.exists():
        return url_file.read_text(encoding="utf-8").strip().rstrip("/")
    return "http://127.0.0.1:8000"


def run_turn(client: httpx.Client, base: str, session_id: str, message: str) -> tuple[str, list[str], str, str]:
    tools: list[str] = []
    text = ""
    mode = ""
    tickets: list[str] = []
    resolved_session = session_id
    payload = {"session_id": session_id, "message": message}

    with client.stream("POST", f"{base}/api/chat", json=payload, timeout=120) as response:
        response.raise_for_status()
        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                for line in block.splitlines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    etype = event.get("type")
                    if etype == "meta":
                        mode = f"{event['mode_label']} / {event['provider_label']} / {event['model']}"
                        resolved_session = event.get("session_id") or resolved_session
                    elif etype == "tool_call":
                        args = event.get("arguments") or {}
                        arg_text = ", ".join(f"{k}={v}" for k, v in args.items())
                        tools.append(f"{event['name']}({arg_text})")
                    elif etype == "tool_result":
                        status = "成功" if event.get("ok") else "失败"
                        tools.append(f"  └ {event['name']} {status}: {str(event.get('message', ''))[:120]}")
                    elif etype == "text":
                        text += event.get("content", "")
                    elif etype == "handoff":
                        ticket = event.get("ticket") or {}
                        tickets.append(f"{ticket.get('ticket_id')} / {ticket.get('reason')}")
    return text.strip(), tools, mode + ("\n工单: " + "; ".join(tickets) if tickets else ""), resolved_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None, help="服务地址，默认读取 logs/server_url.txt")
    args = parser.parse_args()
    base = resolve_base(args.base)

    print(f"服务地址：{base}")
    try:
        health = httpx.get(f"{base}/health", timeout=10).json()
    except Exception as exc:
        print(f"无法连接服务：{exc}")
        return 1

    print(f"运行模式：{health['mode_label']} / {health['provider_label']} / {health['model']}")
    print(f"知识库片段：{health['knowledge_chunks']}，端口：{health['port']}")
    print("=" * 78)

    sessions: dict[str, str] = {}
    with httpx.Client() as client:
        for index, (label, message, group) in enumerate(SCENARIOS, 1):
            print(f"\n【场景 {index}】{label}")
            print(f"用户：{message}")
            reply, tools, mode, new_session = run_turn(client, base, sessions.get(group), message)
            sessions[group] = new_session
            if tools:
                print("工具调用：")
                for item in tools:
                    print(f"  {item}")
            print(f"客服：{reply}")
            print(f"（{mode.splitlines()[0]}）")
        print("\n" + "=" * 78)
        for group, sid in sessions.items():
            snapshot = httpx.get(f"{base}/api/session/{sid}", timeout=10)
            if snapshot.status_code == 200:
                data = snapshot.json()
                print(f"会话 {group}：{data['turns']} 轮，记忆订单号={data['last_order_id']}，工单={bool(data['handoff'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
