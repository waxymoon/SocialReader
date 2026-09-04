# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from domain_pipeline import parse_capture_markdown, run_analysis  # noqa: E402
from food_metrics import read_jsonl  # noqa: E402
from pipeline_capture import public_source_url  # noqa: E402


XHS_DIR = Path(r"D:\ObsidianVault\采集\内容流水线\三文鱼波奇饭")
DY_DIR = Path(r"D:\ObsidianVault\采集\内容流水线\奶茶新品")
LIVE_EVIDENCE = ROOT / "artifacts" / "live_verification_20260904.json"


class FoodStage4Tests(unittest.TestCase):
    def test_xhs_real_outputs_are_detail_content_not_login_noise(self) -> None:
        paths = sorted(path for path in XHS_DIR.glob("*.md") if path.name != "_汇总.md")
        self.assertEqual(len(paths), 3)
        for path in paths:
            item = parse_capture_markdown(path)
            self.assertTrue(item["title"])
            self.assertTrue(item["body"])
            noise = "登录后即可搜索更多精彩视频"
            self.assertNotIn(noise, item["title"] + item["body"])
            self.assertIn("xsec_token=", item["source_url"])

    def test_douyin_fresh_details_are_not_page_noise(self) -> None:
        paths = sorted(path for path in DY_DIR.glob("*.md") if path.name != "_汇总.md")
        self.assertEqual(len(paths), 2)
        items = [parse_capture_markdown(path) for path in paths]
        self.assertTrue(all(not item["source_quality_errors"] for item in items))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = run_analysis(items, output_root=Path(temp_dir), run_id="dy_fresh_regression")
            cards = read_jsonl(output_dir / "food_cards.jsonl")
            self.assertTrue(all(not card["errors"] for card in cards))

    def test_fresh_live_capture_and_precaptured_fallback_are_recorded(self) -> None:
        evidence = json.loads(LIVE_EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["xhs"]["success"], 3)
        self.assertEqual(evidence["xhs"]["visible_candidate_pool"]["visible_records"], 27)
        self.assertFalse(evidence["xhs"]["visible_candidate_pool"]["strong_hotness_claim_allowed"])
        self.assertEqual(evidence["dy"]["success"], 2)
        self.assertEqual(evidence["dy"]["source_noise_badcases"], 0)
        self.assertEqual(evidence["dy"]["status"], "verified")
        self.assertTrue((DY_DIR / "_汇总.md").is_file())
        latest = Path(Path(evidence["fallback"]["latest_run_pointer"]).read_text(encoding="utf-8").strip())
        self.assertTrue((latest / "food_cards.jsonl").is_file())

    def test_public_url_sanitizer_keeps_xhs_replay_parameters(self) -> None:
        cleaned = public_source_url("https://example.test/item/1?xsec_token=secret&xsec_source=search&share_token=drop&keep=yes")
        self.assertEqual(cleaned, "https://example.test/item/1?xsec_token=secret&xsec_source=search&keep=yes")


if __name__ == "__main__":
    unittest.main()
