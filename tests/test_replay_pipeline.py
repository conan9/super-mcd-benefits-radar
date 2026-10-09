"""端到端回放：用**四个响应样例**跑通完整链路。

这是最重要的一个测试文件。它回答的问题是：

    「官方 MCP 返回的数据，能不能一步不落地走完
      解析 → 归一化 → 紧急度评分 → 排序 → 报告？」

而不是"大模型读完工具输出直接总结"。

仓库自带的 ``fixtures/`` 是**结构逐行对标 2026-10-09 真实调用、取值全部合成**
的样例（真实响应含账户数据，不随公开仓库分发），因此本文件可完全离线复现。
把新采集的真实返回放进同一个回放目录，即可用同一套断言复核线上数据。
"""

from __future__ import annotations

import re
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import support

from normalize import PayloadState, build_bundle
from radar import Level, build_radar
from report import render_report, summarize

TODAY = date(2026, 10, 9)

#: 四个工具各自真实返回的格式（由程序判定，不是人工声称）
EXPECTED_FORMATS = {
    "query-my-coupons": "markdown",
    "query-my-account": "json（内嵌于说明文本）",
    "available-coupons": "markdown",
    "campaign-calendar": "markdown",
}


class TestFourToolsEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        cls.radar = build_radar(
            cls.bundle.my_coupons,
            cls.bundle.available_coupons,
            cls.bundle.campaigns,
            cls.bundle.account,
            TODAY,
        )
        cls.report = render_report(cls.bundle, cls.radar)

    def test_all_four_sources_parsed(self) -> None:
        self.assertEqual(len(self.bundle.sources), 4)
        for status in self.bundle.sources:
            with self.subTest(tool=status.tool):
                self.assertIs(status.state, PayloadState.PARSED)

    def test_observed_formats_match_reality(self) -> None:
        observed = {s.tool: s.observed_format for s in self.bundle.sources}
        self.assertEqual(observed, EXPECTED_FORMATS)

    def test_no_unrecognized_source(self) -> None:
        bad = [s.tool for s in self.bundle.sources if s.state is PayloadState.UNRECOGNIZED]
        self.assertEqual(bad, [], "不得有数据源被判定为解析失败")

    def test_record_counts(self) -> None:
        counts = {s.tool: s.record_count for s in self.bundle.sources}
        self.assertEqual(counts["query-my-coupons"], 14)
        self.assertEqual(counts["available-coupons"], 9)
        self.assertEqual(counts["campaign-calendar"], 30)
        self.assertEqual(counts["query-my-account"], 1)

    def test_bundle_contents(self) -> None:
        self.assertEqual(len(self.bundle.my_coupons), 14)
        self.assertEqual(len(self.bundle.available_coupons), 9)
        self.assertEqual(len(self.bundle.campaigns), 30)
        self.assertTrue(self.bundle.account.present)

    def test_no_parse_warnings_that_indicate_failure(self) -> None:
        fatal = [n for n in self.bundle.parse_notes if "未能解析出任何" in n or "共 " in n and "实际解析出" in n]
        self.assertEqual(fatal, [])


