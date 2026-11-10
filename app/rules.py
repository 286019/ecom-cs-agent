"""加载 config/rules.json：能力边界、意图规则、兜底词表、检索阈值。

运营改规则只需要改 JSON，不需要改代码或提示词。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import BASE_DIR

RULES_PATH = BASE_DIR / "config" / "rules.json"


@lru_cache(maxsize=1)
def load_rules() -> dict:
    if not RULES_PATH.exists():
        raise FileNotFoundError(f"规则文件不存在：{RULES_PATH}")
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def reload_rules() -> dict:
    load_rules.cache_clear()
    return load_rules()


def contains_any(text: str, words: list[str]) -> list[str]:
    """返回命中的关键词列表（去重、按出现顺序）。"""
    hit: list[str] = []
    for word in words:
        if word and word in text and word not in hit:
            hit.append(word)
    return hit
