from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deliverables" / "pre_capture_demo"
OUTPUT = Path(__file__).resolve().parent / "data" / "demo-data.json"


def read_jsonl(name: str) -> list[dict[str, Any]]:
    path = SOURCE / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metrics.get(key)
        for key in ("likes", "favorites", "comments", "shares")
        if metrics.get(key) is not None
    }


def main() -> None:
    cards = read_jsonl("food_cards.jsonl")
    candidates = read_jsonl("candidate_pool_scored.jsonl")
    selected = read_jsonl("selected_candidates.jsonl")
    report = json.loads((SOURCE / "eval_report.json").read_text(encoding="utf-8"))
    run_meta = json.loads((SOURCE / "run_meta.json").read_text(encoding="utf-8"))

    cards_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidates_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        cards_by_query[card["query"]].append(card)
    for item in candidates:
        candidates_by_query[item["query"]].append(item)
    for item in selected:
        selected_by_query[item["query"]].append(item)

    datasets = []
    preferred_order = ["三文鱼波奇饭", "奶茶新品"]
    for query in preferred_order:
        query_cards = cards_by_query.get(query, [])
        if not query_cards:
            continue
        pool = candidates_by_query.get(query, [])
        chosen = selected_by_query.get(query, [])
        evidences = []
        public_cards = []
        for card in query_cards:
            for evidence in card.get("evidences", []):
                evidences.append(
                    {
                        "evidence_id": evidence.get("evidence_id"),
                        "exact_quote": evidence.get("exact_quote"),
                        "evidence_location": evidence.get("evidence_location"),
                        "source_type": evidence.get("source_type"),
                        "aspect": evidence.get("aspect"),
                        "target": evidence.get("target"),
                        "rule_review_status": evidence.get("rule_review_status"),
                        "human_review_status": evidence.get("human_review_status"),
                        "title": card.get("title"),
                        "source_url": card.get("source_url"),
                    }
                )
            public_cards.append(
                {
                    "content_id": card.get("content_id"),
                    "title": card.get("title"),
                    "platform": card.get("platform"),
                    "published_at": card.get("published_at"),
                    "source_url": card.get("source_url"),
                    "metrics": compact_metrics(card.get("metrics", {})),
                    "metric_coverage": card.get("metric_coverage"),
                    "novelty": card.get("novelty", {}).get("label"),
                    "hotness": card.get("hotness", {}).get("label"),
                    "food_items": [
                        {
                            "food_name": food.get("food_name"),
                            "ingredients": food.get("ingredients", []),
                            "textures": food.get("textures", []),
                            "flavors": food.get("flavors", []),
                        }
                        for food in card.get("food_items", [])
                    ],
                }
            )

        candidate_items = [
            {
                "content_id": item.get("content_id"),
                "title": item.get("title"),
                "author": item.get("author"),
                "platform": item.get("platform"),
                "likes": item.get("likes"),
                "published_at": item.get("published_at"),
                "rising_score": item.get("rising_score"),
                "source_url": item.get("source_url"),
            }
            for item in chosen
        ]
        rule_pass = sum(item.get("rule_review_status") == "pass" for item in evidences)
        rule_fail = sum(item.get("rule_review_status") == "fail" for item in evidences)
        datasets.append(
            {
                "query": query,
                "platforms": sorted({card.get("platform") for card in query_cards if card.get("platform")}),
                "source_kind": "real_local_capture",
                "metrics": {
                    "candidate_pool": len(pool) if pool else None,
                    "detail_success": len(query_cards),
                    "evidence_total": len(evidences),
                    "rule_pass": rule_pass,
                    "rule_fail": rule_fail,
                    "selected_candidates": len(chosen) if pool else None,
                    "human_pending": sum(item.get("human_review_status") == "pending" for item in evidences),
                },
                "cards": public_cards,
                "evidences": evidences,
                "candidates": candidate_items,
                "pool_note": (
                    "同平台、同关键词、同一次可见候选池；仅作相对比较。"
                    if pool
                    else "该归档没有完整可见候选池，不能给出热门结论。"
                ),
            }
        )

    contract = report["prompt_contract_ab"]
    output = {
        "generated_from": "deliverables/pre_capture_demo",
        "snapshot_at": run_meta.get("run_at"),
        "run_id": run_meta.get("run_id"),
        "model": run_meta.get("model"),
        "notice": "公开演示读取本地已归档快照，不进行实时抓取。",
        "gold_status": report.get("gold_status"),
        "gold_inventory": report.get("gold_inventory"),
        "datasets": datasets,
        "prompt_contract": {
            "scope": contract.get("dataset_scope"),
            "warning": contract.get("warning"),
            "v0_correct": sum(
                row["prompt_v0_prediction"] == row["expected_useful"] for row in contract.get("cases", [])
            ),
            "v1_correct": sum(
                row["prompt_v1_prediction"] == row["expected_useful"] for row in contract.get("cases", [])
            ),
            "total": len(contract.get("cases", [])),
            "cases": contract.get("cases", []),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
