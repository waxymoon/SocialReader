# -*- coding: utf-8 -*-
"""批量萃取 SocialReader 采集笔记，并通过复利融合写入知识库。"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from merge_utils import call_llm, save_with_merge


CAPTURE_ROOT = Path(r"D:\ObsidianVault\采集\内容流水线")
VAULT_ROOT = Path(r"D:\ObsidianVault")
STATE_FILE = Path(__file__).resolve().parent / "extract_state.json"
EXCLUDED_DIRS = {
    "0-收件箱",
    "5-已归档",
    "模板",
    "附件",
    ".obsidian",
    ".trash",
    "对话记录",
    "日报",
    "airp",
    "采集",
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
        if value:
            value = value.replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """手写解析本项目所需的 key/value 与缩进列表 frontmatter。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized
    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        return {}, normalized
    raw = normalized[4:closing]
    metadata: dict[str, Any] = {}
    current_list = ""
    for line in raw.splitlines():
        list_match = re.match(r"^\s{2,}-\s+(.*)$", line)
        if list_match and current_list:
            metadata.setdefault(current_list, []).append(_unquote(list_match.group(1)))
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            current_list = ""
            continue
        key, value = match.groups()
        if value:
            metadata[key] = _unquote(value)
            current_list = ""
        else:
            metadata[key] = [] if key == "tags" else ""
            current_list = key
    return metadata, normalized[closing + 5 :]


