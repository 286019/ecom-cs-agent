"""极简 JSONPath：只支持真实接口适配需要的几种写法。

支持：
    $.data.orders[*]      数组展开
    $.data.order.status   逐级取值
    $.items[0].name       下标
不引入第三方依赖，避免为一个字段抽取装一个库。
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+|\*)\]")


def _tokens(path: str) -> list[str | int]:
    path = (path or "").strip()
    if path.startswith("$"):
        path = path[1:]
    tokens: list[str | int] = []
    for name, index in _TOKEN_RE.findall(path):
        if name:
            if name != "*":
                tokens.append(name)
            else:
                tokens.append("*")
        elif index == "*":
            tokens.append("*")
        elif index:
            tokens.append(int(index))
    return tokens


def extract_all(obj, path: str) -> list:
    current = [obj]
    for token in _tokens(path):
        nxt = []
        for item in current:
            if token == "*":
                if isinstance(item, list):
                    nxt.extend(item)
                elif isinstance(item, dict):
                    nxt.extend(item.values())
            elif isinstance(token, int):
                if isinstance(item, list) and -len(item) <= token < len(item):
                    nxt.append(item[token])
            elif isinstance(item, dict) and token in item:
                nxt.append(item[token])
        current = nxt
    return current


def extract_one(obj, path: str, default=None):
    values = extract_all(obj, path)
    return values[0] if values else default
