# -*- coding: utf-8 -*-
"""人工审核跨 run 继承（2026-09-07 修复：重新分析不丢标注）回归测试。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_metrics import read_jsonl, write_jsonl
from domain_pipeline import build_reasons, inherit_human_reviews


def _card(content_id: str, evidence_statuses: list[tuple[str, str, str]]) -> dict:
    """evidence_statuses: (evidence_id, rule_review_status, human_review_status)"""
    evidences = []
    for eid, rule, human in evidence_statuses:
        evidences.append({
            "evidence_id": eid, "content_id": content_id, "exact_quote": f"quote {eid}",
            "source_type": "body", "evidence_location": "paragraph_1", "aspect": "口感",
            "target": "炸鸡", "normalized_attribute": "酥脆",
            "expression_style": ["口语"], "human_like_scores": {"food_relevance": 2, "specificity": 1,
            "sensory_richness": 1, "colloquiality": 1, "memorability": 1, "recommendation_usability": 1},
            "human_review_status": human, "rule_review_status": rule, "review_reason": "", "risk_flags": [],
        })
    return {"content_id": content_id, "schema_version": "food_v1", "platform": "xhs",
            "source_url": f"https://www.xiaohongshu.com/explore/{content_id}", "published_at": None,
            "query": "炸鸡", "title": "t", "prompt_version": "prompt_v1",
            "food_items": [], "novelty": {"label": "unknown", "evidence_ids": [], "rule_version": "v1"},
            "hotness": {"label": "insufficient_evidence", "pool_size": 1, "engagement_percentile": None,
                        "metric_coverage": 0, "rule_version": "v1"},
            "evidences": evidences, "errors": [], "metrics": {}}


class ReviewInheritTests(unittest.TestCase):
    def _write_run(self, run_root: Path, run_name: str, cards: list[dict]) -> Path:
        out = run_root / "2026-09-07" / run_name
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(out / "food_cards.jsonl", cards)
        write_jsonl(out / "vivid_expressions.jsonl", [e for c in cards for e in c.get("evidences", [])])
        write_jsonl(out / "review_results.jsonl", [
            {key: e.get(key) for key in ("evidence_id", "content_id", "exact_quote", "rule_review_status",
                                          "human_review_status", "review_reason", "risk_flags")}
            for c in cards for e in c.get("evidences", [])
        ])
        write_jsonl(out / "recommendation_reasons.jsonl", build_reasons(cards))
        return out

    def test_approved_and_rejected_inherit_into_new_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 旧 run：人工 approved 一条 rule-fail 证据 + rejected 一条
            old_cards = [_card("xhs_abc", [
                ("ev_xhs_abc_001", "fail", "approved"),
                ("ev_xhs_abc_002", "pass", "rejected"),
            ])]
            self._write_run(root, "run_old", old_cards)
            # 新 run：同证据全 pending（重新分析后丢失标注的场景）
            new_cards = [_card("xhs_abc", [
                ("ev_xhs_abc_001", "fail", "pending"),
                ("ev_xhs_abc_002", "pass", "pending"),
            ])]
            new_dir = self._write_run(root, "run_new", new_cards)

            counts = inherit_human_reviews(new_dir, run_root=root)
            self.assertEqual(counts["approved"], 1)
            self.assertEqual(counts["rejected"], 1)

            merged = read_jsonl(new_dir / "food_cards.jsonl")
            statuses = {e["evidence_id"]: e["human_review_status"] for e in merged[0]["evidences"]}
            self.assertEqual(statuses["ev_xhs_abc_001"], "approved")  # 人工终审覆盖规则 fail
            self.assertEqual(statuses["ev_xhs_abc_002"], "rejected")
            # 理由同步重建：approved(fail句) 应出理由
            reasons = read_jsonl(new_dir / "recommendation_reasons.jsonl")
            ids = [r["evidence_ids"][0] for r in reasons]
            self.assertIn("ev_xhs_abc_001", ids)
            self.assertNotIn("ev_xhs_abc_002", ids)

    def test_new_run_local_review_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_cards = [_card("xhs_abc", [("ev_xhs_abc_001", "fail", "rejected")])]
            self._write_run(root, "run_old", old_cards)
            new_cards = [_card("xhs_abc", [("ev_xhs_abc_001", "fail", "approved")])]  # 本 run 刚标过
            new_dir = self._write_run(root, "run_new", new_cards)
            inherit_human_reviews(new_dir, run_root=root)
            merged = read_jsonl(new_dir / "food_cards.jsonl")
            self.assertEqual(merged[0]["evidences"][0]["human_review_status"], "approved")

    def test_no_history_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_cards = [_card("xhs_abc", [("ev_xhs_abc_001", "pass", "pending")])]
            new_dir = self._write_run(root, "run_only", new_cards)
            counts = inherit_human_reviews(new_dir, run_root=root)
            self.assertEqual(counts, {"approved": 0, "rejected": 0})


if __name__ == "__main__":
    unittest.main()
