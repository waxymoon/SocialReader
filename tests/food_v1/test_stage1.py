# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from domain_pipeline import (  # noqa: E402
    ACCEPTANCE_FIXTURES,
    load_config,
    parse_capture_markdown,
    run_analysis,
)
from food_metrics import read_jsonl  # noqa: E402


REAL_SAMPLE_DIR = Path(r"D:\ObsidianVault\采集\内容流水线\三文鱼波奇饭")


class FoodStage1Tests(unittest.TestCase):
    def test_real_samples_keep_replayable_xhs_link(self) -> None:
        files = sorted(path for path in REAL_SAMPLE_DIR.glob("*.md") if path.name != "_汇总.md")
        self.assertGreaterEqual(len(files), 3)
        items = [parse_capture_markdown(path) for path in files[:3]]
        self.assertTrue(all(item["source_kind"] == "real_local_capture" for item in items))
        self.assertTrue(all("xsec_token=" in item["source_url"] for item in items))
        self.assertTrue(all(item["content_id"] for item in items))

    def test_taskbook_acceptance_boundaries_and_traceability(self) -> None:
        fixtures = [json.loads(line) for line in ACCEPTANCE_FIXTURES.read_text(encoding="utf-8").splitlines() if line.strip()]
        with tempfile.TemporaryDirectory(dir=ROOT / "tests" / "food_v1") as temp:
            output_dir = run_analysis(fixtures, Path(temp))
            expressions = read_jsonl(output_dir / "vivid_expressions.jsonl")
            by_quote = {item["exact_quote"]: item for item in expressions}
            self.assertEqual(by_quote["虾究极 Q 弹"]["rule_review_status"], "pass")
            self.assertEqual(by_quote["虾究极 Q 弹"]["human_review_status"], "approved")
            self.assertEqual(by_quote["拜见三文鱼波奇饭大王"]["rule_review_status"], "pass")
            self.assertEqual(by_quote["求地址"]["rule_review_status"], "fail")
            self.assertEqual(by_quote["好吃绝了"]["rule_review_status"], "fail")
            self.assertEqual(by_quote["吃完瘦三斤"]["rule_review_status"], "fail")
            self.assertTrue(all(item["exact_quote"] in item["source_excerpt"] for item in expressions))
            cards = read_jsonl(output_dir / "food_cards.jsonl")
            self.assertTrue(all(not card["errors"] for card in cards))

    def test_manifest_versions_are_present(self) -> None:
        manifest, keywords = load_config()
        self.assertEqual(manifest["schema_version"], "food_v1")
        self.assertEqual(manifest["date_window_days"], 45)
        self.assertIn("三文鱼波奇饭", keywords["categories"])


if __name__ == "__main__":
    unittest.main()
