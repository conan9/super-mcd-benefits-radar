"""报告渲染与端到端测试 —— 覆盖输出契约与"报告中零 Token"。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import support  # noqa: F401
from normalize import MISSING_MARK
from report import DISCLAIMER, render_report, summarize

REQUIRED_SECTIONS = [
    "# 超麦权益雷达 · 权益体检报告",
    "## 1. 元信息",
    "## 2. 立即行动（P0 / P1）",
    "## 3. 本周内到期（P2）",
    "## 4. 可计划与待确认（P3 / P4 / UNKNOWN）",
    "## 5. 积分账户",
    "## 6. 活动日历",
    "## 7. 待领取（麦麦省）",
    "## 8. 数据完整性与免责声明",
]


class TestReportContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.radar = support.mock_radar()
        cls.text = render_report(cls.bundle, cls.radar)

    def test_all_sections_present_in_order(self) -> None:
        positions = []
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, self.text, f"缺少章节：{section}")
            positions.append(self.text.index(section))
        self.assertEqual(positions, sorted(positions), "章节顺序与契约不符")

    def test_mock_mode_banner_is_prominent(self) -> None:
        self.assertIn("模拟（mock）模式", self.text)
        self.assertIn("不是你账户的真实权益", self.text)

    def test_disclaimer_present(self) -> None:
        self.assertIn(DISCLAIMER, self.text)
        self.assertIn("非麦当劳官方产品", self.text)

    def test_readonly_no_action_claim(self) -> None:
        self.assertIn("未执行任何下单、领券或积分消费操作", self.text)

    def test_claim_section_refuses_proxy_action(self) -> None:
        self.assertIn("不会", self.text)
        self.assertIn("自行领取", self.text)

    def test_missing_fields_rendered_explicitly(self) -> None:
        self.assertIn(MISSING_MARK, self.text)

    def test_unknown_coupon_gets_own_table_row(self) -> None:
        """缺到期日的券必须出现在正文表格里，而不只是被提及。"""
        self.assertIn("信息不足 · 无法排序（UNKNOWN）", self.text)
        self.assertIn("MOCK-C-1005", self.text)

    def test_expired_coupon_in_appendix(self) -> None:
        self.assertIn("附录：已过期（仅归档）", self.text)
        self.assertIn("MOCK-C-1006", self.text)

    def test_p0_and_p1_listed_in_action_section(self) -> None:
        action = self.text.split("## 3.")[0]
        self.assertIn("**P0**", action)
        self.assertIn("**P1**", action)

    def test_table_escaping_of_pipe_characters(self) -> None:
        """名称含 ``|`` 时必须转义，否则会把 Markdown 表格列冲散。"""
        from normalize import Coupon
        from radar import RadarResult, Level, assess_coupon

        bundle, _ = support.mock_radar()
        weird = Coupon(id="C|1", name="含|竖线的券", valid_to=bundle.today.replace(day=14))
        assessment = assess_coupon(weird, bundle.today)
        bundle.my_coupons = [weird]
        text = render_report(bundle, RadarResult(today=bundle.today, coupons=[assessment]))
        self.assertNotEqual(assessment.level, Level.UNKNOWN)
        self.assertIn("含\\|竖线的券", text)
        self.assertNotIn("| 含|竖线的券 |", text)

    def test_urgent_bullets_need_no_escaping(self) -> None:
        """要点列表不是表格，原文照排即可。"""
        from normalize import Coupon
        from radar import RadarResult, assess_coupon

        bundle, _ = support.mock_radar()
        today_due = Coupon(id="C2", name="含|竖线的今日券", valid_to=bundle.today)
        bundle.my_coupons = [today_due]
        text = render_report(
            bundle, RadarResult(today=bundle.today, coupons=[assess_coupon(today_due, bundle.today)])
        )
        self.assertIn("含|竖线的今日券", text)


class TestNoTokenInReport(unittest.TestCase):
    def test_report_contains_no_token_even_when_env_has_one(self) -> None:
        with mock.patch.dict(os.environ, {"MCD_MCP_TOKEN": support.SENTINEL_TOKEN}):
            bundle = support.mock_bundle()
            text = render_report(bundle, support.mock_radar()[1])
        self.assertNotIn(support.SENTINEL_TOKEN, text)
        self.assertNotIn(support.SENTINEL_TOKEN[:16], text)

    def test_summary_contains_no_token(self) -> None:
        bundle, radar = support.mock_radar()
        self.assertNotIn(support.SENTINEL_TOKEN, summarize(bundle, radar))


class TestRealModeBanner(unittest.TestCase):
    def test_real_mode_banner_differs(self) -> None:
        bundle, radar = support.mock_radar()
        bundle.mode = "mock"
        mock_text = render_report(bundle, radar)
        bundle.mode = "real"
        real_text = render_report(bundle, radar)
        self.assertNotEqual(mock_text, real_text)
        self.assertIn("真实（real）模式", real_text)
        self.assertNotIn("模拟（mock）模式", real_text)

    def test_generated_at_is_rendered(self) -> None:
        bundle, radar = support.mock_radar()
        bundle.generated_at = datetime(2026, 10, 9, 14, 30, 0)
        self.assertIn("2026-10-09 14:30:00", render_report(bundle, radar))


class TestEndToEndCLI(unittest.TestCase):
    """跑一遍真实入口，确认产物落盘且不含敏感信息。"""

    def test_cli_produces_report(self) -> None:
        import run_radar

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            code = run_radar.main(
                ["--mode", "mock", "--today", "2026-10-09", "--out", str(out), "--quiet"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            content = out.read_text(encoding="utf-8")
            for section in REQUIRED_SECTIONS:
                self.assertIn(section, content)

    def test_cli_returns_nonzero_when_all_sources_fail(self) -> None:
        import run_radar

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"MCD_MOCK_FAIL": ",".join(run_radar.FETCH_ORDER)}
            ):
                code = run_radar.main(
                    ["--mode", "mock", "--out", str(Path(tmp) / "r.md"), "--quiet"]
                )
            self.assertEqual(code, 1, "全部数据源失败应返回非零退出码")

    def test_cli_partial_failure_still_succeeds(self) -> None:
        import run_radar

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MCD_MOCK_FAIL": "query-my-account"}):
                code = run_radar.main(
                    ["--mode", "mock", "--out", str(Path(tmp) / "r.md"), "--quiet"]
                )
            self.assertEqual(code, 0, "单点失败应降级而非失败")

    def test_cli_dump_raw_redacts(self) -> None:
        import run_radar

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MCD_MCP_TOKEN": support.SENTINEL_TOKEN}):
                run_radar.main(
                    ["--mode", "mock", "--out", str(Path(tmp) / "r.md"),
                     "--dump-raw", str(Path(tmp) / "raw"), "--quiet"]
                )
            for path in (Path(tmp) / "raw").glob("*.json"):
                self.assertNotIn(support.SENTINEL_TOKEN, path.read_text(encoding="utf-8"))

    def test_cli_real_mode_without_token_exits_2(self) -> None:
        import run_radar

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, support.env_with(), clear=True):
                code = run_radar.main(["--mode", "real", "--out", str(Path(tmp) / "r.md")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
