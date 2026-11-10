"""演示用的 mock 业务数据：商品、订单、物流、售后单。

数据全部在内存中，服务重启后 create_refund 产生的售后单会重置。
"""

from __future__ import annotations

import copy
from datetime import datetime

PRODUCTS: dict[str, dict] = {
    "P1001": {
        "product_id": "P1001",
        "name": "AirSound Pro 主动降噪蓝牙耳机",
        "price": 249.0,
        "stock": 128,
        "specs": {
            "颜色": "曜石黑 / 云雾白",
            "蓝牙": "5.3",
            "续航": "单次 38 小时（含充电仓）",
            "降噪": "最高 42dB 主动降噪",
            "防水": "IPX5",
        },
        "warranty": "整机保修 1 年，非人为损坏可换新",
        "promo": "满 200 减 20，到手价 229 元",
        "shipping": "现货，16:00 前下单当天发出",
    },
    "P1002": {
        "product_id": "P1002",
        "name": "轻氧便携榨汁杯 350ml",
        "price": 129.0,
        "stock": 0,
        "specs": {
            "容量": "350ml",
            "材质": "Tritan 杯体 + 304 不锈钢刀头",
            "充电": "USB-C，充满可用约 15 次",
        },
        "warranty": "整机保修 6 个月",
        "promo": "暂无活动",
        "shipping": "暂时缺货，预计 11 月 15 日补货",
    },
    "P1003": {
        "product_id": "P1003",
        "name": "PaceFit 智能运动手环",
        "price": 399.0,
        "stock": 56,
        "specs": {
            "屏幕": "1.47 英寸 AMOLED",
            "健康监测": "心率 / 血氧 / 睡眠 / 压力",
            "续航": "典型使用 14 天",
            "防水": "5ATM",
        },
        "warranty": "整机保修 1 年",
        "promo": "学生认证立减 30 元",
        "shipping": "现货，48 小时内发出",
    },
    "P1004": {
        "product_id": "P1004",
        "name": "恒温不锈钢保温杯 500ml",
        "price": 89.0,
        "stock": 342,
        "specs": {
            "容量": "500ml",
            "材质": "316 不锈钢内胆",
            "保温": "6 小时不低于 65°C",
        },
        "warranty": "非质量问题 7 天无理由退换",
        "promo": "第二件半价",
        "shipping": "现货，当天发出",
    },
}

ORDERS: dict[str, dict] = {
    "EC20241108001": {
        "order_id": "EC20241108001",
        "customer": "林晓",
        "phone_last4": "8821",
        "status": "已发货",
        "status_code": "shipped",
        "created_at": "2024-11-08 10:12",
        "paid_amount": 249.0,
        "payment": "微信支付",
        "items": [{"product_id": "P1001", "name": "AirSound Pro 主动降噪蓝牙耳机", "qty": 1, "price": 249.0}],
        "address": "上海市浦东新区张江路 88 号 3 号楼 502",
        "carrier": "顺丰速运",
        "tracking_no": "SF1234567890123",
        "eta": "2024-11-11",
    },
    "EC20241107002": {
        "order_id": "EC20241107002",
        "customer": "林晓",
        "phone_last4": "8821",
        "status": "已签收",
        "status_code": "delivered",
        "created_at": "2024-11-07 09:30",
        "paid_amount": 129.0,
        "payment": "支付宝",
        "items": [{"product_id": "P1002", "name": "轻氧便携榨汁杯 350ml", "qty": 1, "price": 129.0}],
        "address": "上海市浦东新区张江路 88 号 3 号楼 502",
        "carrier": "中通快递",
        "tracking_no": "ZT7788990011223",
        "eta": "2024-11-09",
    },
    "EC20241106003": {
        "order_id": "EC20241106003",
        "customer": "周楠",
        "phone_last4": "8835",
        "status": "待发货",
        "status_code": "pending",
        "created_at": "2024-11-06 21:05",
        "paid_amount": 399.0,
        "payment": "银行卡",
        "items": [{"product_id": "P1003", "name": "PaceFit 智能运动手环", "qty": 1, "price": 399.0}],
        "address": "杭州市西湖区文三路 199 号",
        "carrier": "",
        "tracking_no": "",
        "eta": "预计 11 月 10 日发出",
    },
    "EC20241105004": {
        "order_id": "EC20241105004",
        "customer": "陈一",
        "phone_last4": "8890",
        "status": "已完成",
        "status_code": "completed",
        "created_at": "2024-10-28 14:47",
        "paid_amount": 178.0,
        "payment": "微信支付",
        "items": [{"product_id": "P1004", "name": "恒温不锈钢保温杯 500ml", "qty": 2, "price": 89.0}],
        "address": "北京市朝阳区望京街 10 号",
        "carrier": "京东物流",
        "tracking_no": "JD0099887766554",
        "eta": "2024-10-31",
    },
}