def _old_field(text: str, label: str) -> str:
    match = re.search(rf"^-\s*{re.escape(label)}：\s*(.*)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}[^\n]*\n+(.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _count_from_interactions(interactions: str, label: str) -> str:
    match = re.search(rf"(\d+(?:\.\d+)?\s*[万亿wk]?)\s*{label}", interactions, flags=re.IGNORECASE)
    return match.group(1).replace(" ", "") if match else ""


def parse_capture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        text = handle.read()
    metadata, content_text = parse_frontmatter(text)
    has_frontmatter = bool(metadata)
    title = str(metadata.get("title", "")).strip()
    if not title:
        heading = re.search(r"^#\s+(.+)$", content_text, flags=re.MULTILINE)
        title = heading.group(1).strip() if heading else path.stem

    interactions = _old_field(text, "互动数") if not has_frontmatter else ""
    likes = str(metadata.get("likes", "")).strip() or _count_from_interactions(interactions, "赞")
    favorites = str(metadata.get("favorites", "")).strip() or _count_from_interactions(interactions, "藏")
    comments_count = str(metadata.get("comments", "")).strip() or _count_from_interactions(interactions, "评")
    comment_section = _section(content_text, "评论")
    comment_lines = [line.strip() for line in comment_section.splitlines() if line.strip().startswith("-")][:5]

    return {
        "title": title,
        "author": str(metadata.get("author", "")).strip() or _old_field(text, "作者"),
        "url": str(metadata.get("url", "")).strip() or _old_field(text, "链接"),
        "platform": str(metadata.get("platform", "")).strip() or _old_field(text, "平台"),
        "content_type": str(metadata.get("content_type", "")).strip() or _old_field(text, "内容类型"),
        "likes": likes,
        "favorites": favorites,
        "comments_count": comments_count,
        "tags": metadata.get("tags", []) if isinstance(metadata.get("tags", []), list) else [],
        "body": _section(content_text, "正文"),
        "comments": "\n".join(comment_lines),
    }


def get_existing_categories() -> list[str]:
    categories: set[str] = set()
    for root, dirs, files in os.walk(VAULT_ROOT):
        dirs[:] = [directory for directory in dirs if not directory.startswith(".") and directory not in EXCLUDED_DIRS]
        relative = Path(root).relative_to(VAULT_ROOT)
        if relative == Path("."):
            continue
        if any(filename.endswith(".md") for filename in files):
            category = relative.as_posix()
            categories.add(category)
            parts = category.split("/")
            for index in range(1, len(parts)):
                categories.add("/".join(parts[:index]))
    return sorted(categories)


def build_prompt(item: dict[str, Any], categories: list[str]) -> str:
    categories_text = "，".join(categories[:30])
    body = str(item.get("body", ""))[:2000]
    comments = str(item.get("comments", ""))[:700]
    prompt = f"""你是社媒爆款内容分析师。分析下面这篇采集的社媒内容，产出结构化萃取笔记，返回严格 JSON：
{{"title": "萃取主题（20字内，提炼可复用的规律/结构/方法论，如'清单式博主推荐内容的爆款结构'）",
 "category": "知识库分类路径（/分隔，优先从已有分类中选，匹配不上才新建）",
 "tags": ["标签1", "标签2"],
 "content": "markdown 结构化内容 300-600字，至少包含：## 爆点分析（为什么火）、## 可复用结构（标题/开头/正文/结尾的写法）、## 选题灵感（我可以怎么用）、## 关键信息（数据/事实/清单）",
 "is_worth_extracting": true}}
判断标准：有可复用的结构/方法论/数据/趋势/观点才值得萃取；纯情绪流水、广告、无信息量的返回 is_worth_extracting=false。

【已有分类】{categories_text}
【采集内容】
标题：{item.get('title', '')}
作者：{item.get('author', '')} 互动：{item.get('likes', '')}赞/{item.get('favorites', '')}藏/{item.get('comments_count', '')}评
正文：{body}
评论：{comments}"""
    return prompt[:4000]


def load_state() -> dict[str, float]:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8", newline="\n") as handle:
            raw = json.load(handle)
        return {str(key): float(value) for key, value in raw.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, float]) -> None:
    with STATE_FILE.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def scan_capture_files(keyword: str | None) -> list[Path]:
    root = CAPTURE_ROOT
    if keyword:
        root = CAPTURE_ROOT / keyword
        try:
            root.resolve().relative_to(CAPTURE_ROOT.resolve())
        except ValueError as exc:
            raise ValueError("关键词目录超出采集根目录") from exc
        if not root.is_dir():
            raise FileNotFoundError(f"关键词目录不存在：{root}")
    if not root.exists():
        raise FileNotFoundError(f"采集目录不存在：{root}")
    return sorted(
        path
        for path in root.rglob("*.md")
        if not path.name.startswith("_") and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _worth_extracting(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def normalize_category(value: Any) -> str:
    """模型偶尔返回多个候选分类；只接受第一个明确的分类路径。"""
    category = re.split(r"[,，;；\r\n]+", str(value or ""), maxsplit=1)[0].strip()
    return category.replace("\\", "/").strip(" /")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量萃取 SocialReader 采集内容")
    parser.add_argument("keyword", nargs="?", help="只处理指定关键词目录")
    parser.add_argument("--force", action="store_true", help="忽略增量标记，重新处理全部匹配文件")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        paths = scan_capture_files(args.keyword)
    except (OSError, ValueError) as exc:
        print(f"[失败] {exc}")
        return 2

    state = load_state()
    categories = get_existing_categories()
    today = datetime.now().strftime("%Y-%m-%d")
    created = merged = duplicate_skipped = not_worth = failed = 0

    for path in paths:
        state_key = str(path.resolve())
        mtime = path.stat().st_mtime
        if not args.force and state.get(state_key) == mtime:
            continue
        try:
            item = parse_capture(path)
            result = call_llm(build_prompt(item, categories), max_tokens=3000, temperature=0.3)
            if not isinstance(result, dict):
                raise ValueError("萃取返回值不是 JSON 对象")
            if not _worth_extracting(result.get("is_worth_extracting")):
                not_worth += 1
                state[state_key] = mtime
                save_state(state)
                print(f"[跳过] {path.name}：不值得萃取")
            else:
                title = str(result.get("title", "")).strip()
                category = normalize_category(result.get("category", ""))
                content = str(result.get("content", "")).strip()
                tags = result.get("tags", [])
                if not title or not category or not content:
                    raise ValueError("萃取结果缺少 title/category/content")
                if not isinstance(tags, list):
                    tags = []
                backlink = f"> 原文：[[{path.stem}|{item['title']}]]"
                content_with_link = f"{content}\n\n{backlink}"
                action, output_path, note = save_with_merge(
                    VAULT_ROOT,
                    category,
                    title,
                    content_with_link,
                    [str(tag) for tag in tags],
                    "采集萃取",
                    str(item.get("url", "")),
                    today,
                )
                if action == "failed":
                    raise RuntimeError(note)
                if action == "created":
                    created += 1
                    label = "新建"
                elif action == "merged":
                    merged += 1
                    label = "合并"
                else:
                    duplicate_skipped += 1
                    label = "跳过"
                state[state_key] = mtime
                save_state(state)
                print(f"[{label}] {path.name} -> {output_path}（{note}）")
        except Exception as exc:
            failed += 1
            print(f"[失败] {path.name}：{type(exc).__name__}: {exc}")
        time.sleep(random.uniform(1, 2))

    succeeded = created + merged + duplicate_skipped + not_worth
    extra = f" / 同名跳过 {duplicate_skipped}" if duplicate_skipped else ""
    print(
        f"成功 {succeeded} 篇（新建 {created} / 合并 {merged} / 跳过 {not_worth} 不值得"
        f"{extra}） / 失败 {failed} 条"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
