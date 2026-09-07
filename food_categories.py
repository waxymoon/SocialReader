# -*- coding: utf-8 -*-
"""食品分类轴判定：categories.json（面试官 2026-09-07 口径：正餐/下午茶多级 + 过滤全部饮品）。

- classify_text(text) -> dict: {"meal": "正餐"/"下午茶"/"", "sub": "日料"/..., "excluded_drink": bool, "drink_kind": "奶茶茶饮"/"咖啡"/...}
- 判定顺序：饮品桶优先（命中即 excluded）→ 二级类 queries（采集关键词）→ 二级类 terms（食品实体词）取命中数最多者。
- 纯标准库 + 读 domains/food_v1/categories.json；供导出知识库/页面打标复用。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DOMAIN_ROOT = Path(__file__).resolve().parent / "domains" / "food_v1"
CATEGORIES_PATH = DOMAIN_ROOT / "categories.json"

_loaded: dict[str, Any] | None = None


def load_categories(path: Path | str | None = None) -> dict[str, Any]:
    global _loaded
    p = Path(path) if path else CATEGORIES_PATH
    with open(p, encoding="utf-8") as handle:
        return json.load(handle)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _hit_count(texts: list[str], words: list[str]) -> int:
    """words 在 texts 中出现次数（去重词计数，防重复词刷高）。"""
    joined = " ".join(_norm(t) for t in texts)
    seen: set[str] = set()
    total = 0
    for word in words:
        w = _norm(word)
        if w and w not in seen and w in joined:
            seen.add(w)
            total += 1
    return total


def classify_text(*texts: str, categories: dict[str, Any] | None = None) -> dict[str, Any]:
    """对一组文本（关键词+标题+正文…）做分类判定。"""
    cfg = categories or load_categories()
    meal_axis = cfg.get("meals", {})
    drinks_axis = cfg.get("excluded_drinks", {})

    # 1) 饮品桶优先
    best_drink = None
    best_drink_hits = 0
    for kind, rule in drinks_axis.items():
        hits = _hit_count(list(texts), rule.get("queries", [])) + _hit_count(list(texts), rule.get("terms", []))
        if hits > best_drink_hits:
            best_drink_hits, best_drink = hits, kind

    # 2) 二级类 queries/terms 命中计数
    best_meal = best_sub = ""
    best_meal_hits = 0
    best_sub_hits = 0
    for meal, subs in meal_axis.items():
        for sub, rule in subs.items():
            hits = _hit_count(list(texts), rule.get("queries", [])) * 3 + _hit_count(list(texts), rule.get("terms", []))
            if hits > best_meal_hits or (hits == best_meal_hits and hits > 0 and meal == "正餐" and best_meal != "正餐"):
                best_meal_hits, best_sub_hits = hits, hits
                best_meal, best_sub = meal, sub

    return {
        "meal": best_meal if best_meal_hits else "",
        "sub": best_sub if best_meal_hits else "",
        "excluded_drink": best_drink is not None,
        "drink_kind": best_drink or "",
    }


def keyword_to_category(keyword: str) -> dict[str, Any]:
    """关键词（话题）直接映射；命中饮品返回 excluded_drink=True。"""
    cfg = load_categories()
    k = _norm(keyword)
    for kind, rule in cfg.get("excluded_drinks", {}).items():
        if any(_norm(q) == k or _norm(q) in k or k in _norm(q) for q in rule.get("queries", [])):
            return {"meal": "", "sub": "", "excluded_drink": True, "drink_kind": kind}
    for meal, subs in cfg.get("meals", {}).items():
        for sub, rule in subs.items():
            if any(_norm(q) == k or _norm(q) in k or k in _norm(q) for q in rule.get("queries", [])):
                return {"meal": meal, "sub": sub, "excluded_drink": False, "drink_kind": ""}
    return {"meal": "", "sub": "", "excluded_drink": False, "drink_kind": ""}


def is_drink(*texts: str, categories: dict[str, Any] | None = None) -> bool:
    return classify_text(*texts, categories=categories)["excluded_drink"]


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    samples = [
        "三文鱼波奇饭",
        "三文鱼波奇饭 减脂期也能吃的满足感晚餐 1比1复刻 三文鱼切得超大块超厚实 铺满一碗还冒尖",
        "奶茶新品",
        "2026 奶茶新品 黑糖波霸 芋圆 生椰拿铁",
        "螺蛳粉加炸蛋 又臭又香",
        "韩式炸鸡 芝士部队锅 双人套餐",
        "随便搜的随机词",
    ]
    for s in samples:
        print(repr(s[:40]), "→", classify_text(s))
