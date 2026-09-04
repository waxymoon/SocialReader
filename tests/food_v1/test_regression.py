# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from extract_capture import parse_capture  # noqa: E402
from pipeline_capture import Capture, format_markdown  # noqa: E402


OLD_SAMPLES = (
    Path(r"D:\ObsidianVault\采集\内容流水线\AI工具\20260826_小红书_AI工具_01.md"),
    Path(r"D:\ObsidianVault\采集\内容流水线\AI工具\20260826_小红书_AI工具_02.md"),
    Path(r"D:\ObsidianVault\采集\内容流水线\AI工具\20260826_小红书_AI工具_03.md"),
)


class GeneralCaptureRegressionTests(unittest.TestCase):
    def test_three_old_general_samples_still_parse(self) -> None:
        for path in OLD_SAMPLES:
            item = parse_capture(path)
            self.assertTrue(item["title"], path.name)
            self.assertTrue(item["body"], path.name)
            self.assertTrue(item["platform"], path.name)

    def test_general_formatter_keeps_non_food_content(self) -> None:
        output = format_markdown(
            Capture(title="通用内容样例", author="测试", body="这是一条不含美食字段的通用采集内容。", interactions="1赞 / 2藏 / 3评 / 4分享", content_type="图文"),
            "xhs",
            "https://www.xiaohongshu.com/explore/general?xsec_token=redacted",
        )
        self.assertIn("# 通用内容样例", output)
        self.assertIn("这是一条不含美食字段的通用采集内容。", output)
        self.assertIn("xsec_token=redacted", output)


if __name__ == "__main__":
    unittest.main()
