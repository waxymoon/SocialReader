# -*- coding: utf-8 -*-
"""SocialReader 独立的 GLM 调用与知识库复利融合工具。"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODELS = ["glm-4.5-air", "glm-4.7-flash"]
ENV_FILE = Path(r"D:\Hermes-Agent\.env")


def _load_env_key(name: str) -> str:
    """环境变量优先，Hermes-Agent 的 .env 文件兜底。"""
    value = os.environ.get(name, "")
    if value:
        return value
    if ENV_FILE.exists():
        with ENV_FILE.open("r", encoding="utf-8", newline="\n") as handle:
            for line in handle:
                if line.startswith(name + "="):
                    return line.strip().split("=", 1)[1].strip('"').strip("'")
    return ""


GLM_API_KEY = _load_env_key("GLM_API_KEY")


def call_llm(
    prompt: str,
    system: str = "你是一个知识管理助手。你的输出必须是严格的JSON格式，不要包含任何markdown标记或其他文本。",
    max_tokens: int = 3000,
    temperature: float = 0.3,
    retries: int = 8,
) -> Any:
    """调用 GLM，按模型依次兜底并返回解析后的 JSON。"""
    if not GLM_API_KEY:
        raise RuntimeError("GLM_API_KEY 未配置")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    last_err: Exception | None = None
    for model in GLM_MODELS:
        for attempt in range(retries):
            try:
                data = json.dumps(
                    {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    GLM_API_URL,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + GLM_API_KEY,
                    },
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    content = json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code == 429 and attempt < retries - 1:
                    time.sleep(min(2**attempt, 30) + random.uniform(0, 5))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
                last_err = exc
                if attempt < retries - 1:
                    time.sleep(min(2**attempt, 15) + random.uniform(0, 2))
                    continue
                break

            cleaned = content.strip()
            cleaned = re.sub(r"^```json\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                if attempt < retries - 1:
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "你的输出不是完整的JSON（可能被截断）。请只输出一个完整、合法的JSON对象，不要省略任何字段，不要截断。",
                        }
                    )
                    continue
                last_err = ValueError("JSON 解析失败: " + content[:80])
                break
    raise RuntimeError(f"所有模型均失败: {GLM_MODELS}, last_err={last_err}")


def check_merge(info: dict[str, Any], candidates: list[dict[str, str]], max_tokens: int = 1500) -> dict[str, Any]:
    """判断新笔记是否与同分类已有笔记高度重叠。"""
    if not candidates:
        return {"should_merge": False, "target": "", "new_points": [], "reason": "无候选"}
    points = "\n".join("- " + str(point) for point in (info.get("key_points") or [])[:8])
    candidate_list = "\n".join(
        f"- {candidate.get('title', '')}：{candidate.get('preview', '')[:150]}"
        for candidate in candidates[:15]
    )
    prompt = f"""你是一个知识库融合判断器。判断下面这篇【新笔记】是否应该【合并进】某篇已有笔记，而不是单独新建一篇。

【新笔记】
标题：{info.get('title', '')}
分类：{info.get('category', '')}
摘要：{info.get('summary', '')}
要点：
{points or '（无）'}

【同分类已有笔记】
{candidate_list or '（无）'}

判断规则：
1. 仅当新笔记与某篇已有笔记【高度重叠】时才算 should_merge=true——同一主题、内容大部分重复（如同一工具/概念的新进展、同一话题的补充信息）
2. 只是相关但主题不同、或不确定，一律 should_merge=false（宁可新建，不要乱合并）
3. new_points 只列旧笔记里【没有】的、真实有价值的新信息要点（最多5条）
4. target 必须是上面列表中的准确标题

