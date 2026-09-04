# -*- coding: utf-8 -*-
"""低频保存平台当前可见候选池；先落 raw JSONL，再调用 food_v1 离线评分。"""
from __future__ import annotations

import argparse
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from domain_pipeline import run_candidate_pool
from food_metrics import derive_content_id, write_jsonl
from pipeline_capture import (
    DY_LIKE_SELECTORS,
    card_link,
    child_count,
    login_gate,
    public_source_url,
)
from read_social import cmd_search_dy, cmd_search_xhs, connect


DATE_PATTERN = re.compile(r"^(?:\d{4}-)?\d{1,2}-\d{1,2}$")


def _card_lines(card: Any) -> list[str]:
    try:
        return [line.strip() for line in str(card.text or "").splitlines() if line.strip()]
    except Exception:
        return []


def _author_and_date(lines: list[str], title: str) -> tuple[str, str | None]:
    filtered = [line for line in lines if line != title]
    for index, line in enumerate(filtered):
        if DATE_PATTERN.fullmatch(line):
            published = f"{datetime.now().year}-{line}" if line.count("-") == 1 else line
            return (filtered[index - 1] if index else ""), published
    return "", None


def visible_candidates(page: Any, platform: str, query: str, run_id: str) -> list[dict[str, Any]]:
    if platform == "xhs":
        cmd_search_xhs(page, query)
        selector, patterns, base, like_selectors = ".note-item", ("/search_result/", "/explore/", "/discovery/"), "https://www.xiaohongshu.com", (".count", ".like-wrapper")
    else:
        cmd_search_dy(page, query)
        selector, patterns, base, like_selectors = ".search-result-card", ("/video/",), "https://www.douyin.com", DY_LIKE_SELECTORS
    cards = page.eles(selector, timeout=8)
    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for position, card in enumerate(cards, 1):
        linked = card_link(card, patterns)
        if not linked:
            continue
        title, href = linked
        url = public_source_url(href if href.startswith("http") else base + href)
        lines = _card_lines(card)
        author, published_at = _author_and_date(lines, title)
        content_id = derive_content_id(platform, url, title)
        rows.append({
            "platform": platform,
            "query": query,
            "run_id": run_id,
            "run_at": run_at,
            "rank_on_page": position,
            "content_id": content_id,
            "title": title,
            "author": author,
            "published_at": published_at,
            "likes": child_count(card, like_selectors),
            "favorites": None,
            "comments": None,
            "shares": None,
            "source_url": url,
            "metric_missing_fields": ["favorites", "comments", "shares"],
            "food_description_density": 0.0,
            "relevance_pass": bool(query and query in (title + " ".join(lines))),
            "source_kind": "real_visible_candidate_pool",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="保存当前可见社媒候选池")
    parser.add_argument("platform", choices=("xhs", "dy"))
    parser.add_argument("query")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    page = connect()
    login_gate(page, args.platform)
    run_id = f"real_pool_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    rows = visible_candidates(page, args.platform, args.query, run_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / "real_candidate_pool_input.jsonl"
    write_jsonl(raw_path, rows)
    result = run_candidate_pool(raw_path, args.output_dir)
    print(f"[candidate_pool] 可见候选 {len(rows)} 条，已先保存 {raw_path}")
    print(f"[candidate_pool] 进入详情候选 {len(result['selected'])} 条，基线状态 {result['baseline']['status']}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
