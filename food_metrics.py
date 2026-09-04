# -*- coding: utf-8 -*-
"""food_v1 候选池去重、分位排序、分层抽样和离线评测。"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


INTERACTION_FIELDS = ("likes", "favorites", "comments", "shares")
DROP_QUERY_KEYS = {"share_token", "sec_uid", "timestamp"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} 不是 JSON 对象")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_source_url(value: Any) -> str:
    """保留内容定位所需参数；仅去掉与定位无关的分享/用户/时间参数。"""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in DROP_QUERY_KEYS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def derive_content_id(platform: str, source_url: str, fallback: str = "") -> str:
    patterns = (r"/(?:search_result|explore|discovery)/([0-9a-fA-F]+)", r"/video/(\d+)")
    for pattern in patterns:
        match = re.search(pattern, source_url)
        if match:
            return f"{platform}_{match.group(1)}"
    seed = f"{platform}|{normalize_source_url(source_url)}|{fallback}".encode("utf-8")
    return f"{platform}_{hashlib.sha256(seed).hexdigest()[:16]}"


def normalize_text(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for parser in (
        lambda: datetime.fromisoformat(text),
        lambda: datetime.strptime(text[:10], "%Y-%m-%d"),
        lambda: datetime.strptime(text[:8], "%Y%m%d"),
    ):
        try:
            parsed = parser()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError):
            continue
    return None


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """返回 0..1 的稳定百分位；并列值使用平均秩。"""
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    output: list[float | None] = [None] * len(values)
    if not present:
        return output
    ordered = sorted(present, key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    cursor = 0
    while cursor < len(ordered):
        end = cursor
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[cursor][1]:
            end += 1
        rank = ((cursor + end) / 2) / denominator if len(ordered) > 1 else 1.0
        for position in range(cursor, end + 1):
            output[ordered[position][0]] = round(rank, 6)
        cursor = end + 1
    return output


def mark_duplicates(rows: list[dict[str, Any]], similarity_threshold: float = 0.9) -> list[dict[str, Any]]:
    """只自动折叠精确重复；高相似文本保留并标记人工确认。"""
    seen_ids: dict[tuple[str, str], str] = {}
    seen_urls: dict[tuple[str, str], str] = {}
    seen_text: dict[tuple[str, str], str] = {}
    canonical_texts: list[tuple[str, str, str]] = []
    output: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        platform = str(row.get("platform") or "")
        content_id = str(row.get("content_id") or "")
        source_url = normalize_source_url(row.get("source_url"))
        row["source_url"] = source_url
        text_key = normalize_text(f"{row.get('title', '')}\n{row.get('body', '')}")
        duplicate_of = ""
        if content_id and (platform, content_id) in seen_ids:
            duplicate_of = seen_ids[(platform, content_id)]
        elif source_url and (platform, source_url) in seen_urls:
            duplicate_of = seen_urls[(platform, source_url)]
        elif text_key and (platform, text_key) in seen_text:
            duplicate_of = seen_text[(platform, text_key)]
        row["duplicate_of"] = duplicate_of or None
        row["possible_duplicate"] = False
        row["possible_duplicate_of"] = None
        if not duplicate_of and text_key:
            for prior_platform, prior_id, prior_text in canonical_texts:
                if prior_platform != platform or min(len(text_key), len(prior_text)) < 12:
                    continue
                if SequenceMatcher(None, text_key, prior_text).ratio() >= similarity_threshold:
                    row["possible_duplicate"] = True
                    row["possible_duplicate_of"] = prior_id
                    break
        key_id = content_id or derive_content_id(platform, source_url, text_key)
        row["content_id"] = key_id
        if not duplicate_of:
            seen_ids[(platform, key_id)] = key_id
            if source_url:
                seen_urls[(platform, source_url)] = key_id
            if text_key:
                seen_text[(platform, text_key)] = key_id
                canonical_texts.append((platform, key_id, text_key))
        output.append(row)
    return output


def score_candidate_pool(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """在 platform + query + run_id 内独立计算互动与新近分位。"""
    marked = mark_duplicates(rows)
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(marked):
        groups[(str(row.get("platform", "")), str(row.get("query", "")), str(row.get("run_id", "")))].append(index)
    now = datetime.now(timezone.utc)
    engagement_weight = float(config.get("rising_weights", {}).get("engagement", 0.7))
    recency_weight = float(config.get("rising_weights", {}).get("recency", 0.3))
    min_pool = int(config.get("minimum_hot_pool_size", 10))
    min_coverage = float(config.get("minimum_metric_coverage", 0.5))
    hot_threshold = float(config.get("relative_hot_percentile", 0.8))
    for indices in groups.values():
        pool_size = sum(1 for index in indices if not marked[index].get("duplicate_of"))
        per_field = {
            field: percentile_ranks([_number(marked[index].get(field)) for index in indices])
            for field in INTERACTION_FIELDS
        }
        ages: list[float | None] = []
        for index in indices:
            published = _parse_datetime(marked[index].get("published_at"))
            ages.append(max(0.0, (now - published.astimezone(timezone.utc)).total_seconds()) if published else None)
        recency_percentiles = percentile_ranks([-value if value is not None else None for value in ages])
        for local_index, global_index in enumerate(indices):
            row = marked[global_index]
            metric_percentiles = {
                field: per_field[field][local_index]
                for field in INTERACTION_FIELDS
                if per_field[field][local_index] is not None
            }
            missing = [field for field in INTERACTION_FIELDS if _number(row.get(field)) is None]
            coverage = len(metric_percentiles) / len(INTERACTION_FIELDS)
            engagement = statistics.fmean(metric_percentiles.values()) if metric_percentiles else None
            recency = recency_percentiles[local_index]
            rising = None if engagement is None or recency is None else engagement_weight * engagement + recency_weight * recency
            row.update({
                "pool_size": pool_size,
                "metric_missing_fields": missing,
                "metric_coverage": round(coverage, 4),
                "metric_percentiles": metric_percentiles,
                "engagement_percentile": round(engagement, 6) if engagement is not None else None,
                "recency_percentile": recency,
                "rising_score": round(rising, 6) if rising is not None else None,
            })
            if row.get("duplicate_of") or row.get("relevance_pass") is False:
                label = "not_hot_in_current_pool"
            elif pool_size < min_pool or coverage < min_coverage or engagement is None:
                label = "insufficient_evidence"
            elif engagement >= hot_threshold:
                label = "relative_hot_candidate"
            else:
                label = "not_hot_in_current_pool"
            row["hotness_label"] = label
    return marked


def stratified_sample(scored: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    quotas = config.get("detail_quotas", {})
    available = [row for row in scored if not row.get("duplicate_of") and row.get("relevance_pass") is not False]
    selected: dict[str, dict[str, Any]] = {}

    def add(queue_name: str, ordered: list[dict[str, Any]], quota: int) -> None:
        used = 0
        for row in ordered:
            if used >= quota:
                break
            content_id = str(row["content_id"])
            if content_id not in selected:
                selected[content_id] = {**row, "selection_reasons": [queue_name]}
                used += 1
            elif queue_name not in selected[content_id]["selection_reasons"]:
                selected[content_id]["selection_reasons"].append(queue_name)

    descending = lambda value: -(float(value) if value is not None else -1.0)
    add("high_engagement", sorted(available, key=lambda row: (descending(row.get("engagement_percentile")), int(row.get("rank_on_page") or 10**9))), int(quotas.get("high_engagement", 3)))
    add("recent", sorted(available, key=lambda row: (descending(row.get("recency_percentile")), int(row.get("rank_on_page") or 10**9))), int(quotas.get("recent", 3)))
    add("comment_value", sorted(available, key=lambda row: (-(_number(row.get("food_description_density")) or 0), -(_number(row.get("comments")) or 0), int(row.get("rank_on_page") or 10**9))), int(quotas.get("comment_value", 2)))
    target = sum(int(quotas.get(name, 0)) for name in ("high_engagement", "recent", "comment_value"))
    for row in sorted(available, key=lambda item: int(item.get("rank_on_page") or 10**9)):
        if len(selected) >= min(target, len(available)):
            break
        content_id = str(row["content_id"])
        if content_id not in selected:
            selected[content_id] = {**row, "selection_reasons": ["page_order_fill"]}
    return list(selected.values())


def random_baseline(scored: list[dict[str, Any]], selected: list[dict[str, Any]], iterations: int = 100) -> dict[str, Any]:
    pool = [row for row in scored if not row.get("duplicate_of") and row.get("engagement_percentile") is not None]
    selected_values = [float(row["engagement_percentile"]) for row in selected if row.get("engagement_percentile") is not None]
    sample_size = min(len(selected_values), len(pool))
    if not pool or not sample_size:
        return {"iterations": iterations, "sample_size": 0, "system_median": None, "random_median": None, "lift": None, "status": "insufficient_evidence"}
    seed_text = "|".join(sorted(str(row.get("content_id")) for row in pool))
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
    random_medians = [statistics.median(float(row["engagement_percentile"]) for row in rng.sample(pool, sample_size)) for _ in range(iterations)]
    system_median = statistics.median(selected_values)
    baseline_median = statistics.median(random_medians)
    return {
        "iterations": iterations,
        "sample_size": sample_size,
        "system_median": round(system_median, 6),
        "random_median": round(baseline_median, 6),
        "lift": round(system_median - baseline_median, 6),
        "status": "above_baseline" if system_median > baseline_median else "not_above_baseline",
    }


def jaccard_top_ids(first: list[dict[str, Any]], second: list[dict[str, Any]], limit: int = 10) -> float:
    def top(rows: list[dict[str, Any]]) -> set[str]:
        ordered = sorted(rows, key=lambda row: (-(row.get("engagement_percentile") or -1), int(row.get("rank_on_page") or 10**9)))
        return {str(row.get("content_id")) for row in ordered[:limit]}
    left, right = top(first), top(second)
    return len(left & right) / len(left | right) if left or right else 1.0