返回严格JSON：
{{"should_merge": true 或 false, "target": "目标笔记标题", "new_points": ["要点"], "reason": "一句话理由"}}"""
    result = call_llm(prompt, max_tokens=max_tokens, temperature=0.2)
    if not isinstance(result, dict):
        return {"should_merge": False, "target": "", "new_points": [], "reason": "返回格式异常"}
    return {
        "should_merge": bool(result.get("should_merge")),
        "target": str(result.get("target", "")).strip(),
        "new_points": [str(item) for item in (result.get("new_points") or [])][:5],
        "reason": str(result.get("reason", "")),
    }


def _yaml_scalar(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return '""'
    needs_quotes = (
        bool(re.search(r'["\']|:\s|\s#', text))
        or text[0] in "-?:,[]{}#&*!|>@`"
        or text.lower() in {"null", "true", "false", "yes", "no", "on", "off"}
    )
    if not needs_quotes:
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _category_directory(vault_root: Path, category: str) -> Path:
    parts = [part.strip() for part in str(category).replace("\\", "/").split("/") if part.strip()]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("分类路径无效")
    if any(part.lower() == "airp" for part in parts):
        raise ValueError("禁止写入 airp 目录")
    root = vault_root.resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise ValueError("分类路径超出知识库根目录")
    return target


def _content_points(content: str) -> list[str]:
    points = []
    for line in content.splitlines():
        cleaned = re.sub(r"^[-*#>\d.、\s]+", "", line).strip()
        if cleaned and len(cleaned) >= 6:
            points.append(cleaned[:200])
        if len(points) >= 8:
            break
    return points


def save_with_merge(
    vault_root: str | Path,
    category: str,
    title: str,
    content: str,
    tags: list[str],
    source_label: str,
    source_url: str,
    today_str: str,
) -> tuple[str, Path | None, str]:
    """按复利规则合并或新建笔记；所有异常均转成 failed 返回值。"""
    try:
        root = Path(vault_root)
        target_dir = _category_directory(root, category)
        os.makedirs(target_dir, exist_ok=True)

        safe_title = re.sub(r'[\\/:*?"<>|]', "-", str(title)).strip(" .") or "未命名"
        new_path = target_dir / f"{safe_title}.md"
        if new_path.exists():
            return "skipped", new_path, "同名已存在，跳过"

        candidates: list[dict[str, str]] = []
        candidate_paths: dict[str, Path] = {}
        for path in sorted(target_dir.glob("*.md"), key=lambda item: item.name)[:15]:
            try:
                with path.open("r", encoding="utf-8", newline="\n") as handle:
                    preview = handle.read(600)
            except (OSError, UnicodeError):
                continue
            candidates.append({"title": path.stem, "preview": preview})
            candidate_paths[path.stem] = path

        info = {
            "title": str(title).strip(),
            "category": str(category).strip(),
            "summary": str(content).strip()[:600],
            "key_points": _content_points(str(content)),
        }
        decision = check_merge(info, candidates)
        if decision.get("should_merge"):
            target_title = str(decision.get("target", "")).strip()
            target_path = candidate_paths.get(target_title)
            if target_path is None:
                return "failed", None, f"融合目标不在候选列表：{target_title}"
            new_points = [str(item).strip() for item in decision.get("new_points", []) if str(item).strip()]
            if new_points:
                addition = "\n".join(f"- {re.sub(r'^[-*]\s*', '', item)}" for item in new_points)
            else:
                addition = str(content).strip()
            block = (
                f"\n\n## 🔄 补充更新（{today_str}）\n"
                f"> 来源：{source_label}「{title}」\n"
                f"> 原文：{source_url}\n\n"
                f"{addition}\n"
            )
            with target_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(block)
            note = str(decision.get("reason", "")).strip() or "高度重叠，已追加补充更新"
            return "merged", target_path, note

        frontmatter = [
            "---",
            f"title: {_yaml_scalar(title)}",
            f"category: {_yaml_scalar(category)}",
        ]
        clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if clean_tags:
            frontmatter.append("tags:")
            frontmatter.extend(f"  - {_yaml_scalar(tag)}" for tag in clean_tags)
        frontmatter.extend(
            [
                "source: 采集萃取",
                f"source_url: {_yaml_scalar(source_url)}",
                f"date: {_yaml_scalar(today_str)}",
                "---",
                "",
                f"# {str(title).strip()}",
                "",
                str(content).strip(),
                "",
            ]
        )
        with new_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(frontmatter))
        note = str(decision.get("reason", "")).strip() or "未发现高度重叠笔记"
        return "created", new_path, note
    except Exception as exc:  # 调用方需要继续批处理
        return "failed", None, f"{type(exc).__name__}: {exc}"
