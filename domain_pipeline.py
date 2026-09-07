# -*- coding: utf-8 -*-
"""SocialReader food_v1 领域管线：本地抽取、证据校验、审核与导出。"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from food_metrics import (
    derive_content_id,
    normalize_source_url,
    random_baseline,
    read_json,
    read_jsonl,
    score_candidate_pool,
    stratified_sample,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parent
DOMAIN_ROOT = ROOT / "domains" / "food_v1"
MANIFEST_PATH = DOMAIN_ROOT / "manifest.json"
KEYWORDS_PATH = DOMAIN_ROOT / "keywords.json"
ACCEPTANCE_FIXTURES = DOMAIN_ROOT / "evals" / "stage1_acceptance_cases.jsonl"
CANDIDATE_POOL_FIXTURE = DOMAIN_ROOT / "evals" / "candidate_pool_fixture.jsonl"
DEFAULT_OUTPUT_ROOT = Path(r"D:\ObsidianVault\采集\美食情报")

FOOD_TERMS = (
    "三文鱼波奇饭", "波奇饭", "三文鱼", "虾滑", "虾肉", "虾", "奶茶", "咖啡", "牛油果",
    "米饭", "温泉蛋", "鱼子", "玉米", "甜品", "小吃", "早餐", "夜宵", "轻食",
)
INGREDIENT_TERMS = ("三文鱼", "虾肉", "虾", "牛油果", "米饭", "温泉蛋", "飞鱼籽", "鱼子", "玉米", "海苔")
FLAVOR_TERMS = ("鲜香", "鲜美", "清爽", "清甜", "茶味", "奶香", "油脂香", "不腻", "香")
TEXTURE_TERMS = ("Q弹", "Q 弹", "软嫩", "软糯", "绵密", "酥脆", "爆汁", "拉丝", "糯叽叽", "厚实", "嫩")
METHOD_TERMS = ("切", "拌", "搅拌", "煮", "烤", "炸", "蒸", "煎", "焖", "不用开火")
SCENE_TERMS = ("工作日午餐", "年夜饭", "晚餐", "早餐", "夜宵", "宅家")
NEW_SIGNALS = ("正式上线", "上新", "新品", "联名", "限定", "首发")
NEW_FORMAT_SIGNALS = ("新吃法", "新搭配", "新规格", "隐藏吃法")
INVALID_NEW_ONLY = ("第一次吃", "最近发现", "终于吃到了", "宝藏店铺", "新鲜")
RISK_PATTERNS = ("吃完瘦", "必瘦", "治愈", "治疗", "降血糖", "减肥神器")
HARD_FILTER_PATTERNS = ("求链接", "求地址", "地址在哪", "多少钱", "问价格")
GENERIC_EXACT = ("绝了", "不错", "好吃", "好吃绝了", "看起来不错")
PAGE_NOISE_MARKERS = ("开启读屏标签", "信息网络传播视听节目许可证", "广播电视节目制作经营许可证", "互联网新闻信息服务许可证")
SENSORY_TERMS = FLAVOR_TERMS + TEXTURE_TERMS + ("口感", "味道", "香气", "入口", "每一口", "咬", "嚼", "冒尖", "铺满")
REQUIRED_EXACT_PHRASES = (
    "虾究极 Q 弹",
    "拜见三文鱼波奇饭大王",
    "每一口都能嚼到虾肉",
    "好吃绝了",
    "求地址",
    "看起来不错",
    "吃完瘦三斤",
    "这杯奶茶茶味清爽",
)


@dataclass
class SourceSegment:
    source_type: str
    location: str
    text: str


def load_config() -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(MANIFEST_PATH), read_json(KEYWORDS_PATH)


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[1:-1]
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    metadata: dict[str, Any] = {}
    current_list = ""
    for raw in text[4:end].splitlines():
        if raw.startswith("  - ") and current_list:
            metadata.setdefault(current_list, []).append(_unquote(raw[4:]))
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not match:
            continue
        key, value = match.groups()
        if value:
            metadata[key] = _unquote(value)
            current_list = ""
        else:
            metadata[key] = [] if key == "tags" else ""
            current_list = key if key == "tags" else ""
    return metadata, text[end + 5 :]


def _section(text: str, heading: str) -> str:
    match = re.search(rf"(?ms)^##\s+{re.escape(heading)}[^\n]*\n(.*?)(?=^##\s+|\Z)", text)
    return match.group(1).strip() if match else ""


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _clean_comment(line: str) -> str:
    value = re.sub(r"^-\s+\*\*.*?\*\*(?:（.*?）)?[：:]?", "", line.strip())
    value = re.sub(r"\s+—\s+赞\s+\S+\s*$", "", value)
    return value.strip()


def _parse_transcript(raw: str) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for index, line in enumerate(raw.splitlines(), 1):
        match = re.match(r"^\[([^\]]+)\]\s*(.+)$", line.strip())
        if match:
            output.append({"location": match.group(1).replace("→", "-").replace(" ", ""), "text": match.group(2).strip()})
        elif line.strip() and not line.startswith("（"):
            output.append({"location": f"segment_{index}", "text": line.strip()})
    return output


def parse_capture_markdown(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata, body_text = parse_frontmatter(text)
    body = _section(body_text, "正文")
    comments_raw = _section(body_text, "评论")
    transcript_raw = _section(body_text, "视频转写")
    comments = [_clean_comment(line) for line in comments_raw.splitlines() if line.strip().startswith("-")]
    platform = str(metadata.get("source") or metadata.get("platform") or "unknown")
    source_url = normalize_source_url(metadata.get("url", ""))
    title_match = re.search(r"(?m)^#\s+(.+)$", body_text)
    title = str(metadata.get("title") or (title_match.group(1).strip() if title_match else path.stem))
    published_at = str(metadata.get("published_at") or "") or None
    query = path.parent.name
    source_quality_errors: list[dict[str, str]] = []
    noise_hits = [marker for marker in PAGE_NOISE_MARKERS if marker in body]
    if len(noise_hits) >= 2 or (title in {"抖音内容", "未获取"} and noise_hits):
        source_quality_errors.append({
            "code": "source_page_noise",
            "field": "body",
            "message": "详情降级结果包含平台首页导航或许可证文本，不能计为有效内容",
        })
    return {
        "content_id": derive_content_id(platform, source_url, title),
        "platform": str(metadata.get("platform") or platform),
        "platform_code": platform,
        "source_url": source_url,
        "published_at": published_at,
        "query": query,
        "title": title,
        "author": str(metadata.get("author") or ""),
        "body": body,
        "comments": comments,
        "transcript": _parse_transcript(transcript_raw),
        "likes": _parse_int(metadata.get("likes")),
        "favorites": _parse_int(metadata.get("favorites")),
        "comments_count": _parse_int(metadata.get("comments")),
        "shares": _parse_int(metadata.get("shares")),
        "raw_file": str(path.resolve()),
        "source_kind": "real_local_capture",
        "prompt_version": "prompt_v1",
        "source_quality_errors": source_quality_errors,
    }


def fixture_segments(item: dict[str, Any]) -> list[SourceSegment]:
    segments: list[SourceSegment] = []
    for index, paragraph in enumerate(re.split(r"[\n。！？]+", str(item.get("body") or "")), 1):
        if paragraph.strip():
            segments.append(SourceSegment("body", f"paragraph_{index}", paragraph.strip()))
    for index, comment in enumerate(item.get("comments") or [], 1):
        segments.append(SourceSegment("comment", f"comment_{index}", str(comment).strip()))
    for index, entry in enumerate(item.get("transcript") or [], 1):
        if isinstance(entry, dict):
            segments.append(SourceSegment("video_transcript", str(entry.get("location") or f"segment_{index}"), str(entry.get("text") or "").strip()))
        else:
            segments.append(SourceSegment("video_transcript", f"segment_{index}", str(entry).strip()))
    return [segment for segment in segments if segment.text]


def _target(quote: str, title: str) -> str:
    for term in FOOD_TERMS:
        if term in quote:
            return term
    for term in FOOD_TERMS:
        if term in title:
            return term
    return ""


def _aspect(quote: str) -> tuple[str, str]:
    for term in TEXTURE_TERMS:
        if term in quote:
            return "口感", term.replace(" ", "")
    for term in FLAVOR_TERMS:
        if term in quote:
            return "味道", term
    if any(term in quote for term in ("冒尖", "铺满", "粉粉嫩嫩", "大块")):
        return "外观/分量", "具象描述"
    if any(term in quote for term in METHOD_TERMS):
        return "吃法/做法", "体验动作"
    if "拜见" in quote or "大王" in quote:
        return "表达", "拟人"
    return "体验", ""


def human_like_scores(quote: str, target: str) -> dict[str, int]:
    memorable_signal = any(term in quote for term in ("究极", "拜见", "大王", "爆炸", "冒尖"))
    specific = 2 if any(term in quote for term in SENSORY_TERMS) else (1 if any(term in quote for term in METHOD_TERMS + SCENE_TERMS) or (target and memorable_signal) else 0)
    sensory = 2 if any(term in quote for term in FLAVOR_TERMS + TEXTURE_TERMS) else (1 if any(term in quote for term in ("入口", "每一口", "咬", "嚼", "冒尖", "铺满")) else 0)
    colloquial = 2 if any(term in quote for term in ("究极", "拜见", "大王", "谁不馋", "真的", "一口")) else 1
    memorable = 2 if memorable_signal else (1 if "！" in quote or "一口" in quote else 0)
    usable = 2 if specific or sensory else (1 if target else 0)
    return {
        "food_relevance": 2 if target else 0,
        "specificity": specific,
        "sensory_richness": sensory,
        "colloquiality": colloquial,
        "memorability": memorable,
        "recommendation_usability": usable,
    }


def expression_review(quote: str, scores: dict[str, int]) -> tuple[str, str, list[str]]:
    compact = re.sub(r"[\s，。！？!,.]", "", quote)
    risks = [pattern for pattern in RISK_PATTERNS if pattern in quote]
    if any(pattern in quote for pattern in HARD_FILTER_PATTERNS):
        return "fail", "hard_filter_request", risks
    if risks:
        return "fail", "unsupported_health_claim", risks
    if compact in GENERIC_EXACT:
        return "fail", "generic_without_food_attribute", risks
    total = sum(scores.values())
    if scores["food_relevance"] != 2:
        return "fail", "food_target_missing", risks
    if max(scores["specificity"], scores["sensory_richness"]) < 1 or total < 7:
        return "fail", "human_like_score_below_threshold", risks
    return "pass", "rule_threshold_passed_pending_human", risks


def _candidate_quotes(segment: SourceSegment, title: str) -> list[str]:
    pieces = [part.strip() for part in re.split(r"[。！？!；;\n]+", segment.text) if part.strip()]
    output: list[str] = [phrase for phrase in REQUIRED_EXACT_PHRASES if phrase in segment.text]
    for piece in pieces:
        if any(phrase in piece for phrase in REQUIRED_EXACT_PHRASES):
            continue
        contains_signal = any(term in piece for term in SENSORY_TERMS + METHOD_TERMS + ("拜见", "大王", "究极"))
        is_filter_case = any(term in piece for term in HARD_FILTER_PATTERNS + RISK_PATTERNS) or re.sub(r"[\s，。！？!,.]", "", piece) in GENERIC_EXACT
        if contains_signal or is_filter_case:
            output.append(piece[:160])
    return output


def _date(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def extract_item(item: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item["source_url"] = normalize_source_url(item.get("source_url"))
    item["content_id"] = str(item.get("content_id") or derive_content_id(str(item.get("platform_code") or item.get("platform") or "unknown"), item["source_url"], str(item.get("title") or "")))
    segments = fixture_segments(item)
    evidences: list[dict[str, Any]] = []
    seen_quotes: set[tuple[str, str]] = set()
    expected_reviews = item.get("expected_reviews") or {}
    for segment in segments:
        for quote in _candidate_quotes(segment, str(item.get("title") or "")):
            key = (quote, segment.source_type)
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            target = _target(quote, str(item.get("title") or ""))
            aspect, normalized = _aspect(quote)
            scores = human_like_scores(quote, target)
            rule_status, review_reason, risks = expression_review(quote, scores)
            expected = expected_reviews.get(quote)
            human_status = expected if expected in {"approved", "rejected"} else "pending"
            evidences.append({
                "evidence_id": f"ev_{item['content_id']}_{len(evidences) + 1:03d}",
                "content_id": item["content_id"],
                "exact_quote": quote,
                "source_type": segment.source_type,
                "evidence_location": segment.location,
                "source_excerpt": segment.text,
                "target": target,
                "aspect": aspect,
                "normalized_attribute": normalized,
                "sentiment": "unknown",
                "expression_style": [name for name, present in (("程度强化", any(term in quote for term in ("究极", "超", "很"))), ("拟人", any(term in quote for term in ("拜见", "大王"))), ("口语", True)) if present],
                "human_like_scores": scores,
                "rule_review_status": rule_status,
                "human_review_status": human_status,
                "review_reason": "任务书人工预期" if expected else review_reason,
                "risk_flags": risks,
            })

    launch_evidence_ids: list[str] = []
    novelty_type = "unknown"
    for segment in segments:
        if segment.source_type == "comment" and ("?" in segment.text or "吗" in segment.text):
            continue
        if any(signal in segment.text for signal in NEW_FORMAT_SIGNALS):
            novelty_type = "new_format_or_recipe"
        elif any(signal in segment.text for signal in NEW_SIGNALS) and not (
            any(invalid in segment.text for invalid in INVALID_NEW_ONLY) and not any(signal in segment.text for signal in NEW_SIGNALS)
        ):
            novelty_type = "new_product"
        else:
            continue
        evidence = {
            "evidence_id": f"ev_{item['content_id']}_{len(evidences) + 1:03d}",
            "content_id": item["content_id"],
            "exact_quote": segment.text[:160],
            "source_type": segment.source_type,
            "evidence_location": segment.location,
            "source_excerpt": segment.text,
            "target": _target(segment.text, str(item.get("title") or "")),
            "aspect": "新品证据",
            "normalized_attribute": novelty_type,
            "sentiment": "unknown",
            "expression_style": [],
            "human_like_scores": {},
            "rule_review_status": "pass",
            "human_review_status": "pending",
            "review_reason": "明确新品信号，待人工确认",
            "risk_flags": [],
        }
        evidences.append(evidence)
        launch_evidence_ids.append(evidence["evidence_id"])

    title = str(item.get("title") or "")
    food_name = next((term for term in FOOD_TERMS if term in title), "") or next((term for term in FOOD_TERMS if any(term in segment.text for segment in segments)), "")
    approved_attribute_evidence = [evidence for evidence in evidences if evidence["target"] and evidence["aspect"] != "新品证据"]
    ingredients = sorted({term for term in INGREDIENT_TERMS if term in title or any(term in segment.text for segment in segments)})
    flavors = sorted({term for term in FLAVOR_TERMS if any(term in segment.text for segment in segments)})
    textures = sorted({term.replace(" ", "") for term in TEXTURE_TERMS if any(term in segment.text for segment in segments)})
    methods = sorted({term for term in METHOD_TERMS if any(term in segment.text for segment in segments)})
    scenes = sorted({term for term in SCENE_TERMS if any(term in segment.text for segment in segments)})
    published = _date(item.get("published_at"))
    window_days = int(manifest.get("date_window_days", 45))
    within_window = bool(published and datetime.now(timezone.utc) - published.astimezone(timezone.utc) <= timedelta(days=window_days))
    if novelty_type == "new_format_or_recipe" and launch_evidence_ids:
        novelty_label = "new_format_or_recipe"
    elif launch_evidence_ids and food_name and within_window:
        novelty_label = "confirmed_new"
    elif launch_evidence_ids and published and not within_window:
        novelty_label = "historical_new"
    elif launch_evidence_ids and sum((bool(food_name), bool(published), bool(launch_evidence_ids))) >= 2:
        novelty_label = "likely_new"
    elif not published or not food_name:
        novelty_label = "unknown"
    else:
        novelty_label = "not_new"
    metric_values = [item.get("likes"), item.get("favorites"), item.get("comments_count"), item.get("shares")]
    coverage = sum(value is not None for value in metric_values) / 4
    card = {
        "schema_version": "food_v1",
        "content_id": item["content_id"],
        "platform": str(item.get("platform") or "unknown"),
        "source_url": item["source_url"],
        "source_kind": str(item.get("source_kind") or "unknown"),
        "raw_file": item.get("raw_file"),
        "query": str(item.get("query") or ""),
        "title": title,
        "published_at": item.get("published_at"),
        "metrics": {"likes": item.get("likes"), "favorites": item.get("favorites"), "comments": item.get("comments_count"), "shares": item.get("shares")},
        "metric_coverage": coverage,
        "food_items": [{
            "food_name": food_name,
            "brand_or_store": "",
            "category": "轻食/波奇饭" if "波奇饭" in food_name else food_name,
            "ingredients": ingredients,
            "flavors": flavors,
            "textures": textures,
            "cooking_methods": methods,
            "temperature": "",
            "portion": "",
            "price": None,
            "scenes": scenes,
            "dietary_claims": [],
            "evidence_ids": [evidence["evidence_id"] for evidence in approved_attribute_evidence],
        }] if food_name else [],
        "novelty": {"label": novelty_label, "evidence_ids": launch_evidence_ids, "rule_version": manifest["newness_rule_version"]},
        "hotness": {
            "label": "insufficient_evidence",
            "pool_size": 1,
            "engagement_percentile": None,
            "metric_coverage": coverage,
            "rule_version": manifest["hotness_rule_version"],
            "scope_note": manifest["external_claim_scope"],
        },
        "evidences": evidences,
        "prompt_version": str(item.get("prompt_version") or manifest["prompt_version"]),
        "rule_versions": {"newness": manifest["newness_rule_version"], "hotness": manifest["hotness_rule_version"], "expression": manifest["expression_rule_version"]},
        "errors": [],
    }
    return card


def validate_card(card: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for field in ("content_id", "platform", "source_url"):
        if not isinstance(card.get(field), str) or not card[field]:
            errors.append({"code": "required_field", "field": field, "message": "必填字段缺失"})
    seen_quotes: set[tuple[str, str, str]] = set()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for evidence in card.get("evidences", []):
        evidence_id = str(evidence.get("evidence_id") or "")
        evidence_by_id[evidence_id] = evidence
        quote = str(evidence.get("exact_quote") or "")
        excerpt = str(evidence.get("source_excerpt") or "")
        source_type = str(evidence.get("source_type") or "")
        location = str(evidence.get("evidence_location") or "")
        if not quote or quote not in excerpt:
            errors.append({"code": "quote_not_traceable", "field": evidence_id, "message": "exact_quote 不是对应原文片段的子串"})
        if source_type == "video_transcript" and not (re.search(r"\d", location) and ("-" in location or "segment_" in location)):
            errors.append({"code": "invalid_video_location", "field": evidence_id, "message": "视频证据缺少合法时间点"})
        if source_type == "comment" and not re.fullmatch(r"comment_\d+", location):
            errors.append({"code": "invalid_comment_location", "field": evidence_id, "message": "评论证据缺少评论序号"})
        quote_key = (str(card.get("content_id")), source_type, quote)
        if quote_key in seen_quotes:
            errors.append({"code": "duplicate_quote", "field": evidence_id, "message": "相同原句重复入库"})
        seen_quotes.add(quote_key)
    if card.get("novelty", {}).get("label") in {"confirmed_new", "likely_new", "historical_new", "new_format_or_recipe"}:
        for evidence_id in card.get("novelty", {}).get("evidence_ids", []):
            if evidence_id not in evidence_by_id or evidence_by_id[evidence_id].get("aspect") != "新品证据":
                errors.append({"code": "invalid_novelty_evidence", "field": str(evidence_id), "message": "新品标签缺少对应证据"})
    return errors


def build_reasons(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for card in cards:
        # 人工是最终裁判：人工 approved 可覆盖规则 fail（错字/词库未覆盖等）；
        # 仅规则 pass 的证据也生成（标记 pending，等人工终审）；人工 rejected 一律排除。
        for evidence in card.get("evidences", []):
            if evidence.get("human_review_status") == "rejected":
                continue
            model_pass = bool((evidence.get("model_review") or {}).get("pass"))
            if not (evidence.get("rule_review_status") == "pass"
                    or evidence.get("human_review_status") == "approved"
                    or model_pass):
                continue
            if evidence.get("risk_flags"):
                continue
            if evidence.get("aspect") == "新品证据":
                continue
            approved = evidence.get("human_review_status") == "approved"
            quote = str(evidence.get("exact_quote") or "").strip()
            aspect = str(evidence.get("aspect") or "").strip()
            # 推荐理由 = 通过审核/语义评估的活人感原句本身（网友真实评价即最佳种草理由）
            reason = f"“{quote}”" if quote else "（原句缺失）"
            source = "vetted_quote_v1"
            if approved:
                source = "human_approved_v1"
            elif model_pass:
                source = "semantic_pass_v1"
            reasons.append({
                "content_id": card["content_id"],
                "reason": reason,
                "aspect": aspect,
                "evidence_ids": [evidence["evidence_id"]],
                "risk_flags": [],
                "generation_source": source,
                "human_confirmed": approved,
                "review_status": "approved" if approved else "pending",
                "prompt_version": card["prompt_version"],
            })
    return reasons


def plan_queries(seed_category: str, existing_queries: Iterable[str] = (), maximum: int = 12) -> list[dict[str, str]]:
    _, keywords = load_config()
    seed = seed_category.strip()
    if not seed or seed in keywords.get("excluded_standalone_terms", []):
        raise ValueError("种子品类不能为空，也不能仅使用过宽泛词")
    existing = {re.sub(r"\s+", "", str(value)) for value in existing_queries}
    candidates: list[dict[str, str]] = []
    axes = (
        ("new", keywords["trend_terms"][:4], ["测评", "口感"]),
        ("hot", ["最近很火", "必吃", "回购"], ["测评", "一口"]),
        ("description", [""], keywords["description_terms"][:6]),
    )
    for signal_type, signal_terms, description_terms in axes:
        for signal in signal_terms:
            description = description_terms[len(candidates) % len(description_terms)]
            query = f"{seed}{signal}{description}".strip()
            compact = re.sub(r"\s+", "", query)
            if compact in existing or any(item["query"] == query for item in candidates):
                continue
            candidates.append({
                "query": query,
                "category_term": seed,
                "signal_type": signal_type,
                "signal_term": signal,
                "description_term": description,
                "reason": "覆盖明确上新信号与体验描述" if signal_type == "new" else ("覆盖当前候选池热度线索" if signal_type == "hot" else "覆盖具体感官表达"),
                "risk": "可能混入旧产品回顾" if signal_type == "new" else "需在候选池范围内解释",
            })
            if len(candidates) >= maximum:
                return candidates
    return candidates


def _report(cards: list[dict[str, Any]], reasons: list[dict[str, Any]], run_meta: dict[str, Any]) -> str:
    evidences = [evidence for card in cards for evidence in card.get("evidences", [])]
    traceable = [evidence for evidence in evidences if evidence.get("exact_quote") and evidence["exact_quote"] in str(evidence.get("source_excerpt") or "")]
    failures = [error for card in cards for error in card.get("errors", [])]
    real_cards = [card for card in cards if card.get("source_kind") == "real_local_capture"]
    invalid_real_count = sum(bool(card.get("errors")) for card in real_cards)
    real_count = len(real_cards) - invalid_real_count
    fixture_count = sum(card.get("source_kind") == "taskbook_acceptance_fixture" for card in cards)
    return "\n".join([
        f"# food_v1 运行报告 {run_meta['run_id']}",
        "",
        f"> 运行时间：{run_meta['run_at']}。真实本地采集与任务书验收夹具严格分开计数。",
        "",
        f"- 有效真实本地内容：{real_count} 篇",
        f"- 真实采集坏例：{invalid_real_count} 篇",
        f"- 任务书验收夹具：{fixture_count} 篇",
        f"- 原句证据：{len(evidences)} 条",
        f"- 可逐字回溯：{len(traceable)}/{len(evidences)}" if evidences else "- 可逐字回溯：无证据",
        f"- 确定性校验失败：{len(failures)} 条",
        f"- 已人工确认可生成理由：{len(reasons)} 条（仅来自任务书已给定预期或页面人工操作）",
        "",
        "## 口径",
        "",
        "本报告不声称平台全站热门。单篇本地内容没有完整候选池，因此热门字段保留 insufficient_evidence。",
        "",
        "## 失败与待审",
        "",
        *(f"- {card['content_id']}：{error['code']} / {error['message']}" for card in cards for error in card.get("errors", [])),
        *(f"- {card['content_id']}：{sum(e.get('human_review_status') == 'pending' for e in card.get('evidences', []))} 条待人工审核" for card in cards if any(e.get("human_review_status") == "pending" for e in card.get("evidences", []))),
        "",
    ])


def run_analysis(items: list[dict[str, Any]], output_root: Path = DEFAULT_OUTPUT_ROOT, run_id: str | None = None) -> Path:
    manifest, _ = load_config()
    now = datetime.now().astimezone()
    actual_run_id = run_id or f"food_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_dir = output_root / now.strftime("%Y-%m-%d") / actual_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    run_meta = {
        "run_id": actual_run_id,
        "run_at": now.isoformat(timespec="seconds"),
        "domain": "food_v1",
        "prompt_version": manifest["prompt_version"],
        "model": "none_rules_only",
        "data_counts": {
            "real_local_capture": sum(item.get("source_kind") == "real_local_capture" for item in items),
            "taskbook_acceptance_fixture": sum(item.get("source_kind") == "taskbook_acceptance_fixture" for item in items),
        },
    }
    cards: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    for item in items:
        raw_rows.append({key: value for key, value in item.items() if key not in {"body", "comments", "transcript", "expected_reviews"}})
        try:
            source_quality_errors = item.get("source_quality_errors", [])
            if source_quality_errors:
                card = {
                    "schema_version": "food_v1",
                    "content_id": str(item.get("content_id") or "unknown"),
                    "platform": str(item.get("platform") or "unknown"),
                    "source_url": normalize_source_url(item.get("source_url")),
                    "published_at": item.get("published_at"),
                    "food_items": [],
                    "evidences": [],
                    "novelty": {"label": "unknown", "evidence_ids": [], "rule_version": manifest["newness_rule_version"]},
                    "hotness": {"label": "insufficient_evidence", "pool_size": 1, "engagement_percentile": None, "metric_coverage": 0, "rule_version": manifest["hotness_rule_version"]},
                    "errors": source_quality_errors,
                    "source_kind": str(item.get("source_kind") or "unknown"),
                    "query": str(item.get("query") or ""),
                    "title": str(item.get("title") or ""),
                    "prompt_version": manifest["prompt_version"],
                }
            else:
                card = extract_item(item, manifest)
                card["errors"] = validate_card(card)
        except Exception as exc:
            card = {
                "schema_version": "food_v1",
                "content_id": str(item.get("content_id") or "unknown"),
                "platform": str(item.get("platform") or "unknown"),
                "source_url": normalize_source_url(item.get("source_url")),
                "published_at": item.get("published_at"),
                "food_items": [], "evidences": [],
                "novelty": {"label": "unknown", "evidence_ids": [], "rule_version": manifest["newness_rule_version"]},
                "hotness": {"label": "insufficient_evidence", "pool_size": 1, "engagement_percentile": None, "metric_coverage": 0, "rule_version": manifest["hotness_rule_version"]},
                "errors": [{"code": "item_failed", "field": "", "message": f"{type(exc).__name__}: {exc}"}],
                "source_kind": str(item.get("source_kind") or "unknown"),
                "query": str(item.get("query") or ""),
                "title": str(item.get("title") or ""),
                "prompt_version": manifest["prompt_version"],
            }
        cards.append(card)
    reasons = build_reasons(cards)
    write_jsonl(output_dir / "raw_index.jsonl", raw_rows)
    write_jsonl(output_dir / "food_cards.jsonl", cards)
    write_jsonl(output_dir / "vivid_expressions.jsonl", [evidence for card in cards for evidence in card.get("evidences", [])])
    write_jsonl(output_dir / "review_results.jsonl", [
        {key: evidence.get(key) for key in ("evidence_id", "content_id", "exact_quote", "rule_review_status", "human_review_status", "review_reason", "risk_flags")}
        for card in cards for evidence in card.get("evidences", [])
    ])
    write_jsonl(output_dir / "recommendation_reasons.jsonl", reasons)
    (output_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (output_dir / "report.md").write_text(_report(cards, reasons, run_meta), encoding="utf-8", newline="\n")
    (output_root / "latest_run.txt").parent.mkdir(parents=True, exist_ok=True)
    (output_root / "latest_run.txt").write_text(str(output_dir), encoding="utf-8", newline="\n")
    # 跨 run 继承人工审核状态（approved/rejected），避免重新分析丢标注
    try:
        inherited = inherit_human_reviews(output_dir, run_root=output_root)
        if inherited.get("approved") or inherited.get("rejected"):
            run_meta["inherited_reviews"] = inherited
            (output_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except Exception:
        pass  # 继承失败不阻断分析（历史 run 缺失/损坏时静默降级）
    return output_dir


def load_analysis_items(input_dir: Path, include_fixtures: bool = False, limit: int = 5) -> list[dict[str, Any]]:
    paths = sorted(path for path in input_dir.glob("*.md") if path.name != "_汇总.md")[:limit]
    items = [parse_capture_markdown(path) for path in paths]
    if include_fixtures:
        items.extend(read_jsonl(ACCEPTANCE_FIXTURES))
    return items


def inherit_human_reviews(output_dir: Path, run_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, int]:
    """把历史 run 的人工审核状态（approved/rejected+原因）继承到新 run 的相同证据上。

    合并键 = evidence_id（跨 run 稳定：content_id+证据序号）。只覆盖新 run 中仍为
    pending 的证据（本 run 刚标过的不覆盖）。无历史或全 pending 时 no-op。
    """
    cards = read_jsonl(output_dir / "food_cards.jsonl")
    if not cards:
        return {"approved": 0, "rejected": 0}
    history: dict[str, tuple[str, str]] = {}
    for run_dir in sorted(run_root.glob("*/*"), key=lambda p: p.stat().st_mtime):
        if run_dir.resolve() == output_dir.resolve():
            continue
        rp = run_dir / "review_results.jsonl"
        if not rp.is_file():
            continue
        for row in read_jsonl(rp):
            hid = str(row.get("evidence_id") or "")
            status = str(row.get("human_review_status") or "")
            if hid and status in ("approved", "rejected"):
                history.setdefault(hid, (status, str(row.get("review_reason") or "")))
    if not history:
        return {"approved": 0, "rejected": 0}
    counts = {"approved": 0, "rejected": 0}
    changed = False
    for card in cards:
        for evidence in card.get("evidences", []):
            if evidence.get("human_review_status") != "pending":
                continue
            hid = str(evidence.get("evidence_id") or "")
            if hid not in history:
                continue
            status, reason = history[hid]
            evidence["human_review_status"] = status
            evidence["review_reason"] = reason or ("人工审核继承" if status == "approved" else "人工驳回继承")
            counts[status] = counts.get(status, 0) + 1
            changed = True
    if changed:
        reasons = build_reasons(cards)
        write_jsonl(output_dir / "food_cards.jsonl", cards)
        write_jsonl(output_dir / "vivid_expressions.jsonl", [e for c in cards for e in c.get("evidences", [])])
        write_jsonl(output_dir / "review_results.jsonl", [
            {key: e.get(key) for key in ("evidence_id", "content_id", "exact_quote", "rule_review_status", "human_review_status", "review_reason", "risk_flags")}
            for c in cards for e in c.get("evidences", [])
        ])
        write_jsonl(output_dir / "recommendation_reasons.jsonl", reasons)
    return counts


def update_review(output_dir: Path, evidence_id: str, status: str, reason: str) -> dict[str, Any]:
    if status not in {"approved", "rejected", "pending"}:
        raise ValueError("审核状态无效")
    cards = read_jsonl(output_dir / "food_cards.jsonl")
    updated: dict[str, Any] | None = None
    for card in cards:
        for evidence in card.get("evidences", []):
            if evidence.get("evidence_id") == evidence_id:
                evidence["human_review_status"] = status
                evidence["review_reason"] = reason.strip() or "页面人工审核"
                updated = evidence
    if updated is None:
        raise ValueError("未找到证据")
    write_jsonl(output_dir / "food_cards.jsonl", cards)
    write_jsonl(output_dir / "vivid_expressions.jsonl", [evidence for card in cards for evidence in card.get("evidences", [])])
    write_jsonl(output_dir / "review_results.jsonl", [
        {key: evidence.get(key) for key in ("evidence_id", "content_id", "exact_quote", "rule_review_status", "human_review_status", "review_reason", "risk_flags")}
        for card in cards for evidence in card.get("evidences", [])
    ])
    write_jsonl(output_dir / "recommendation_reasons.jsonl", build_reasons(cards))
    return updated


def run_candidate_pool(input_path: Path, output_dir: Path) -> dict[str, Any]:
    """先原样保存候选池，再做确定性评分、抽样和随机基线。"""
    manifest, _ = load_config()
    raw_rows = read_jsonl(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "candidate_pool_raw.jsonl", raw_rows)
    scored = score_candidate_pool(raw_rows, manifest)
    selected = stratified_sample(scored, manifest)
    baseline = random_baseline(scored, selected, 100)
    write_jsonl(output_dir / "candidate_pool_scored.jsonl", scored)
    write_jsonl(output_dir / "selected_candidates.jsonl", selected)
    (output_dir / "random_baseline.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return {"raw": raw_rows, "scored": scored, "selected": selected, "baseline": baseline}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SocialReader food_v1 领域管线")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="分析本地已采集 Markdown")
    analyze.add_argument("input_dir", type=Path)
    analyze.add_argument("--limit", type=int, default=5)
    analyze.add_argument("--include-acceptance-fixtures", action="store_true")
    analyze.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    plan = subparsers.add_parser("plan-queries", help="生成规则搜索词候选")
    plan.add_argument("seed_category")
    plan.add_argument("--max", type=int, default=12, dest="maximum")
    pool = subparsers.add_parser("score-pool", help="对固定候选池离线评分与抽样")
    pool.add_argument("input_path", type=Path)
    pool.add_argument("output_dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "plan-queries":
        print(json.dumps({"queries": plan_queries(args.seed_category, maximum=args.maximum)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "score-pool":
        result = run_candidate_pool(args.input_path, args.output_dir)
        print(json.dumps({"raw": len(result["raw"]), "scored": len(result["scored"]), "selected": len(result["selected"]), "baseline": result["baseline"]}, ensure_ascii=False, indent=2))
        return 0
    items = load_analysis_items(args.input_dir, args.include_acceptance_fixtures, args.limit)
    if not items:
        print("[无输入] 未找到可分析 Markdown", file=sys.stderr)
        return 2
    output_dir = run_analysis(items, args.output_root)
    print(f"[food_v1] 输入 {len(items)} 条")
    print(f"[food_v1] 输出 {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
