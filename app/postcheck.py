"""确定性后校验：工具已经返回的字段，不允许被回答成「未标注」。

只做一件事：当回答出现「未标注」类拒答、而本次工具返回的 specs 里
确实包含用户所问的字段时，把真实值补进回答。
工具没返回的字段不做任何补写，保持「未标注」。
"""

from __future__ import annotations

from typing import Iterable

# 用户问法中的关键词 → 商品 specs 里的字段名（任一命中即可）
SPEC_ALIASES: dict[str, tuple[str, ...]] = {
    "降噪": ("降噪", "主动降噪"),
    "颜色": ("颜色", "配色"),
    "重量": ("重量",),
    "材质": ("材质", "材料"),
    "续航": ("续航", "电池"),
    "防水": ("防水", "防水等级"),
    "蓝牙": ("蓝牙", "蓝牙版本"),
    "尺寸": ("尺寸", "直径"),
    "容量": ("容量",),
    "适配": ("适配", "兼容"),
    "机洗": ("机洗", "洗涤"),
    "碳酸": ("碳酸",),
    "表带": ("表带",),
}

REFUSAL_MARKERS = ("未标注", "建议联系人工确认", "知识库里没有", "暂时没有这方面的规定")


def _collect_specs(tool_results: Iterable[dict]) -> dict[str, str]:
    """合并本次对话中 query_product 返回的 specs。"""
    merged: dict[str, str] = {}
    for item in tool_results:
        if item.get("name") != "query_product":
            continue
        result = item.get("result") or {}
        if not result.get("ok"):
            continue
        for product in result.get("data") or []:
            for key, value in (product.get("specs") or {}).items():
                merged.setdefault(str(key), str(value))
    return merged


def _asked_fields(question: str, specs: dict[str, str]) -> dict[str, str]:
    """找出用户问到、且 specs 里确实存在的字段。"""
    hits: dict[str, str] = {}
    lowered = question.lower()
    for keyword, aliases in SPEC_ALIASES.items():
        if keyword not in lowered:
            continue
        for spec_key, spec_value in specs.items():
            if any(alias in spec_key or spec_key in alias for alias in aliases):
                hits[spec_key] = spec_value
                break
    return hits


class RefusalGuard:
    """流式输出时保证「该信息未标注」独立成句。

    模型常把引导词和拒答句粘在一起（如「手环颜色有该信息未标注」），
    这里只扣留标记词前后的少量字符，发现粘连就把悬空词换成冒号或补句号。
    """

    MARKERS = ("该信息未标注", "信息未标注")
    GLUE = ("支持", "有", "是", "为")
    PUNCT = "。！？；\n，："

    def __init__(self) -> None:
        self.pending = ""
        self.tail = ""

    @classmethod
    def _clean_prefix(cls, prefix: str) -> str:
        if not prefix or prefix[-1] in cls.PUNCT:
            return prefix
        for glue in cls.GLUE:
            if prefix.endswith(glue):
                base = prefix[: -len(glue)].rstrip()
                return f"{base}：" if base else "。"
        return f"{prefix}。"

    def _next_marker(self) -> tuple[int, str] | None:
        best: tuple[int, str] | None = None
        for marker in self.MARKERS:
            index = self.pending.find(marker)
            if index < 0:
                continue
            if best is None or index < best[0] or (index == best[0] and len(marker) > len(best[1])):
                best = (index, marker)
        return best

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        out = ""
        while True:
            found = self._next_marker()
            if found:
                index, marker = found
                prefix = self.pending[:index]
                cleaned = self._clean_prefix(prefix)
                if not cleaned and not prefix:
                    last = out[-1] if out else self.tail
                    if last and last not in self.PUNCT:
                        cleaned = "。"
                out += cleaned + marker
                self.pending = self.pending[index + len(marker):]
                continue
            hold = 0
            for marker in self.MARKERS:
                for size in range(min(len(marker) - 1, len(self.pending)), 0, -1):
                    if self.pending.endswith(marker[:size]):
                        hold = max(hold, size)
                        break
            if not hold:
                for glue in self.GLUE:
                    if self.pending.endswith(glue):
                        hold = len(glue)
                        break
            if hold:
                out += self.pending[:-hold]
                self.pending = self.pending[-hold:]
            else:
                out += self.pending
                self.pending = ""
            if out:
                self.tail = out[-1]
            return out

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        if out:
            self.tail = out[-1]
        return out


def correct_missing_orders(answer: str, tool_results: Iterable[dict]) -> str:
    """多订单查询时，如果回答没列出订单号，补上可定位的信息。"""
    orders: list[dict] = []
    for item in tool_results:
        if item.get("name") != "query_order":
            continue
        result = item.get("result") or {}
        if not result.get("ok"):
            continue
        orders.extend(result.get("data") or [])
    if len(orders) < 2:
        return ""
    ids = [str(order.get("order_id", "")) for order in orders]
    if all(order_id and order_id in answer for order_id in ids):
        return ""
    lines = []
    for order in orders:
        products = "、".join(order.get("products") or [])
        lines.append(f"{order.get('order_id')}（{products}，{order.get('status')}）")
    return "具体订单：" + "；".join(lines) + "。"


def correct_unstated_fields(question: str, answer: str, tool_results: Iterable[dict]) -> str:
    """返回需要追加的更正文本；无需更正时返回空串。"""
    if not any(marker in answer for marker in REFUSAL_MARKERS):
        return ""
    specs = _collect_specs(tool_results)
    if not specs:
        return ""
    hits = _asked_fields(question, specs)
    if not hits:
        return ""
    facts = "；".join(f"{key}：{value}" for key, value in hits.items())
    return f"更正：商品规格里已标注，{facts}（来源：query_product）。上面的「未标注」不适用。"
