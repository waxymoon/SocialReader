# -*- coding: utf-8 -*-
"""新品知识库 Excel 导出（海博拓天面试官 2026-09-07 口径）。

数据源：
  - food run 产物：D:\\ObsidianVault\\采集\\美食情报\\<日期>\\<run_id>\\food_cards.jsonl
    （title/query/platform/source_url/novelty/evidences/metrics 等结构化分析结果）
  - 采集正文归档：D:\\ObsidianVault\\采集\\内容流水线\\<关键词>\\*.md（标题/作者/正文/评论/话题标签）
  join key = content_id（平台_笔记id，与 domain_pipeline 同一规则）。

表头（17 列）：渠道来源 | 一级品类 | 二级品类 | 美食话题 | 标题 | 内容类型 | 新品判断 | 新品证据 |
推荐理由(活人感原句) | 正文摘要 | 代表评论 | 作者 | 发布时间 | 点赞 | 收藏 | 评论数 | 原链接

铁律：字段读不到留空（平台未返回/待人工），绝不编数字。饮品默认过滤（供“今天吃点啥”skill）。
用法：
  python export_knowledge_base.py                # 全量导出（过滤饮品）
  python export_knowledge_base.py --include-drinks  # 含饮品行（演示“过滤”反例用）
  python export_knowledge_base.py --latest-only  # 仅最新一次 run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("缺少 openpyxl，请先安装：python -m pip install openpyxl")

from domain_pipeline import parse_capture_markdown  # md → dict（含噪声错误标记）
from food_categories import classify_text, is_drink  # 分类轴判定

ROOT = Path(__file__).resolve().parent
RUN_ROOT = Path(r"D:\ObsidianVault\采集\美食情报")  # <日期>/<run_id>/food_cards.jsonl
PIPELINE_ROOT = Path(r"D:\ObsidianVault\采集\内容流水线")  # <关键词>/*.md
DELIVERABLES = ROOT / "deliverables"

HEADERS = [
    "渠道来源", "一级品类", "二级品类", "美食话题", "标题", "内容类型",
    "新品判断", "新品证据", "推荐理由（活人感原句）", "正文摘要", "代表评论",
    "作者", "发布时间", "点赞", "收藏", "评论数", "原链接",
]
NOVELTY_LABEL_CN = {
    "confirmed_new": "是（实锤新品）",
    "likely_new": "疑似新品",
    "historical_new": "是（历史新品）",
    "new_format_or_recipe": "新做法/新配方",
    "not_new": "否",
    "unknown": "待人工核",
}


def collect_food_cards(latest_only: bool = False) -> dict[str, dict[str, Any]]:
    """遍历美食情报所有 run 的 food_cards.jsonl，按 content_id 去重（最新 run 优先）。"""
    fresh: dict[str, dict[str, Any]] = {}
    run_dirs = sorted([p for p in RUN_ROOT.glob("*/*") if p.is_dir()], key=lambda p: p.stat().st_mtime)
    if latest_only:
        run_dirs = run_dirs[-1:]
    for run_dir in reversed(run_dirs):
        fp = run_dir / "food_cards.jsonl"
        if not fp.is_file():
            continue
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                card = json.loads(line)
            except (ValueError, TypeError):
                continue
            cid = str(card.get("content_id") or "")
            if cid and cid not in fresh:
                fresh[cid] = card
    return fresh


def collect_md_items() -> dict[str, dict[str, Any]]:
    """遍历内容流水线 md，跳过汇总/坏例/夹具，按 content_id 索引。"""
    from domain_pipeline import parse_frontmatter  # frontmatter 元数据（含 content_type）

    out: dict[str, dict[str, Any]] = {}
    for md in PIPELINE_ROOT.glob("*/*.md"):
        if md.name == "_汇总.md":
            continue
        try:
            item = parse_capture_markdown(md)
        except Exception:
            continue
        if item.get("source_quality_errors") or not item.get("content_id"):
            continue  # 平台噪声/首页降级坏例不进入知识库
        if "失败" in item.get("title", "") and not item.get("body"):
            continue
        try:
            meta, _ = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            item["content_type"] = str(meta.get("content_type") or "")
        except Exception:
            item["content_type"] = ""
        out.setdefault(item["content_id"], item)
    return out


def _evidence_score(ev: dict[str, Any]) -> float:
    scores = ev.get("human_like_scores") or {}
    try:
        return float(sum(int(v or 0) for v in scores.values()))
    except (TypeError, ValueError):
        return 0.0


def pick_reasons(card: dict[str, Any], limit: int = 2) -> list[str]:
    """推荐理由：与 build_reasons 同口径——人工驳回排除，规则 pass 或 人工通过 均可入选，按总分 top N。"""
    evs = [
        e for e in card.get("evidences") or []
        if e.get("human_review_status") != "rejected"
        and (e.get("rule_review_status") == "pass" or e.get("human_review_status") == "approved")
    ]
    evs.sort(key=_evidence_score, reverse=True)
    reasons = []
    for ev in evs[:limit]:
        quote = str(ev.get("exact_quote") or "").strip()
        if not quote:
            continue
        aspect = str(ev.get("aspect") or "").strip()
        confirmed = ev.get("human_review_status") == "approved"
        suffix = "" if confirmed else "（规则通过·待人工终审）"
        reasons.append(f"“{quote}”（{aspect}）{suffix}" if aspect else f"“{quote}”{suffix}")
    return reasons


def novelty_cell(card: dict[str, Any]) -> tuple[str, str]:
    """返回 (新品判断, 新品证据原句)。"""
    novelty = card.get("novelty") or {}
    label = str(novelty.get("label") or "unknown")
    label_cn = NOVELTY_LABEL_CN.get(label, label)
    ids = novelty.get("evidence_ids") or []
    quotes: list[str] = []
    if ids:
        by_id = {str(e.get("evidence_id")): e for e in card.get("evidences") or []}
        for eid in ids[:2]:
            ev = by_id.get(str(eid))
            quote = str((ev or {}).get("exact_quote") or "").strip()
            if quote and quote not in quotes:
                quotes.append(quote)
    return label_cn, "；".join(quotes)[:300]


def comment_summary(md_item: dict[str, Any], limit: int = 3, width: int = 46) -> str:
    comments = md_item.get("comments") or []
    parts = []
    for raw in comments[:limit]:
        text = str(raw).strip()
        text = text.split("：", 1)[-1] if "：" in text else text  # 去昵称头
        text = re.sub(r"^[*\s]+", "", text)
        if len(text) > width:
            text = text[: width - 1] + "…"
        parts.append(text)
    return " ｜ ".join(parts)


def truncate(text: Any, width: int = 80) -> str:
    text = str(text or "").strip().replace("\n", " ")
    if not text:
        return ""
    return text if len(text) <= width else text[: width - 1] + "…"


BODY_PLACEHOLDERS = ("（未提取到正文）", "未获取", "未提取")


def effective_body(md: dict[str, Any], card: dict[str, Any]) -> str:
    """正文优先 md.body；占位/空时用视频转写文本兜底（desc 缺失的视频笔记）。"""
    body = str(md.get("body") or "").strip()
    if not body or body in BODY_PLACEHOLDERS:
        parts = []
        for entry in md.get("transcript") or []:
            if isinstance(entry, dict):
                text = str(entry.get("text") or "").strip()
            else:
                text = str(entry or "").strip()
            if text:
                parts.append(text)
        joined = " ".join(parts)
        return joined[:600]
    return body


def build_rows(cards: dict[str, dict[str, Any]], md_items: dict[str, dict[str, Any]], include_drinks: bool) -> tuple[list[list[Any]], dict[str, int]]:
    stats = {"total_cards": len(cards), "rows": 0, "filtered_drinks": 0, "unclassified": 0, "no_reason": 0}
    rows: list[list[Any]] = []
    for cid, card in cards.items():
        md = md_items.get(cid) or {}
        query = str(card.get("query") or md.get("query") or "")
        title = str(card.get("title") or md.get("title") or "")
        body = effective_body(md, card)
        platform_code = str(card.get("platform") or md.get("platform_code") or "unknown")
        platform_cn = "小红书" if platform_code in ("xhs", "小红书") else ("抖音" if platform_code in ("dy", "dyvideo", "抖音") else platform_code)

        cat = classify_text(query, title, body)
        if cat["excluded_drink"]:
            stats["filtered_drinks"] += 1
            if not include_drinks:
                continue
        meal, sub = cat["meal"], cat["sub"]
        if not meal and not sub:
            stats["unclassified"] += 1

        label_cn, novelty_evidence = novelty_cell(card)
        reasons = pick_reasons(card)
        if not reasons:
            stats["no_reason"] += 1

        metrics = card.get("metrics") or {}
        likes = metrics.get("likes") if metrics.get("likes") is not None else md.get("likes")
        favorites = metrics.get("favorites") if metrics.get("favorites") is not None else md.get("favorites")
        comments = metrics.get("comments") if metrics.get("comments") is not None else md.get("comments_count")

        content_type = str(md.get("content_type") or "")
        source_url = str(card.get("source_url") or md.get("source_url") or "")
        rows.append([
            platform_cn,
            meal or ("饮品（已排除）" if include_drinks and cat["excluded_drink"] else "未分类"),
            sub or (cat["drink_kind"] if cat["excluded_drink"] else ""),
            query or "",
            title,
            content_type,
            label_cn,
            novelty_evidence,
            "；".join(reasons),
            truncate(body),
            comment_summary(md),
            str(md.get("author") or card.get("author") or ""),
            str(md.get("published_at") or card.get("published_at") or ""),
            likes if likes is not None else "",
            favorites if favorites is not None else "",
            comments if comments is not None else "",
            source_url,
        ])
    stats["rows"] = len(rows)
    return rows, stats


def write_xlsx(rows: list[list[Any]], out_path: Path, stats: dict[str, int], include_drinks: bool) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "新品知识库"

    header_fill = PatternFill("solid", fgColor="F6D6DC")
    header_font = Font(bold=True, color="5A2E36", name="微软雅黑", size=10)
    cell_font = Font(name="微软雅黑", size=9)
    thin = Side(style="thin", color="D9C2C8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(vertical="top", wrap_text=True)

    ws.append(HEADERS)
    for col in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        cell.border = border
    for row in rows:
        ws.append(row)

    widths = [8, 10, 10, 14, 30, 8, 14, 30, 44, 36, 36, 12, 12, 8, 8, 8, 46]
    for idx, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(HEADERS)):
        for cell in r:
            cell.font = cell_font
            cell.border = border
            cell.alignment = wrap
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{max(1, ws.max_row)}"
    for r in range(2, ws.max_row + 1):
        link = ws.cell(row=r, column=len(HEADERS)).value
        if isinstance(link, str) and link.startswith("http"):
            ws.cell(row=r, column=len(HEADERS)).hyperlink = link
            ws.cell(row=r, column=len(HEADERS)).font = Font(name="微软雅黑", size=9, color="0563C1", underline="single")

    # 说明 sheet
    info = wb.create_sheet("口径说明")
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        ("新品知识库 · 口径说明", True),
        (f"生成时间：{now}", False),
        ("", False),
        ("数据来源", True),
        ("· 渠道：小红书 / 抖音 公开内容采集（只收录已授权公开内容）", False),
        ("· 正文归档：D:\\ObsidianVault\\采集\\内容流水线\\<话题>\\*.md", False),
        ("· 结构化分析：D:\\ObsidianVault\\采集\\美食情报\\<日期>\\<run>\\food_cards.jsonl", False),
        ("", False),
        ("分类口径（正餐/下午茶 两级，用于“今天吃点啥”skill）", True),
        ("· 一级：正餐 / 下午茶；二级：米面粥汤、快餐小炒、日料、韩料、火锅烧烤、西餐简餐、地方菜 / 烘焙甜品、轻食沙拉", False),
        ("· 全部饮品（奶茶茶饮/咖啡/其他饮品）默认过滤，不计入知识库", False),
        (f"· 本次过滤饮品：{stats['filtered_drinks']} 条；未分类：{stats['unclassified']} 条", False),
        ("", False),
        ("字段口径", True),
        ("· 新品判断：规则命中上新信号（新品/上新/联名/限定/首发/新吃法…），confirmed=实锤、likely=疑似、unknown=待人工核", False),
        ("· 新品证据：判断依据的原文原句（可回链原帖核对）", False),
        ("· 推荐理由：规则审核通过（rule pass）的活人感原句，按六维评分取前 2，仍待人工终审", False),
        ("· 点赞/收藏/评论数：平台页面返回为准；未返回留空，不估算", False),
        ("· 原链接保留平台签名参数（xsec_token 等），浏览器登录态下可回查", False),
        ("", False),
        (f"本次统计：总卡 {stats['total_cards']} / 导出行 {stats['rows']} / 无规则通过理由 {stats['no_reason']}", False),
    ]
    for text, bold in lines:
        info.append([text])
        cell = info.cell(row=info.max_row, column=1)
        cell.font = Font(name="微软雅黑", size=10 if not bold else 11, bold=bold, color="5A2E36" if bold else "333333")
    info.column_dimensions["A"].width = 110

    wb.save(out_path)
    return out_path


def run_export(include_drinks: bool = False, latest_only: bool = False, out_path: str | None = None) -> tuple[Path, dict[str, int]]:
    """导出全量/最新 run 的新品知识库 xlsx，返回 (路径, 统计)。"""
    cards = collect_food_cards(latest_only=latest_only)
    if not cards:
        raise RuntimeError("没有找到 food_cards 数据，请先采集并分析")
    md_items = collect_md_items()
    rows, stats = build_rows(cards, md_items, include_drinks=include_drinks)
    if not rows:
        raise RuntimeError("知识库为空（可能全部被饮品过滤，可改用 include_drinks 查看）")
    path = Path(out_path) if out_path else DELIVERABLES / f"新品知识库_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    DELIVERABLES.mkdir(parents=True, exist_ok=True)
    write_xlsx(rows, path, stats, include_drinks=include_drinks)
    return path, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="新品知识库 Excel 导出")
    parser.add_argument("--out", default=None, help="输出 xlsx 路径（默认 deliverables/新品知识库_<时间>.xlsx）")
    parser.add_argument("--include-drinks", action="store_true", help="包含饮品行（演示“过滤”效果用）")
    parser.add_argument("--latest-only", action="store_true", help="仅导出最新一次 run")
    args = parser.parse_args()
    try:
        out_path, stats = run_export(
            include_drinks=args.include_drinks, latest_only=args.latest_only, out_path=args.out
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(f"知识库已导出：{out_path}")
    print(f"统计：总卡 {stats['total_cards']} → 行 {stats['rows']}，滤饮品 {stats['filtered_drinks']}，未分类 {stats['unclassified']}，无理由 {stats['no_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