class TestPriorityRanking(unittest.TestCase):
    """真实数据必须真的经过**本项目自己的**分级与排序，不是照抄工具输出。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        cls.radar = build_radar(
            cls.bundle.my_coupons,
            cls.bundle.available_coupons,
            cls.bundle.campaigns,
            cls.bundle.account,
            TODAY,
        )

    def test_level_distribution_follows_the_grading_rules(self) -> None:
        counts = self.radar.counts
        # 2026-10-09 到期 2 张 → P0；10-10/11/12 → P1；10-13~10-16 → P2；其余 → P3
        self.assertEqual(counts.get("P0"), 2)
        self.assertEqual(counts.get("P1"), 3)
        self.assertEqual(counts.get("P2"), 4)
        self.assertEqual(counts.get("P3"), 5)
        self.assertEqual(counts.get("UNKNOWN", 0), 0, "「我的券」都带有效期，不该出现 UNKNOWN")
        self.assertEqual(sum(counts.values()), 14)

    def test_urgent_list_is_level_then_days_sorted(self) -> None:
        urgent = self.radar.urgent
        self.assertEqual(len(urgent), 5, "P0 2 张 + P1 3 张")
        self.assertEqual(urgent[0].level, Level.P0)
        self.assertLessEqual(urgent[0].days_left, urgent[-1].days_left)

    def test_coupon_expiring_today_is_flagged_today(self) -> None:
        today_items = [a for a in self.radar.coupons if a.days_left == 0]
        self.assertEqual(len(today_items), 2)
        self.assertTrue(all(a.level is Level.P0 for a in today_items))
        self.assertTrue(all(a.reason == "今天到期" for a in today_items))

    def test_claimable_coupons_without_expiry_are_unknown_not_zero(self) -> None:
        """没有有效期 → UNKNOWN 且措辞为「未提供」，**绝不能**显示为"0 天后到期"。"""
        unknown = [a for a in self.radar.claimable if a.days_left is None]
        self.assertTrue(unknown)
        self.assertTrue(all(a.level is Level.UNKNOWN for a in unknown))
        self.assertTrue(all("未提供" in a.reason for a in unknown))
        self.assertTrue(all("0 天后到期" not in a.reason for a in unknown))


class TestReportContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        cls.radar = build_radar(
            cls.bundle.my_coupons,
            cls.bundle.available_coupons,
            cls.bundle.campaigns,
            cls.bundle.account,
            TODAY,
        )
        cls.report = render_report(cls.bundle, cls.radar)

    def test_all_eight_sections_present(self) -> None:
        for index, title in enumerate(
            (
                "元信息",
                "立即行动",
                "本周内到期",
                "可计划与待确认",
                "积分账户",
                "活动日历",
                "待领取",
                "数据完整性与免责声明",
            ),
            1,
        ):
            with self.subTest(section=index):
                self.assertIn(f"## {index}. {title}", self.report)

    def test_campaigns_are_shown_not_reported_as_empty(self) -> None:
        self.assertIn("共 30 条日历条目", self.report)
        self.assertNotIn("本月无活动", self.report)
        self.assertNotIn("解析失败。**\n> `campaign-calendar`", self.report)

    def test_today_date_present(self) -> None:
        self.assertIn(TODAY.isoformat(), self.report)

    def test_points_section_shows_values(self) -> None:
        self.assertIn("| 可用积分 | 120 |", self.report)
        self.assertIn("| 已使用积分 | 900 |", self.report)
        self.assertIn("麦享会积分", self.report)

    def test_not_provided_wording_used(self) -> None:
        self.assertIn("未提供", self.report)

    def test_no_mock_banner_in_replay_mode(self) -> None:
        self.assertNotIn("模拟（mock）模式", self.report)
        self.assertIn("回放（replay）模式", self.report)

    def test_no_period_claimed_for_calendar_items(self) -> None:
        section = self.report.split("## 6. 活动日历")[1].split("## 7.")[0]
        self.assertNotIn("今天结束", section)
        self.assertNotIn("天后结束", section)

    def test_summary_line(self) -> None:
        text = summarize(self.bundle, self.radar)
        self.assertIn("解析失败 0", text)
        self.assertIn("券 14 张", text)


class TestNoSensitiveLeakage(unittest.TestCase):
    """报告是给用户看、也可能被截图外传的，绝不能带凭据或账户标识。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        cls.radar = build_radar(
            cls.bundle.my_coupons,
            cls.bundle.available_coupons,
            cls.bundle.campaigns,
            cls.bundle.account,
            TODAY,
        )
        cls.report = render_report(cls.bundle, cls.radar)

    def test_no_account_id_value_in_report(self) -> None:
        """字段**名**会在隐私说明里被点名（这是刻意为之），但**取值**绝不能出现。"""
        self.assertNotIn("00000000-0000-0000-0000-000000000000", self.report)
        self.assertEqual(
            self.report.count("accountId"),
            1,
            "accountId 只应作为隐私说明里的字段名出现一次，不得出现在数据行",
        )
        self.assertIn("不保存取值", self.report)

    def test_no_signed_url_query_string_in_report(self) -> None:
        self.assertNotIn("q-signature", self.report)
        self.assertNotIn("q-ak=", self.report)

    def test_no_token_like_string_in_report(self) -> None:
        for pattern in (r"(?i)bearer\s+\S", r"[0-9a-fA-F]{32,}"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.report))

    def test_replay_fixtures_themselves_are_clean(self) -> None:
        """样例入库前必须已脱敏——否则等于把真实凭据提交进仓库。"""
        for name in support.REAL_FIXTURES.values():
            text = support.read_fixture(name)
            with self.subTest(fixture=name):
                self.assertNotIn("q-signature=", text)
                self.assertNotIn("AKID", text)
                self.assertNotRegex(text, r"(?i)bearer\s+\S")


class TestReplayCli(unittest.TestCase):
    """命令行回放：不联网也能跑出与线上同构的报告。"""

    def test_replay_dir_produces_report(self) -> None:
        import run_radar

        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            code = run_radar.main(
                [
                    "--mode",
                    "replay",
                    "--replay-dir",
                    str(support.FIXTURES),
                    "--today",
                    TODAY.isoformat(),
                    "--out",
                    str(out),
                    "--quiet",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            text = out.read_text(encoding="utf-8")
            self.assertIn("共 30 条日历条目", text)

    def test_missing_replay_files_degrade_not_crash(self) -> None:
        import run_radar

        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            code = run_radar.main(
                ["--mode", "replay", "--replay-dir", tmp, "--today", TODAY.isoformat(), "--out", str(out), "--quiet"]
            )
            # 四个源全部取不到 → 退出码 1，但报告仍必须生成
            self.assertEqual(code, 1)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
