"""生成评测测试集 eval/testset.jsonl（134 条，覆盖 6 类）。

运行：python scripts/build_testset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# (问题, 可接受的意图, 是否应转人工, 回答中应出现的关键词之一)
PRESALE = [
    ("耳机的续航是多少", ["presale"], False, ["P1001", "AirSound", "小时"]),
    ("AirSound Pro 多少钱", ["presale"], False, ["P1001", "249"]),
    ("降噪耳机有现货吗", ["presale"], False, ["P1001", "库存", "现货"]),
    ("耳机支持什么降噪模式", ["presale"], False, ["P1001", "降噪"]),
    ("耳机重量多少", ["presale"], False, ["未标注", "人工"]),
    ("榨汁杯多少钱", ["presale"], False, ["P1002", "129"]),
    ("榨汁杯容量多大", ["presale"], False, ["P1002", "350", "ml"]),
    ("榨汁杯能榨冰块吗", ["presale"], False, ["未标注", "人工"]),
    ("榨汁杯有货吗", ["presale"], False, ["P1002", "缺货", "库存"]),
    ("手环多少钱", ["presale"], False, ["P1003", "399"]),
    ("手环续航几天", ["presale"], False, ["P1003", "天"]),
    ("手环支持防水吗", ["presale"], False, ["P1003", "防水", "5ATM"]),
    ("手环能测血氧吗", ["presale"], False, ["P1003", "血氧"]),
    ("保温杯多少钱", ["presale"], False, ["P1004", "89"]),
    ("保温杯容量多少", ["presale"], False, ["P1004", "500", "ml"]),
    ("保温杯保温多久", ["presale"], False, ["P1004", "小时", "保温"]),
    ("保温杯材质是什么", ["presale"], False, ["P1004", "316", "不锈钢"]),
    ("杯子是什么材质的", ["presale"], False, ["P1004", "316", "不锈钢"]),
    ("耳机有优惠吗", ["presale"], False, ["P1001", "优惠", "券"]),
    ("榨汁杯有优惠吗", ["presale"], False, ["P1002", "暂无", "活动"]),
    ("手环有什么颜色", ["presale"], False, ["未标注", "人工"]),
    ("保温杯有哪些颜色", ["presale"], False, ["未标注", "人工"]),
    ("耳机保修多久", ["policy", "presale"], False, ["保修", "年"]),
    ("手环保修多久", ["policy", "presale"], False, ["保修", "年"]),
    ("榨汁杯可以机洗吗", ["presale"], False, ["未标注", "人工"]),
    ("耳机支持苹果手机吗", ["presale"], False, ["未标注", "人工"]),
    ("手环能连安卓吗", ["presale"], False, ["未标注", "人工"]),
    ("保温杯能装碳酸饮料吗", ["presale"], False, ["未标注", "人工"]),
    ("耳机多少钱", ["presale"], False, ["P1001", "249"]),
    ("手环的表带能换吗", ["presale"], False, ["未标注", "人工"]),
]

LOGISTICS = [
    ("帮我查一下订单 EC20241108001", ["order_logistics"], False, ["EC20241108001", "已发货"]),
    ("EC20241108001 到哪了", ["order_logistics"], False, ["EC20241108001", "物流", "已发货"]),
    ("帮我看看 EC20241108001 的物流", ["order_logistics"], False, ["EC20241108001", "顺丰"]),
    ("手机尾号 8821 的订单", ["order_logistics"], False, ["EC202411", "订单"]),
    ("尾号8835的订单发货了吗", ["order_logistics"], False, ["EC20241106003", "待发货"]),
    ("订单 EC20241106003 什么时候发货", ["order_logistics"], False, ["EC20241106003", "发货"]),
    ("订单 EC20241107002 签收了吗", ["order_logistics"], False, ["EC20241107002", "已签收"]),
    ("我的订单到哪了", ["order_logistics"], False, ["订单号", "手机号"]),
    ("EC20241105004 的状态", ["order_logistics"], False, ["EC20241105004", "已完成"]),
    ("帮我查订单 EC20241107002", ["order_logistics"], False, ["EC20241107002", "已签收"]),
    ("快递到哪了 EC20241108001", ["order_logistics"], False, ["EC20241108001", "运输", "顺丰"]),
    ("运单号是多少 EC20241108001", ["order_logistics"], False, ["SF1234567890123", "顺丰"]),
    ("我买的东西发货了吗 EC20241106003", ["order_logistics"], False, ["EC20241106003", "待发货"]),
    ("订单 EC20241106003 预计什么时候到", ["order_logistics"], False, ["EC20241106003", "预计"]),
    ("订单 EC20241108001 买的什么", ["order_logistics"], False, ["AirSound", "耳机"]),
    ("订单 EC20241108001 实付多少", ["order_logistics"], False, ["249"]),
    ("订单 EC20241105004 买了什么", ["order_logistics"], False, ["保温杯"]),
    ("订单 EC20241107002 的物流", ["order_logistics"], False, ["EC20241107002", "中通"]),
    ("快递单号 EC20241107002", ["order_logistics"], False, ["ZT7788990011223"]),
    ("我手机尾号8890的订单", ["order_logistics"], False, ["EC20241105004"]),
    ("尾号 8821 有两个订单吗", ["order_logistics"], False, ["EC20241108001", "EC20241107002"]),
    ("订单 EC20241108001 到货了吗", ["order_logistics"], False, ["已发货", "运输", "预计"]),
    ("帮我查快递 EC20241108001", ["order_logistics"], False, ["顺丰", "SF1234567890123"]),
    ("订单 EC20241107002 什么时候到的", ["order_logistics"], False, ["2024-11-09", "签收"]),
    ("EC20241108001 是顺丰吗", ["order_logistics"], False, ["顺丰"]),
    ("订单 EC20241106003 状态", ["order_logistics"], False, ["待发货"]),
    ("查一下 EC20241105004", ["order_logistics"], False, ["EC20241105004", "已完成"]),
    ("我的快递怎么还没动 EC20241106003", ["order_logistics"], False, ["待发货", "还没发货"]),
]

AFTER_SALE = [
    ("你们支持七天无理由退货吗？退货运费谁承担？", ["policy"], False, ["7 天", "运费"]),
    ("退货运费谁承担", ["policy"], False, ["运费", "买家", "商家"]),
    ("退款多久到账", ["policy"], False, ["到账", "工作日"]),
    ("七天无理由的条件是什么", ["policy"], False, ["7 天", "条件", "未使用"]),
    ("拆封的耳机还能退吗", ["policy"], False, ["无理由", "退货", "7 天"]),
    ("质量问题退货运费谁出", ["policy"], False, ["质量问题", "商家"]),
    ("发票怎么开", ["policy"], False, ["发票", "开"]),
    ("可以开专票吗", ["policy"], False, ["专票", "增值税"]),
    ("保修期多久", ["policy"], False, ["保修", "年"]),
    ("退款流程是怎样的", ["policy"], False, ["退款", "审核", "流程"]),
    ("怎么申请退货", ["policy", "after_sale"], False, ["退货", "申请", "订单"]),
    ("我想退货怎么办", ["policy", "after_sale"], False, ["退货", "申请", "订单"]),
    ("订单 EC20241105004 我要申请退货退款，杯盖有划痕", ["after_sale"], False, ["售后单", "退货退款"]),
    ("订单 EC20241107002 我要退货", ["after_sale"], False, ["售后单", "退货"]),
    ("订单 EC20241108001 我想退款", ["after_sale"], False, ["售后单", "退款"]),
    ("帮我申请退款，订单 EC20241106003", ["after_sale"], False, ["售后单", "退款"]),
    ("订单 EC20241106003 我买错了，帮我退掉", ["after_sale"], False, ["售后单", "退款"]),
    ("售后进度怎么查", ["policy", "after_sale"], False, ["售后", "订单"]),
    ("订单 EC20241107002 的售后进度", ["after_sale"], False, ["AS20241107001", "进度"]),
    ("退款到账了吗", ["after_sale", "policy"], False, ["到账", "退款", "订单"]),
    ("优惠券退款后会退回吗", ["policy"], False, ["优惠券", "退回"]),
    ("价格保护怎么申请", ["policy"], False, ["价格保护", "降价"]),
    ("发票能补开吗", ["policy"], False, ["发票", "开具", "可以"]),
    ("退款需要几天", ["policy"], False, ["天", "到账"]),
    ("换货怎么操作", ["policy", "after_sale"], False, ["换货", "申请"]),
    ("退货要保留包装吗", ["policy"], False, ["包装", "完整"]),
]

COMPLAINT = [
    ("我要投诉！你们发错货了，必须赔偿我双倍！", ["complaint"], True, []),
    ("你们这是欺诈，我要举报", ["complaint"], True, []),
    ("我要找你们领导", ["complaint"], True, []),
    ("太差了！！我要曝光你们", ["complaint"], True, []),
    ("再不处理我就起诉你们", ["complaint"], True, []),
    ("我要退一赔三", ["complaint"], True, []),
    ("东西漏电把我手烫伤了", ["complaint"], True, []),
    ("我用了你们的榨汁杯过敏了，要赔偿", ["complaint"], True, []),
    ("垃圾客服，滚出来", ["complaint"], True, []),
    ("我要报警，你们骗钱", ["complaint"], True, []),
    ("你们这是违法的，我咨询过律师", ["complaint"], True, []),
    ("我要去消协投诉", ["complaint"], True, []),
    ("发到网上让大家评评理", ["complaint"], True, []),
    ("什么破店，气死我了", ["complaint"], True, []),
    ("我要转人工", ["complaint"], True, []),
    ("给我接人工客服", ["complaint"], True, []),
    ("这不赔偿说不过去，赔我误工费", ["complaint"], True, []),
    ("你们把我东西弄坏了，赔钱", ["complaint"], True, []),
    ("我要打315举报你们", ["complaint"], True, []),
    ("差评！必须给我一个说法", ["complaint"], True, []),
]

OUT_OF_KB = [
    ("你们支持比特币付款吗", True),
    ("你们老板是谁", True),
    ("公司股票代码是多少", True),
    ("你们有几家线下门店", True),
    ("可以加盟你们吗", True),
    ("你们招聘客服吗", True),
    ("你们和某某品牌是什么关系", True),
    ("今天天气怎么样", True),
    ("帮我写一首诗", True),
    ("1加1等于几", True),
    ("你们公司成立多久了", True),
    ("老板的邮箱是多少", True),
    ("有内部员工折扣吗", True),
    ("你们支持发票抽奖吗", True),
    ("你们的退货率是多少", True),
    ("竞品哪个好", True),
    ("你们客服工资多少", True),
]

# 扩库后应自助的高频咨询（支付/会员/赠品/配送），不再消耗人工
SUPPORTED_POLICY = [
    ("你们支持货到付款吗", ["policy", "chitchat"], ["货到付款", "99"]),
    ("有赠品吗", ["policy", "presale", "chitchat"], ["赠品", "199"]),
    ("会员积分怎么用", ["policy", "chitchat"], ["积分", "抵扣"]),
    ("可以用花呗分期吗", ["policy"], ["花呗", "分期"]),
    ("支持以旧换新吗", ["policy", "chitchat"], ["以旧换新", "抵扣"]),
    ("有线下自提点吗", ["policy", "chitchat"], ["自提", "门店"]),
    ("能寄到海外吗", ["policy", "chitchat"], ["海外", "跨境"]),
    ("你们支持数字人民币吗", ["policy"], ["数字人民币", "试点"]),
    ("有跨境直邮吗", ["policy", "chitchat"], ["跨境", "直邮"]),
]

MULTI_TURN = [
    {
        "question": "帮我查一下订单 EC20241108001",
        "followup": ["那这个订单的物流到哪了"],
        "note": "多轮记忆：订单号继承",
    },
    {
        "question": "你们支持七天无理由退货吗？退货运费谁承担？",
        "followup": ["那质量问题退货运费谁出"],
        "note": "多轮：同一政策追问",
    },
    {
        "question": "订单 EC20241105004 我要申请退货退款，杯盖有划痕",
        "followup": ["那我这个退款什么时候到账"],
        "note": "多轮记忆：售后单继承",
    },
    {
        "question": "耳机多少钱",
        "followup": ["有优惠吗"],
        "note": "多轮：商品追问",
    },
]


def build() -> list[dict]:
    rows: list[dict] = []
    counter = 0

    def add(category: str, question: str, intents: list[str], handoff: bool, keywords: list[str]) -> None:
        nonlocal counter
        counter += 1
        rows.append(
            {
                "id": f"{category}-{counter:03d}",
                "category": category,
                "question": question,
                "expect_intents": intents,
                "expect_handoff": handoff,
                "expect_any": keywords,
            }
        )

    for q, intents, handoff, kw in PRESALE:
        add("presale", q, intents, handoff, kw)
    for q, intents, handoff, kw in LOGISTICS:
        add("logistics", q, intents, handoff, kw)
    for q, intents, handoff, kw in AFTER_SALE:
        add("aftersale", q, intents, handoff, kw)
    for q, intents, handoff, kw in COMPLAINT:
        add("complaint", q, intents, handoff, kw)
    for q, handoff in OUT_OF_KB:
        # 纯闲聊任务（写诗、算术）允许明确拒绝而不转人工，其余知识库外问题必须转人工
        smalltalk = q in {"帮我写一首诗", "1加1等于几"}
        add(
            "out_of_kb",
            q,
            ["chitchat", "policy", "presale", "complaint"],
            handoff and not smalltalk,
            ["不在我的服务范围"] if smalltalk else [],
        )

    for q, intents, keywords in SUPPORTED_POLICY:
        add("policy", q, intents, False, keywords)

    for item in MULTI_TURN:
        counter += 1
        rows.append(
            {
                "id": f"multi-{counter:03d}",
                "category": "multi_turn",
                "question": item["question"],
                "followup": item["followup"],
                "expect_intents": ["order_logistics", "policy", "after_sale", "presale"],
                "expect_handoff": False,
                "expect_any": [],
                "note": item["note"],
            }
        )
    return rows


def main() -> None:
    rows = build()
    out = BASE / "eval" / "testset.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats: dict[str, int] = {}
    for row in rows:
        stats[row["category"]] = stats.get(row["category"], 0) + 1
    print(f"写入 {len(rows)} 条到 {out}")
    print("分类统计：", stats)


if __name__ == "__main__":
    main()
