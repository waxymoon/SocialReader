# -*- coding: utf-8 -*-
"""② 语义评估器：DeepSeek 逐句判断"活人感表达"（2026-09-07 妹妹拍板）。

为什么：规则词库对口语变形/梗/错字不宽容（"吃瘦36斤""汤汁拌饭绝绝子"无 food
target 就被毙）——但社媒的活人感恰恰藏在这些语言变形里。让模型语义判断：
- 错字/谐音/故意口癖是活人感的一部分，不因拼写扣分
- target（食品对象）认不出就标 unknown，不因此毙句
- 判断"像不像真实用户会说的话"，不是判断文案优美度

用法：semantic_review_cards(cards) -> {evidence_id: {"pass": bool, "reason": str}}
只审 rule fail 且非人工驳回的句子（规则 pass 保留，省 token）；按内容分批调用。
标注口径：模型通过 ≠ 人工通过，导出/页面标注"语义通过·待人工终审"。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ENV_FILE = Path(r"D:\Hermes-Agent\.env")
DS_API_URL = "https://api.deepseek.com/chat/completions"
DS_MODEL = "deepseek-v4-flash"
DS_FALLBACK = "deepseek-chat"

SEMANTIC_SYSTEM = """你是社媒美食内容的"活人感"判断器。给你一批从真实帖子/评论/视频口播里抽出的句子，
逐句判断：这句话像不像真实用户吃过后会说的话（口语化、有细节、有情绪、像真人分享）？

判定要点：
1. 错字、谐音、故意口癖（如"绝绝子""泰裤辣""好好次"）是活人感的一部分，绝不因拼写扣分。
2. 认不出具体食品（无食品名）不扣分——很多人夸的是口感/氛围/体验。
3. 广告腔、官方文案、空泛夸奖（"很好吃""推荐"）不算活人感。
4. 疑问句、求助（"求地址""多少钱"）不算夸赞型活人感，但真实生活化提问可标 living_voice=false + reason 说明。

