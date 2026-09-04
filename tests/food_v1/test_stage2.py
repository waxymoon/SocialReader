# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from domain_pipeline import CANDIDATE_POOL_FIXTURE, load_config, run_candidate_pool  # noqa: E402
from food_metrics import (  # noqa: E402
    random_baseline,
    read_jsonl,
    score_candidate_pool,
    stratified_sample,
)


class FoodStage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, _ = load_config()
        cls.raw = read_jsonl(CANDIDATE_POOL_FIXTURE)

    def test_scoring_and_selection_are_deterministic(self) -> None:
        first = score_candidate_pool(self.raw, self.config)
        second = score_candidate_pool(self.raw, self.config)
        self.assertEqual(first, second)
        first_selected = stratified_sample(first, self.config)
        second_selected = stratified_sample(second, self.config)
        self.assertEqual(first_selected, second_selected)
        self.assertEqual(random_baseline(first, first_selected), random_baseline(second, second_selected))

    def test_raw_pool_is_saved_before_derived_outputs(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests" / "food_v1") as temp:
            output = Path(temp)
            result = run_candidate_pool(CANDIDATE_POOL_FIXTURE, output)
            self.assertEqual(read_jsonl(output / "candidate_pool_raw.jsonl"), self.raw)
            self.assertEqual(len(read_jsonl(output / "candidate_pool_scored.jsonl")), len(result["scored"]))

    def test_exact_duplicate_is_marked_but_possible_duplicate_is_not_deleted(self) -> None:
        scored = score_candidate_pool(self.raw, self.config)
        duplicates = [row for row in scored if row.get("duplicate_of")]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["duplicate_of"], "fixture_pool_01")
        self.assertEqual(scored[0]["pool_size"], 12)

    def test_metric_missing_is_not_converted_to_zero(self) -> None:
        scored = score_candidate_pool(self.raw, self.config)
        low_info = next(row for row in scored if row["content_id"] == "fixture_pool_12")
        self.assertIsNone(low_info["favorites"])
        self.assertIn("favorites", low_info["metric_missing_fields"])
        self.assertEqual(low_info["metric_coverage"], 0.5)

    def test_selected_group_beats_deterministic_random_baseline(self) -> None:
        scored = score_candidate_pool(self.raw, self.config)
        selected = stratified_sample(scored, self.config)
        baseline = random_baseline(scored, selected, 100)
        self.assertEqual(len(selected), 8)
        self.assertEqual(baseline["status"], "above_baseline")
        self.assertGreater(baseline["lift"], 0)


if __name__ == "__main__":
    unittest.main()
