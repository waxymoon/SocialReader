# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval_food import build_eval_report  # noqa: E402


class FoodStage3Tests(unittest.TestCase):
    def test_incomplete_human_gold_never_emits_production_accuracy(self) -> None:
        report = build_eval_report()
        self.assertEqual(report["gold_status"], "insufficient_human_gold")
        self.assertIsNone(report["production_metrics"])
        self.assertEqual(report["gold_inventory"]["total_real_cases"], 5)
        self.assertEqual(report["gold_inventory"]["platform_counts"], {"xhs": 3, "dy": 2})
        self.assertEqual(report["gold_inventory"]["approved_gold_cases"], 0)

    def test_prompt_contract_uses_one_dataset_and_keeps_badcases(self) -> None:
        report = build_eval_report()
        ab = report["prompt_contract_ab"]
        self.assertFalse(ab["is_real_public_gold"])
        self.assertGreater(len(ab["cases"]), 0)
        self.assertGreater(len(ab["prompt_v0"]["badcases"]), 0)
        self.assertEqual(ab["prompt_v1"]["exact_quote_traceability"], 1.0)
        self.assertEqual(ab["prompt_v1"]["badcases"], [])


if __name__ == "__main__":
    unittest.main()