LOGISTICS: dict[str, dict] = {
    "EC20241108001": {
        "order_id": "EC20241108001",
        "carrier": "顺丰速运",
        "tracking_no": "SF1234567890123",
        "current": "运输中：快件已到达【上海虹桥中转场】",
        "traces": [
            {"time": "2024-11-09 08:20", "desc": "快件已到达【上海虹桥中转场】"},
            {"time": "2024-11-08 22:10", "desc": "快件已从【深圳宝安集散点】发出"},
            {"time": "2024-11-08 18:32", "desc": "顺丰速运已收取快件"},
        ],
    },
    "EC20241107002": {
        "order_id": "EC20241107002",
        "carrier": "中通快递",
        "tracking_no": "ZT7788990011223",
        "current": "已签收：本人签收，感谢使用中通快递",
        "traces": [
            {"time": "2024-11-08 15:42", "desc": "快件已签收，签收人：本人"},
            {"time": "2024-11-08 09:10", "desc": "快件正在派送中，派送员：王师傅 138****6721"},
            {"time": "2024-11-07 20:05", "desc": "快件已到达【上海浦东张江网点】"},
            {"time": "2024-11-07 12:18", "desc": "中通快递已揽收"},
        ],
    },
    "EC20241105004": {
        "order_id": "EC20241105004",
        "carrier": "京东物流",
        "tracking_no": "JD0099887766554",
        "current": "已签收：商品已放入快递柜",
        "traces": [
            {"time": "2024-10-31 11:03", "desc": "已签收，商品已放入丰巢快递柜"},
            {"time": "2024-10-31 08:15", "desc": "派送中"},
            {"time": "2024-10-30 19:40", "desc": "已到达北京望京营业部"},
        ],
    },
}

# 预置一条售后单，方便演示「查询售后进度」
AFTER_SALES: dict[str, dict] = {
    "AS20241107001": {
        "after_sale_id": "AS20241107001",
        "order_id": "EC20241107002",
        "type": "退货退款",
        "reason": "商品噪音较大，想退货",
        "status": "商家已同意，等待上门取件",
        "created_at": "2024-11-08 16:20",
        "refund_amount": 129.0,
        "timeline": [
            {"time": "2024-11-08 16:20", "desc": "用户提交退货退款申请"},
            {"time": "2024-11-08 17:05", "desc": "商家审核通过，已预约 11 月 10 日上门取件"},
        ],
    }
}


_INITIAL_STATE = copy.deepcopy({"orders": ORDERS, "after_sales": AFTER_SALES})


def reset() -> None:
    """评测脚本每轮开始前重置演示数据，避免退款单/订单状态互相污染。"""
    ORDERS.clear()
    ORDERS.update(copy.deepcopy(_INITIAL_STATE["orders"]))
    AFTER_SALES.clear()
    AFTER_SALES.update(copy.deepcopy(_INITIAL_STATE["after_sales"]))


def find_order(order_id: str | None = None, phone_last4: str | None = None) -> list[dict]:
    """按订单号或手机号后四位查订单，返回列表（可能为空）。"""
    if order_id:
        oid = order_id.strip().upper()
        order = ORDERS.get(oid)
        return [copy.deepcopy(order)] if order else []
    if phone_last4:
        suffix = phone_last4.strip()
        return [copy.deepcopy(o) for o in ORDERS.values() if o["phone_last4"] == suffix]
    return []


def list_orders() -> list[dict]:
    return [copy.deepcopy(o) for o in ORDERS.values()]


def new_after_sale(order_id: str, refund_type: str, reason: str) -> dict:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    record = {
        "after_sale_id": f"AS{stamp}",
        "order_id": order_id,
        "type": refund_type,
        "reason": reason,
        "status": "待商家审核",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "refund_amount": ORDERS[order_id]["paid_amount"],
        "timeline": [
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "desc": "用户提交售后申请"},
            {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "desc": "系统已受理，预计 24 小时内完成审核"},
        ],
    }
    AFTER_SALES[record["after_sale_id"]] = record
    ORDERS[order_id]["status"] = "售后处理中"
    ORDERS[order_id]["status_code"] = "after_sale"
    return copy.deepcopy(record)
