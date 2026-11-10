# 转人工归因分析

- 生成时间：2026-11-09 17:54:33
- 测试集：134 条
- 转人工：35 条（26.1%）
- 其中：应转人工（预期）35 条；误转人工 0 条

## 一、归因分布

| 类别 | 数量 | 占转人工 | 占全量 |
|---|---|---|---|
| a) 意图识别错误 | 0 | 0.0% | 0.0% |
| b) 检索未召回 | 0 | 0.0% | 0.0% |
| c) 召回但置信度低于阈值 | 0 | 0.0% | 0.0% |
| d) 本就应当转人工（正确） | 35 | 100.0% | 26.1% |
| e) 硬规则误触发（边界/情绪/主题） | 0 | 0.0% | 0.0% |

## 二、类别明细

### a) 意图识别错误（0 条）

无。

### b) 检索未召回（0 条）

无。

### c) 召回但置信度低于阈值（0 条）

无。

### d) 本就应当转人工（正确）（35 条）

| 用例 | 原问题 | 实际分支 | 期望分支 | 实际规则 | 归因结论 |
|---|---|---|---|---|---|
| complaint-085 | 我要投诉！你们发错货了，必须赔偿我双倍！ | handoff（complaint） | complaint | refund_dispute | 测试集预期转人工，命中规则 refund_dispute |
| complaint-086 | 你们这是欺诈，我要举报 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| complaint-087 | 我要找你们领导 | handoff（complaint） | complaint | explicit_human | 测试集预期转人工，命中规则 explicit_human |
| complaint-088 | 太差了！！我要曝光你们 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| complaint-089 | 再不处理我就起诉你们 | handoff（complaint） | complaint | legal | 测试集预期转人工，命中规则 legal |
| complaint-090 | 我要退一赔三 | handoff（complaint） | complaint | refund_dispute | 测试集预期转人工，命中规则 refund_dispute |
| complaint-091 | 东西漏电把我手烫伤了 | handoff（complaint） | complaint | safety | 测试集预期转人工，命中规则 safety |
| complaint-092 | 我用了你们的榨汁杯过敏了，要赔偿 | handoff（complaint） | complaint | refund_dispute | 测试集预期转人工，命中规则 refund_dispute |
| complaint-093 | 垃圾客服，滚出来 | handoff（complaint） | complaint | emotion | 测试集预期转人工，命中规则 emotion |
| complaint-094 | 我要报警，你们骗钱 | handoff（complaint） | complaint | legal | 测试集预期转人工，命中规则 legal |
| complaint-095 | 你们这是违法的，我咨询过律师 | handoff（complaint） | complaint | intent_complaint | 测试集预期转人工，命中规则 intent_complaint |
| complaint-096 | 我要去消协投诉 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| complaint-097 | 发到网上让大家评评理 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| complaint-098 | 什么破店，气死我了 | handoff（complaint） | complaint | emotion | 测试集预期转人工，命中规则 emotion |
| complaint-099 | 我要转人工 | handoff（complaint） | complaint | explicit_human | 测试集预期转人工，命中规则 explicit_human |
| complaint-100 | 给我接人工客服 | handoff（complaint） | complaint | explicit_human | 测试集预期转人工，命中规则 explicit_human |
| complaint-101 | 这不赔偿说不过去，赔我误工费 | handoff（complaint） | complaint | refund_dispute | 测试集预期转人工，命中规则 refund_dispute |
| complaint-102 | 你们把我东西弄坏了，赔钱 | handoff（complaint） | complaint | refund_dispute | 测试集预期转人工，命中规则 refund_dispute |
| complaint-103 | 我要打315举报你们 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| complaint-104 | 差评！必须给我一个说法 | handoff（complaint） | complaint | complaint | 测试集预期转人工，命中规则 complaint |
| out_of_kb-105 | 你们支持比特币付款吗 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-106 | 你们老板是谁 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-107 | 公司股票代码是多少 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-108 | 你们有几家线下门店 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-109 | 可以加盟你们吗 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-110 | 你们招聘客服吗 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-111 | 你们和某某品牌是什么关系 | chitchat（chitchat） | chitchat、policy、presale、complaint | low_confidence | 测试集预期转人工，命中规则 low_confidence |
| out_of_kb-112 | 今天天气怎么样 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-115 | 你们公司成立多久了 | policy（policy） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-116 | 老板的邮箱是多少 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-117 | 有内部员工折扣吗 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-118 | 你们支持发票抽奖吗 | policy（policy） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-119 | 你们的退货率是多少 | policy（policy） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-120 | 竞品哪个好 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |
| out_of_kb-121 | 你们客服工资多少 | chitchat（chitchat） | chitchat、policy、presale、complaint | unsupported_topic | 测试集预期转人工，命中规则 unsupported_topic |

### e) 硬规则误触发（边界/情绪/主题）（0 条）

无。

## 三、典型样本

**d) 本就应当转人工（正确）**

- `我要投诉！你们发错货了，必须赔偿我双倍！`
  - 实际：分支 handoff，意图 complaint，规则 refund_dispute
  - 归因：测试集预期转人工，命中规则 refund_dispute
- `你们这是欺诈，我要举报`
  - 实际：分支 handoff，意图 complaint，规则 complaint
  - 归因：测试集预期转人工，命中规则 complaint
- `我要找你们领导`
  - 实际：分支 handoff，意图 complaint，规则 explicit_human
  - 归因：测试集预期转人工，命中规则 explicit_human

## 四、结论

- 误转人工 0 条 / 应自助 99 条 = **0.0%**（误转人工率）。
- 投诉类用例主分支命中 20/20，均由 complaint 意图直接进入 handoff 分支，不再依赖情绪/边界规则补救。
- 类别 a/b/c/e 为 0：本轮优化后没有发现意图跑偏、检索未召回或硬规则误触发导致的误转。
- 知识库外问题仍全部由硬规则转人工（含 unsupported_topic 与 low_confidence），过滤没有放松。
- **自测偏差提示**：测试集与规则同源开发，0 误转不能直接作为上线依据；上线前需用独立标注的线上真实会话做盲测。
