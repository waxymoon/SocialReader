# -*- coding: utf-8 -*-
"""只读审计 Obsidian 分类，输出建议合并清单，不修改任何笔记。"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from merge_utils import call_llm


VAULT_ROOT = Path(r"D:\ObsidianVault")
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


def _frontmatter_title(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("---\n"):
        closing = normalized.find("\n---\n", 4)
        if closing >= 0:
            raw = normalized[4:closing]
            match = re.search(r"^title:\s*(.*)$", raw, flags=re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                return value.strip()
    return ""


def _note_info(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        text = handle.read()
    title = _frontmatter_title(text)
    if not title:
        heading = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        title = heading.group(1).strip() if heading else path.stem

    body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"[`*_>#|]", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    return title, body[:150]


def scan_categories() -> list[tuple[str, list[tuple[str, str]]]]:
    categories: list[tuple[str, list[tuple[str, str]]]] = []
    for root, dirs, files in os.walk(VAULT_ROOT):
        dirs[:] = [directory for directory in dirs if not directory.startswith(".") and directory not in EXCLUDED_DIRS]
        relative = Path(root).relative_to(VAULT_ROOT)
        if relative == Path("."):
            continue
        note_paths = sorted(Path(root) / filename for filename in files if filename.endswith(".md") and not filename.startswith("."))
        if not 2 <= len(note_paths) <= 40:
            continue
        notes: list[tuple[str, str]] = []
        for path in note_paths:
            try:
                notes.append(_note_info(path))
            except (OSError, UnicodeError):
                continue
        if 2 <= len(notes) <= 40:
            categories.append((relative.as_posix(), notes))
    return sorted(categories, key=lambda item: item[0])


def build_prompt(category: str, notes: list[tuple[str, str]]) -> str:
    listing = "\n".join(
        f"{index}. {title}：{summary}"
        for index, (title, summary) in enumerate(notes, start=1)
    )
    return f"""你是知识库合并审计器。下面是一个分类里的笔记清单（标题+摘要）。找出【内容高度重叠、应该合并成一篇】的笔记对。
【分类】{category}
{listing}
返回严格 JSON：{{"pairs": [{{"a": "标题A", "b": "标题B", "reason": "一句话理由"}}], "checked": {len(notes)}}}
规则：只找高度重叠的（同一主题/内容重复/一篇是另一篇的超集）；只是相关不合并；最多5对；拿不准不列。"""


def _valid_pairs(result: Any, titles: set[str]) -> list[dict[str, str]]:
    if not isinstance(result, dict) or not isinstance(result.get("pairs"), list):
        raise ValueError("审计返回值缺少 pairs 列表")
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in result["pairs"][:5]:
        if not isinstance(raw, dict):
            continue
        a = str(raw.get("a", "")).strip()
        b = str(raw.get("b", "")).strip()
        reason = str(raw.get("reason", "")).strip()
        key = tuple(sorted((a, b)))
        if not a or not b or a == b or a not in titles or b not in titles or key in seen:
            continue
        seen.add(key)
        output.append({"a": a, "b": b, "reason": reason or "内容高度重叠"})
    return output


def write_report(
    report_path: Path,
    categories: list[tuple[str, list[tuple[str, str]]]],
    pairs: list[dict[str, str]],
    failures: list[tuple[str, str]],
) -> None:
    date_text = datetime.now().strftime("%Y-%m-%d")
    total_notes = sum(len(notes) for _, notes in categories)
    lines = [
        f"# 复利体检报告 {date_text}",
        "",
        "> 本报告由 audit_merge.py 生成，看完可删。",
        "",
        f"共检查 {len(categories)} 个分类 {total_notes} 篇笔记，建议合并 {len(pairs)} 组。",
        "",
    ]
    if pairs:
        lines.extend(["## 建议合并", ""])
        for pair in pairs:
            lines.append(
                f"- [ ] **《{pair['a']}》** → 并入 **《{pair['b']}》**"
                f"（分类：{pair['category']}）——{pair['reason']}"
            )
    else:
        lines.extend(["## 未发现重叠", "", "全库未发现需要合并的重复笔记 ✓"])
    if failures:
        lines.extend(["", "## 调用失败", ""])
        lines.extend(f"- {category}：{reason}" for category, reason in failures)
    lines.append("")
    with report_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def main() -> int:
    if not VAULT_ROOT.exists():
        print(f"[失败] 知识库不存在：{VAULT_ROOT}")
        return 2
    categories = scan_categories()
    all_pairs: list[dict[str, str]] = []
    failures: list[tuple[str, str]] = []
    for index, (category, notes) in enumerate(categories, start=1):
        print(f"[{index}/{len(categories)}] 审计 {category}（{len(notes)} 篇）")
        try:
            result = call_llm(build_prompt(category, notes), max_tokens=1500, temperature=0.2)
            for pair in _valid_pairs(result, {title for title, _ in notes}):
                pair["category"] = category
                all_pairs.append(pair)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((category, reason))
            print(f"  [跳过] {reason}")

    report_path = VAULT_ROOT / f"复利体检报告_{datetime.now().strftime('%Y%m%d')}.md"
    try:
        write_report(report_path, categories, all_pairs, failures)
    except OSError as exc:
        print(f"[失败] 无法写入报告：{exc}")
        return 1
    print(f"报告：{report_path}")
    print(f"建议合并 {len(all_pairs)} 组；调用失败 {len(failures)} 个分类")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
