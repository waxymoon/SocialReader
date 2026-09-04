# -*- coding: utf-8 -*-
"""food_v1 评测：严格区分任务书契约夹具、待标数据和人工金标准。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from domain_pipeline import ACCEPTANCE_FIXTURES, DOMAIN_ROOT, extract_item, load_config
from food_metrics import read_jsonl


GOLD_PATH = DOMAIN_ROOT / "evals" / "gold_cases_v1.jsonl"


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def gold_inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    approved = [row for row in rows if row.get("annotation_status") == "approved_gold"]
    sentences = [sentence for row in approved for sentence in row.get("sentences", [])]
    secondary = [row for row in approved if row.get("secondary_annotator")]
    platform_counts = {platform: sum(row.get("platform") == platform for row in rows) for platform in ("xhs", "dy")}
    categories = sorted({str(row.get("category")) for row in rows if row.get("category")})
    return {
        "total_real_cases": len([row for row in rows if row.get("source_kind") == "real_local_capture"]),
        "approved_gold_cases": len(approved),
        "approved_gold_sentences": len(sentences),
        "platform_counts": platform_counts,
        "categories": categories,
        "secondary_annotation_cases": len(secondary),
        "secondary_coverage": ratio(len(secondary), len(approved)),
        "requirements": {"cases": 24, "sentences": 60, "xhs": 12, "dy": 12, "categories": 5, "secondary_coverage": 0.2},
    }


def _v0_accept(quote: str) -> bool:
    """代表现有通用爆款萃取的宽松契约基线，不伪装成真实模型输出。"""
    compact = quote.replace(" ", "")
    return bool(compact) and not compact.startswith("求") and any(term in compact for term in ("好吃", "绝", "不错", "Q弹", "大王", "清爽", "瘦"))


def contract_ab() -> dict[str, Any]:
    manifest, _ = load_config()
    fixtures = read_jsonl(ACCEPTANCE_FIXTURES)
    cases: list[dict[str, Any]] = []
    for fixture in fixtures:
        card = extract_item(fixture, manifest)
        by_quote = {evidence["exact_quote"]: evidence for evidence in card["evidences"]}
        for quote, expected_status in fixture.get("expected_reviews", {}).items():
            evidence = by_quote[quote]
            expected = expected_status == "approved"
            cases.append({
                "content_id": fixture["content_id"],
                "exact_quote": quote,
                "expected_useful": expected,
                "prompt_v0_prediction": _v0_accept(quote),
                "prompt_v1_prediction": evidence["rule_review_status"] == "pass",
                "traceable": quote in evidence["source_excerpt"],
                "v1_reason": evidence["review_reason"],
            })

    def metrics(version: str) -> dict[str, Any]:
        prediction_key = f"{version}_prediction"
        accepted = [case for case in cases if case[prediction_key]]
        false_accepts = [case for case in accepted if not case["expected_useful"]]
        correct = [case for case in cases if case[prediction_key] == case["expected_useful"]]
        return {
            "accuracy": ratio(len(correct), len(cases)),
            "expression_precision": ratio(sum(case["expected_useful"] for case in accepted), len(accepted)),
            "generic_noise_false_accept": ratio(len(false_accepts), sum(not case["expected_useful"] for case in cases)),
            "exact_quote_traceability": ratio(sum(case["traceable"] for case in cases), len(cases)),
            "accepted": len(accepted),
            "badcases": [case for case in cases if case[prediction_key] != case["expected_useful"]],
        }
    return {
        "dataset_scope": "taskbook_acceptance_fixture_only",
        "is_real_public_gold": False,
        "warning": "仅用于规则契约回归，不能作为24篇真实公开内容金标准或真实模型准确率。",
        "run_config": {"model": "none_contract_rules", "temperature": None, "input_truncation": None, "prompt_versions": ["prompt_v0_contract", "prompt_v1_rules"]},
        "cases": cases,
        "prompt_v0": metrics("prompt_v0"),
        "prompt_v1": metrics("prompt_v1"),
    }


def build_eval_report() -> dict[str, Any]:
    inventory = gold_inventory(read_jsonl(GOLD_PATH))
    requirements = inventory["requirements"]
    ready = (
        inventory["approved_gold_cases"] >= requirements["cases"]
        and inventory["approved_gold_sentences"] >= requirements["sentences"]
        and inventory["platform_counts"]["xhs"] >= requirements["xhs"]
        and inventory["platform_counts"]["dy"] >= requirements["dy"]
        and len(inventory["categories"]) >= requirements["categories"]
        and (inventory["secondary_coverage"] or 0) >= requirements["secondary_coverage"]
    )
    return {
        "gold_status": "ready" if ready else "insufficient_human_gold",
        "gold_inventory": inventory,
        "production_metrics": None if not ready else {},
        "prompt_contract_ab": contract_ab(),
        "manual_spot_check_10": "not_run_requires_human",
    }


def report_markdown(report: dict[str, Any]) -> str:
    inv = report["gold_inventory"]
    ab = report["prompt_contract_ab"]
    return "\n".join([
        "# food_v1 评测报告",
        "",
        f"> 金标准状态：`{report['gold_status']}`。未达到人工标注规模前不计算或展示真实准确率。",
        "",
        "## 金标准库存",
        "",
        f"- 真实内容：{inv['total_real_cases']}/24",
        f"- 已人工确认金标准：{inv['approved_gold_cases']}/24",
        f"- 已人工标注句子：{inv['approved_gold_sentences']}/60",
        f"- 平台：小红书 {inv['platform_counts']['xhs']}/12；抖音 {inv['platform_counts']['dy']}/12",
        f"- 品类：{len(inv['categories'])}/5（{', '.join(inv['categories']) or '无'}）",
        f"- 第二标注覆盖：{inv['secondary_coverage'] if inv['secondary_coverage'] is not None else '无可计算样本'}",
        "",
        "## Prompt 契约回归（不是生产准确率）",
        "",
        f"- 数据范围：{ab['dataset_scope']}；真实公开金标准：否",
        f"- prompt_v0 契约准确率：{ab['prompt_v0']['accuracy']}；Badcase {len(ab['prompt_v0']['badcases'])} 条",
        f"- prompt_v1 规则准确率：{ab['prompt_v1']['accuracy']}；Badcase {len(ab['prompt_v1']['badcases'])} 条",
        f"- prompt_v1 原句回溯：{ab['prompt_v1']['exact_quote_traceability']}",
        "",
        "## 未完成项",
        "",
        "- 还需人工确认至少 24 篇真实公开内容和 60 个句子。",
        "- 还需另一位标注人独立覆盖至少 20%。",
        "- 没有授权读取模型密钥，本轮没有调用 GLM，因此不报告模型准确率、耗时或成本。",
        "- 随机抽 10 条人工复查尚未执行。",
        "",
        "## 契约 Badcase",
        "",
        *(f"- prompt_v0：‘{case['exact_quote']}’ 预测={case['prompt_v0_prediction']}，期望={case['expected_useful']}" for case in ab["prompt_v0"]["badcases"]),
        *(f"- prompt_v1：‘{case['exact_quote']}’ 预测={case['prompt_v1_prediction']}，期望={case['expected_useful']}" for case in ab["prompt_v1"]["badcases"]),
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="food_v1 评测")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    report = build_eval_report()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (args.output_dir / "eval_report.md").write_text(report_markdown(report), encoding="utf-8", newline="\n")
    print(json.dumps({"gold_status": report["gold_status"], "gold_inventory": report["gold_inventory"], "contract_v1": report["prompt_contract_ab"]["prompt_v1"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