只输出一个 JSON 对象：{"sentences": [{"sentence": "原文", "living_voice": true/false, "reason": "一句话理由"}]}
必须逐条对应输入，条数一致，不要漏句或改写原文。"""


def _load_key() -> str:
    value = os.environ.get("DEEPSEEK_API_KEY", "")
    if value:
        return value.strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DEEPSEEK_API_KEY 未配置")


def _batch_review(quotes: list[str]) -> dict[str, Any]:
    """一批句子调 DS 返回 {quote: verdict}。失败返回 {}（降级=该批不判，规则兜底）。"""
    if not quotes:
        return {}
    key = _load_key()
    user = "请判断以下句子（每句一行，按序号返回）：\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(quotes))
    messages = [
        {"role": "system", "content": SEMANTIC_SYSTEM},
        {"role": "user", "content": user},
    ]
    last_err: Exception | None = None
    for model in (DS_MODEL, DS_MODEL, DS_FALLBACK):
        for attempt in range(2):
            payload = json.dumps({
                "model": model, "messages": messages, "temperature": 0.1,
                "max_tokens": 2000, "response_format": {"type": "json_object"},
            }).encode("utf-8")
            try:
                req = urllib.request.Request(
                    DS_API_URL, data=payload,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    content = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("空 content")
                cleaned = re.sub(r"^```json\s*", "", content.strip())
                cleaned = re.sub(r"\s*```$", "", cleaned)
                obj = json.loads(cleaned)
                sentences = obj.get("sentences") if isinstance(obj, dict) else None
                if not isinstance(sentences, list):
                    raise ValueError("缺 sentences 数组")
                out: dict[str, Any] = {}
                for item in sentences:
                    if isinstance(item, dict) and item.get("sentence"):
                        out[str(item["sentence"]).strip()] = {
                            "pass": bool(item.get("living_voice")),
                            "reason": str(item.get("reason") or "")[:120],
                        }
                if out:
                    return out
                raise ValueError("无有效条目")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(min(2**attempt, 8))
    print(f"[语义评估] 一批 {len(quotes)} 句失败：{last_err}", file=sys.stderr)
    return {}


def semantic_review_cards(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """遍历卡片的 evidences：对 rule fail 且非人工驳回的句子做语义判断。

    返回 {evidence_id: {"model_pass": bool, "model_reason": str}}。规则 pass 的不审。
    """
    verdicts: dict[str, dict[str, Any]] = {}
    for card in cards:
        targets = [
            e for e in card.get("evidences") or []
            if e.get("rule_review_status") == "fail"
            and e.get("human_review_status") not in ("approved", "rejected")
            and "model_review" not in e  # 幂等：已语义评估过的跳过
        ]
        if not targets:
            continue
        quotes = [str(e.get("exact_quote") or "").strip() for e in targets]
        # 按 12 句一批
        for i in range(0, len(quotes), 12):
            chunk = quotes[i:i + 12]
            result = _batch_review(chunk)
            if not result:
                continue
            for e, q in zip(targets[i:i + 12], chunk):
                verdict = result.get(q)
                if verdict:
                    verdicts[str(e.get("evidence_id"))] = {
                        "model_pass": verdict["pass"],
                        "model_reason": verdict["reason"],
                    }
    return verdicts


def apply_semantic_to_run(run_dir) -> dict[str, Any]:
    """对指定 run 做②语义评估并持久化写回（页面 reasons 页签与 excel 导出口径一致）。

    1. 只评 rule-fail 且无人工裁决、且尚未有 model_review 的证据（幂等，重复调用不重评）
    2. 通过句写进 evidence.model_review + 重写 food_cards/vivid/review/recommendation_reasons
    3. 返回 {reviewed, passed, failed}
    """
    from domain_pipeline import build_reasons  # noqa: PLC0415
    from food_metrics import read_jsonl, write_jsonl  # noqa: PLC0415

    cards = read_jsonl(run_dir / "food_cards.jsonl")
    if not cards:
        return {"reviewed": 0, "passed": 0, "failed": 0}
    # 收集待审句（幂等：已有 model_review 的跳过）
    pending: list[tuple[Any, str]] = []  # (evidence, evidence_id)
    for card in cards:
        for e in card.get("evidences", []):
            if e.get("rule_review_status") == "fail" \
               and e.get("human_review_status") not in ("approved", "rejected") \
               and "model_review" not in e:
                pending.append((e, str(e.get("evidence_id") or "")))
    if not pending:
        return {"reviewed": 0, "passed": 0, "failed": 0, "note": "无可评句（已评过或无需评）"}
    # 按卡分批：先按 evidence 归属卡分组
    by_card: dict[str, list[Any]] = {}
    for card in cards:
        cid = str(card.get("content_id") or "")
        by_card[cid] = [e for e in card.get("evidences", [])
                        if e.get("rule_review_status") == "fail"
                        and e.get("human_review_status") not in ("approved", "rejected")
                        and "model_review" not in e]
    reviewed = passed = failed = 0
    for cid, evs in by_card.items():
        if not evs:
            continue
        quotes = [str(e.get("exact_quote") or "").strip() for e in evs]
        result = _batch_review(quotes)
        if not result:
            continue
        for e, q in zip(evs, quotes):
            verdict = result.get(q)
            if not verdict:
                continue
            e["model_review"] = {"pass": bool(verdict["pass"]), "reason": str(verdict.get("reason") or "")[:120]}
            reviewed += 1
            if verdict["pass"]:
                passed += 1
            else:
                failed += 1
    # 写回
    write_jsonl(run_dir / "food_cards.jsonl", cards)
    write_jsonl(run_dir / "vivid_expressions.jsonl", [e for c in cards for e in c.get("evidences", [])])
    write_jsonl(run_dir / "review_results.jsonl", [
        {k: e.get(k) for k in ("evidence_id", "content_id", "exact_quote", "rule_review_status",
                               "human_review_status", "review_reason", "risk_flags", "model_review")}
        for c in cards for e in c.get("evidences", [])])
    write_jsonl(run_dir / "recommendation_reasons.jsonl", build_reasons(cards))
    return {"reviewed": reviewed, "passed": passed, "failed": failed}


if __name__ == "__main__":
    # 自测：几类典型句子
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    samples = [
        "吃瘦36斤，带薪减肥打工人必备",
        "汤汁拌饭绝绝子",
        "求地址，多少钱一份",
        "这家店环境优美，服务周到，欢迎光临",
        "拜见三文鱼波奇饭大王",
        "好次到跺脚，一周吃三次",
    ]
    for i in range(0, len(samples), 12):
        r = _batch_review(samples[i:i + 12])
        for s in samples[i:i + 12]:
            v = r.get(s)
            print(("PASS" if v and v["pass"] else "----"), "|", s[:30], "|", (v or {}).get("reason", "未返回")[:40])
