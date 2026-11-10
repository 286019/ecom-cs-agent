"""工具层：schema 定义 + 执行分发。

工具调用走模型原生 function calling（OpenAI tools 协议），
本地演示引擎复用同一套工具函数，保证两种模式行为一致。
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import mock_data
from .config import settings
from .datasource import DataSource
from .session import Session

# 数据源开关：mock（默认）/ http（真实接口），由 .env 的 TOOL_BACKEND 控制
DATASOURCE = DataSource(settings)

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "按订单号或收货手机号后四位查询订单状态、商品明细、实付金额、收货信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，例如 EC20241108001"},
                    "phone_last4": {"type": "string", "description": "收货手机号后四位，例如 8821"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_logistics",
            "description": "查询订单的物流轨迹、当前运输状态和运单号。用户问运单号、快递单号、到哪了、物流进度、是否签收时都必须调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，例如 EC20241108001"},
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_product",
            "description": "查询商品的价格、库存、规格、优惠活动和发货时效。返回的 specs 是唯一可信来源，未列出的参数视为未标注。支持按商品名关键词或商品 ID 查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "商品名称关键词，例如 耳机、手环"},
                    "product_id": {"type": "string", "description": "商品 ID，例如 P1001"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_refund",
            "description": "为已支付的订单发起退款或退货退款申请，返回售后单号和审核状态。仅在用户明确要求退款/退货时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "refund_type": {
                        "type": "string",
                        "enum": ["退款", "退货退款"],
                        "description": "售后类型，未收到货选退款，已收到货选退货退款",
                    },
                    "reason": {"type": "string", "description": "用户给出的退款原因"},
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_after_sale",
            "description": "按订单号或售后单号查询售后处理进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "after_sale_id": {"type": "string", "description": "售后单号，例如 AS20241107001"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_human",
            "description": "当用户投诉、情绪激动、要求赔偿、或问题无法解决时，转接人工客服并生成工单摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "转人工原因，例如 投诉 / 要求赔偿 / 无法解答"},
                    "summary": {"type": "string", "description": "给人工客服的问题摘要，包含订单号等关键信息"},
                },
                "required": ["reason"],
            },
        },
    },
]


def _fmt_money(value: float) -> str:
    return f"¥{value:.2f}"


def query_order(args: dict, session: Session) -> dict:
    order_id = (args.get("order_id") or "").strip() or session.last_order_id
    phone_last4 = (args.get("phone_last4") or "").strip() or session.last_phone_tail
    if not order_id and not phone_last4:
        return {"ok": False, "message": "请提供订单号，或收货手机号后四位，我来帮您查询。"}

    orders, meta = DATASOURCE.orders(order_id if order_id else None, None if order_id else phone_last4)
    if not orders:
        return {
            "ok": False,
            "message": f"没有找到订单 {order_id or '尾号' + str(phone_last4)}，请核对一下订单号是否正确。",
            "source": meta["source"],
        }

    items = []
    for order in orders:
        items.append(
            {
                "order_id": order["order_id"],
                "status": order["status"],
                "created_at": order["created_at"],
                "paid_amount": order["paid_amount"],
                "products": [f"{i['name']} ×{i['qty']}" for i in order["items"]],
                "carrier": order["carrier"],
                "tracking_no": order["tracking_no"],
                "eta": order["eta"],
                "address": order["address"],
            }
        )

    if len(items) == 1:
        o = items[0]
        parts = [
            f"订单 {o['order_id']} 当前状态：{o['status']}。",
            f"商品：{'、'.join(o['products'])}",
            f"实付金额：{_fmt_money(o['paid_amount'])}，下单时间：{o['created_at']}。",
        ]
        if o["carrier"]:
            parts.append(f"承运商：{o['carrier']}，运单号：{o['tracking_no']}。")
        parts.append(f"预计送达：{o['eta']}。")
        message = "\n".join(parts)
    else:
        lines = [f"手机尾号 {phone_last4} 名下共有 {len(items)} 个订单："]
        for o in items:
            lines.append(f"- {o['order_id']}｜{o['status']}｜{'、'.join(o['products'])}｜{_fmt_money(o['paid_amount'])}")
        message = "\n".join(lines) + "\n您想看哪一个订单的详情？直接发订单号即可。"

    return {"ok": True, "message": message, "data": items, "source": meta["source"], "degraded": meta["degraded"]}


def query_logistics(args: dict, session: Session) -> dict:
    order_id = (args.get("order_id") or "").strip() or session.last_order_id
    if not order_id:
        return {"ok": False, "message": "请提供订单号，我帮您查物流。"}

    logistics, meta = DATASOURCE.logistics(order_id)
    if not logistics:
        order = mock_data.ORDERS.get(order_id.upper())
        if order and not order["carrier"]:
            return {
                "ok": False,
                "message": f"订单 {order_id} 还没有发货，暂时没有物流信息。当前状态：{order['status']}，{order['eta']}。",
                "source": meta["source"],
            }
        return {"ok": False, "message": f"未查到订单 {order_id} 的物流信息，请确认订单号是否正确。", "source": meta["source"]}

    lines = [
        f"订单 {order_id} 物流（{logistics['carrier']}，运单号 {logistics['tracking_no']}）",
        f"当前状态：{logistics['current']}",
        "最新轨迹：",
    ]
    for trace in logistics["traces"]:
        lines.append(f"- {trace['time']}  {trace['desc']}")
    message = "\n".join(lines)
    return {"ok": True, "message": message, "data": logistics, "source": meta["source"], "degraded": meta["degraded"]}


def query_product(args: dict, session: Session) -> dict:
    keyword = (args.get("keyword") or "").strip()
    product_id = (args.get("product_id") or "").strip().upper()

    # 模型有时把完整商品名连商品 ID 一起塞进 keyword（如「AirSound Pro…（P1001）」），
    # 先抽出 ID，再去掉括号部分，避免关键词匹配失败。
    if not product_id:
        found = re.search(r"P\d{4}", keyword.upper())
        if found:
            product_id = found.group(0)
            keyword = re.sub(r"[（(]\s*P\d{4}\s*[)）]", "", keyword, flags=re.IGNORECASE).strip()

    products, meta = DATASOURCE.products(keyword or None, product_id or None)
    if not products:
        names = "、".join(p["name"] for p in mock_data.PRODUCTS.values())
        return {"ok": False, "message": f"没有找到相关商品。目前在售商品有：{names}。", "source": meta["source"]}

    lines = []
    data = []
    for p in products:
        stock_text = f"有货（库存 {p['stock']} 件）" if p["stock"] > 0 else "暂时缺货"
        specs = "；".join(f"{k}：{v}" for k, v in p["specs"].items())
        lines.append(
            f"【{p['name']}】{_fmt_money(p['price'])}\n"
            f"库存：{stock_text}\n规格：{specs}\n"
            f"优惠：{p['promo']}\n发货：{p['shipping']}\n售后：{p['warranty']}"
        )
        data.append(
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "price": p["price"],
                "stock": p["stock"],
                "specs": p["specs"],
                "promo": p["promo"],
                "shipping": p["shipping"],
            }
        )
    return {
        "ok": True,
        "message": "\n\n".join(lines),
        "data": data,
        "source": meta["source"],
        "degraded": meta["degraded"],
    }


def create_refund(args: dict, session: Session) -> dict:
    order_id = (args.get("order_id") or "").strip().upper() or (session.last_order_id or "")
    reason = (args.get("reason") or "").strip() or "用户未说明原因"
    refund_type = args.get("refund_type") or "退款"

    if not order_id:
        return {"ok": False, "message": "请先告诉我订单号，我再帮您提交退款申请。"}

    order = mock_data.ORDERS.get(order_id)
    if not order:
        return {"ok": False, "message": f"未找到订单 {order_id}，请核对订单号后再试。"}

    existing = next((r for r in mock_data.AFTER_SALES.values() if r["order_id"] == order_id), None)
    if existing:
        return {
            "ok": True,
            "message": (
                f"订单 {order_id} 已经有售后单了：{existing['after_sale_id']}，"
                f"当前进度「{existing['status']}」，无需重复提交。"
            ),
            "data": existing,
            "duplicated": True,
        }

    if refund_type not in ("退款", "退货退款"):
        refund_type = "退货退款" if order["status_code"] in ("delivered", "completed") else "退款"

    record = mock_data.new_after_sale(order_id, refund_type, reason)
    session.last_after_sale_id = record["after_sale_id"]
    message = (
        f"已为您提交{refund_type}申请，售后单号 {record['after_sale_id']}。\n"
        f"关联订单：{order_id}，退款金额 {_fmt_money(record['refund_amount'])}。\n"
        f"当前状态：{record['status']}，审核通过后款项将原路退回（1-3 个工作日到账）。\n"
        f"您可以随时问我「售后进度」来查询。"
    )
    return {"ok": True, "message": message, "data": record}


def query_after_sale(args: dict, session: Session) -> dict:
    order_id = (args.get("order_id") or "").strip().upper() or (session.last_order_id or "")
    after_sale_id = (args.get("after_sale_id") or "").strip().upper() or (session.last_after_sale_id or "")

    if not order_id and not after_sale_id:
        return {"ok": False, "message": "请告诉我订单号或售后单号，我帮您查询售后进度。"}

    records, meta = DATASOURCE.after_sales(order_id or None, after_sale_id or None)

    if not records:
        return {
            "ok": False,
            "message": f"订单 {order_id or after_sale_id} 目前没有售后记录。需要我帮您发起退款或退货吗？",
            "source": meta["source"],
        }

    lines = []
    for record in records:
        lines.append(
            f"售后单 {record['after_sale_id']}（订单 {record['order_id']}）\n"
            f"类型：{record['type']}｜金额：{_fmt_money(record['refund_amount'])}\n"
            f"当前进度：{record['status']}\n处理记录："
        )
        for step in record.get("timeline") or []:
            lines.append(f"- {step['time']}  {step['desc']}")
        session.last_after_sale_id = record["after_sale_id"]
    return {
        "ok": True,
        "message": "\n".join(lines),
        "data": records,
        "source": meta["source"],
        "degraded": meta["degraded"],
    }


def handoff_to_human(args: dict, session: Session) -> dict:
    reason = (args.get("reason") or "用户要求转人工").strip()
    summary = (args.get("summary") or "").strip() or None
    ticket = session.create_handoff(reason, summary)
    message = (
        f"已为您转接人工客服，工单号 {ticket['ticket_id']}。\n"
        f"转接原因：{ticket['reason']}\n"
        f"人工客服会带着下面的工单摘要继续为您服务，预计 1 分钟内接入：\n{ticket['summary']}"
    )
    return {"ok": True, "message": message, "data": ticket}


TOOL_HANDLERS = {
    "query_order": query_order,
    "query_logistics": query_logistics,
    "query_product": query_product,
    "create_refund": create_refund,
    "query_after_sale": query_after_sale,
    "handoff_to_human": handoff_to_human,
}


def execute_tool(name: str, args: dict[str, Any] | None, session: Session) -> dict:
    """统一执行入口：异常不外抛，返回结构化结果。"""
    started = time.perf_counter()
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"ok": False, "message": f"未知工具：{name}", "elapsed_ms": 0}
    try:
        result = handler(args or {}, session)
    except Exception as exc:  # 工具内部异常不能打断对话
        result = {"ok": False, "message": f"工具执行出错：{exc}"}
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result
