"""活动日历 Markdown 解析器测试。

基准数据 ``fixtures/campaign_calendar.md`` **结构逐行对标 2026-10-09 对官方 MCP
（``campaign-calendar``，入参 ``{}``）的真实响应**，但活动标题、正文与素材地址
已全部替换为合成值（真实响应不随公开仓库分发）。
用它做基准，是为了让"解析结果 == 官方格式"这件事可被自动化验证，
而不是靠一次性的目测。
"""

from __future__ import annotations

import collections
import re
import unittest
from datetime import date
from pathlib import Path

import support
from normalize import (
    Campaign,
    build_bundle,
    normalize_campaign,
    parse_campaign_markdown,
    parse_date,
)
from radar import Level, assess_campaign, build_radar
from report import render_report

TODAY = date(2026, 10, 9)

#: 真实响应基准（逐字副本）
LIVE_FIXTURE = support.FIXTURES / "campaign_calendar.md"

#: 基准样例中的日期分组数（人工核对）
LIVE_DATE_GROUPS = 12
#: 基准样例中的活动条目数（人工核对：`-   **活动标题**` 出现次数）
LIVE_ENTRY_COUNT = 30
#: 基准样例中 2026-10-09 当日条目数（官方标注「今日」）
LIVE_TODAY_ENTRY_COUNT = 14


def live_text() -> str:
    return LIVE_FIXTURE.read_text(encoding="utf-8")


def count_headings(text: str) -> int:
    return len(re.findall(r"^\s{0,3}#{1,6}\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text, re.M))


def count_entries(text: str) -> int:
    return len(re.findall(r"^\s*[-*+]\s+\*\*\s*活动标题\s*\*\*", text, re.M))


class TestFixtureProvenance(unittest.TestCase):
    """基准文件必须能被独立计数复核——否则"没丢活动"的结论无从谈起。"""

    def test_fixture_exists(self) -> None:
        self.assertTrue(LIVE_FIXTURE.is_file(), "缺少格式基准样例文件")

    def test_manual_counts_match_constants(self) -> None:
        text = live_text()
        self.assertEqual(count_headings(text), LIVE_DATE_GROUPS, "日期分组数与常量不符")
        self.assertEqual(count_entries(text), LIVE_ENTRY_COUNT, "条目数与常量不符")

    def test_fixture_has_no_account_data(self) -> None:
        """基准文件只能含公开营销内容。"""
        text = live_text()
        for forbidden in ("积分余额", "手机号", "会员号", "availablePoints", "couponId"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


class TestParseLiveResponse(unittest.TestCase):
    """核心断言：真实返回 → 解析结果，一条不丢。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = live_text()
        cls.records, cls.warnings = parse_campaign_markdown(cls.text)

    def test_no_activity_is_lost(self) -> None:
        self.assertEqual(len(self.records), LIVE_ENTRY_COUNT, "解析出的活动数与基准样例不一致")

    def test_no_warnings_on_real_response(self) -> None:
        self.assertEqual(self.warnings, [], "基准样例不应产生解析警告")

    def test_date_group_distribution(self) -> None:
        expected = {
            "2026-10-07": 1,
            "2026-10-08": 2,
            "2026-10-09": 14,
            "2026-10-10": 2,
            "2026-10-11": 2,
            "2026-10-12": 2,
            "2026-10-13": 1,
            "2026-10-14": 1,
            "2026-10-15": 1,
            "2026-10-18": 1,
            "2026-10-22": 1,
            "2026-10-23": 2,
        }
        actual = collections.Counter(r["_calendarDate"] for r in self.records)
        self.assertEqual(dict(sorted(actual.items())), expected)
        self.assertEqual(sum(expected.values()), LIVE_ENTRY_COUNT)

    def test_today_group_is_labelled(self) -> None:
        today = [r for r in self.records if r["_calendarDate"] == "2026-10-09"]
        self.assertEqual(len(today), LIVE_TODAY_ENTRY_COUNT)
        for record in today:
            self.assertEqual(record["_groupLabel"], "今日")

    def test_past_groups_are_labelled(self) -> None:
        past = [r for r in self.records if r["_calendarDate"] in ("2026-10-07", "2026-10-08")]
        self.assertEqual(len(past), 3)
        for record in past:
            self.assertEqual(record["_groupLabel"], "往期回顾")

    def test_future_groups_have_no_label(self) -> None:
        """官方只给「往期回顾」「今日」打标签，未来日期无标签——这是格式事实，不是缺失。"""
        future = [r for r in self.records if r["_calendarDate"] > "2026-10-09"]
        self.assertEqual(len(future), LIVE_ENTRY_COUNT - LIVE_TODAY_ENTRY_COUNT - 3)
        for record in future:
            self.assertIsNone(record["_groupLabel"])

    def test_every_record_has_title(self) -> None:
        for record in self.records:
            with self.subTest(record=record["campaignId"]):
                self.assertTrue(record["campaignName"] and record["campaignName"].strip())

    def test_every_record_has_image(self) -> None:
        for record in self.records:
            with self.subTest(record=record["campaignId"]):
                self.assertTrue(record["_image"], "基准样例里每条活动都带图片")
                self.assertTrue(record["_image"].startswith("https://example.invalid/"))

    def test_every_record_has_content(self) -> None:
        for record in self.records:
            with self.subTest(record=record["campaignId"]):
                self.assertTrue(record["_content"])

    def test_multiline_content_is_preserved(self) -> None:
        first = self.records[0]
        self.assertIn("\n", first["_content"], "多行内容应保留换行，不得被压成一行")
        self.assertIn("本条为合成示例内容", first["_content"])

    def test_known_entry_is_parsed_exactly(self) -> None:
        record = next(
            r for r in self.records
            if r["_calendarDate"] == "2026-10-09" and r["campaignName"].startswith("【合成样例】活动")
        )
        self.assertEqual(record["_groupLabel"], "今日")
        self.assertIn("本条为合成示例内容", record["_content"])
        self.assertTrue(record["_image"].endswith(".png"))


class TestNormalizedCampaignFromMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, _ = parse_campaign_markdown(live_text())
        cls.campaigns = [normalize_campaign(r) for r in cls.records]

    def test_synthetic_id_is_flagged_and_documented(self) -> None:
        for campaign in self.campaigns:
            with self.subTest(campaign=campaign.id):
                self.assertTrue(campaign.synthetic_id, "必须标记为生成的定位编号")
                self.assertRegex(campaign.id, r"^MD-\d{8}-\d{2}$")
                self.assertNotIn("id", campaign.missing, "生成的定位编号不该被登记为缺失")

    def test_calendar_date_and_source(self) -> None:
        for campaign in self.campaigns:
            with self.subTest(campaign=campaign.id):
                self.assertEqual(campaign.date_source, "markdown")
                self.assertIsNotNone(campaign.calendar_date)
                self.assertEqual(campaign.start, campaign.calendar_date)
                self.assertEqual(campaign.end, campaign.calendar_date)

    def test_no_spurious_missing_fields(self) -> None:
        """Markdown 日历天然没有 status / id，不应逐条刷屏为缺失。"""
        for campaign in self.campaigns:
            with self.subTest(campaign=campaign.id):
                self.assertEqual(campaign.missing, [])

    def test_future_entries_have_no_status_but_are_not_missing(self) -> None:
        future = [c for c in self.campaigns if c.calendar_date > TODAY]
        self.assertTrue(future)
        for campaign in future:
            self.assertIsNone(campaign.status)
            self.assertNotIn("status", campaign.missing)


class TestCalendarAssessment(unittest.TestCase):
    """日历条目不得被表述成到期/结束——那是编造。"""

    @classmethod
    def setUpClass(cls) -> None:
        records, _ = parse_campaign_markdown(live_text())
        cls.campaigns = [normalize_campaign(r) for r in records]

    def test_levels_are_calendar_semantics(self) -> None:
        level_by_date = {}
        for campaign in self.campaigns:
            level_by_date.setdefault(campaign.calendar_date, assess_campaign(campaign, TODAY).level)
        self.assertIs(level_by_date[date(2026, 10, 9)], Level.TODAY)
        self.assertIs(level_by_date[date(2026, 10, 10)], Level.UPCOMING)
        self.assertIs(level_by_date[date(2026, 10, 7)], Level.PAST)

    def test_never_claims_deadline_urgency(self) -> None:
        """日历条目不使用 P0–P4 / EXPIRED，也不出现"结束"措辞。"""
        for campaign in self.campaigns:
            with self.subTest(campaign=campaign.id):
                assessment = assess_campaign(campaign, TODAY)
                self.assertNotIn(
                    assessment.level,
                    {Level.P0, Level.P1, Level.P2, Level.P3, Level.P4, Level.EXPIRED},
                )
                self.assertNotIn("结束", assessment.reason)
                self.assertNotIn("到期", assessment.reason)

    def test_today_reason_cites_official_label(self) -> None:
        today = next(c for c in self.campaigns if c.calendar_date == date(2026, 10, 9))
        self.assertIn("今日", assess_campaign(today, TODAY).reason)

    def test_missing_calendar_date_goes_unknown(self) -> None:
        broken = Campaign(id="MD-X", name="无日期活动", date_source="markdown")
        self.assertIs(assess_campaign(broken, TODAY).level, Level.UNKNOWN)


class TestMarkdownReportRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, _ = parse_campaign_markdown(live_text())
        cls.campaigns = [normalize_campaign(r) for r in cls.records]
        cls.bundle = support.mock_bundle(TODAY)
        cls.bundle.campaigns = cls.campaigns
        cls.radar = build_radar(
            cls.bundle.my_coupons, cls.bundle.available_coupons,
            cls.bundle.campaigns, cls.bundle.account, TODAY,
        )
        cls.text = render_report(cls.bundle, cls.radar)
        cls.section = cls.text.split("## 6. 活动日历")[1].split("## 7.")[0]

    def test_activity_count_is_not_zero(self) -> None:
        """修复前此处为 0（报告显示"本月没有活动"）。"""
        self.assertIn(f"| 活动 | {LIVE_ENTRY_COUNT} |", self.text)

    def test_section_lists_all_entries(self) -> None:
        rows = [line for line in self.section.splitlines() if line.startswith("| TODAY ")
                or line.startswith("| UPCOMING ") or line.startswith("| PAST ")]
        self.assertEqual(len(rows), LIVE_ENTRY_COUNT, "正文表格必须列出全部条目")

    def test_today_entries_present(self) -> None:
        today_rows = [line for line in self.section.splitlines() if line.startswith("| TODAY ")]
        self.assertEqual(len(today_rows), LIVE_TODAY_ENTRY_COUNT)

    def test_今天结束_is_never_rendered(self) -> None:
        """日历日期不是截止日，报告不得宣称活动"今天结束"。"""
        self.assertNotIn("今天结束", self.text)
        self.assertNotIn("天后结束", self.text)
        self.assertNotIn("已结束", self.text)

    def test_no_missing_mark_in_group_column(self) -> None:
        self.assertNotIn("[字段缺失]", self.section)

    def test_footnote_explains_calendar_semantics(self) -> None:
        self.assertIn("不提供活动的有效期", self.section)
        self.assertIn("不是截止日", self.section)

    def test_no_token_in_report(self) -> None:
        self.assertNotIn(support.SENTINEL_TOKEN, self.text)


class TestDualFormatCompatibility(unittest.TestCase):
    """JSON 与 Markdown 双格式并存：JSON 走原路径，行为不得改变。"""

    def test_json_campaigns_still_parse(self) -> None:
        bundle = support.mock_bundle(TODAY)
        self.assertEqual(len(bundle.campaigns), 4)
        for campaign in bundle.campaigns:
            with self.subTest(campaign=campaign.id):
                self.assertEqual(campaign.date_source, "json")
                self.assertFalse(campaign.synthetic_id)

    def test_json_path_preferred_when_records_present(self) -> None:
        """同一份数据里，能走 JSON 就不该去猜 Markdown。"""
        from mcd_client import ToolResult

        payload = {"data": {"campaignList": [{
            "campaignId": "X1", "campaignName": "结构化活动",
            "startDate": "2026-10-01", "endDate": "2026-10-20", "status": "进行中",
        }]}}
        bundle = build_bundle(
            {"campaign-calendar": ToolResult("campaign-calendar", True, payload, mode="mock")},
            mode="mock", today=TODAY,
        )
        self.assertEqual(len(bundle.campaigns), 1)
        self.assertEqual(bundle.campaigns[0].date_source, "json")
        self.assertEqual(bundle.parse_notes, [])

    def test_markdown_path_used_when_json_fails(self) -> None:
        from mcd_client import ToolResult

        bundle = build_bundle(
            {"campaign-calendar": ToolResult("campaign-calendar", True, live_text(), mode="real")},
            mode="real", today=TODAY,
        )
        self.assertEqual(len(bundle.campaigns), LIVE_ENTRY_COUNT)
        self.assertTrue(all(c.date_source == "markdown" for c in bundle.campaigns))
        self.assertTrue(bundle.parse_notes, "必须说明日历日期的语义")

    def test_both_formats_produce_campaign_objects(self) -> None:
        from mcd_client import ToolResult

        for payload, expected in ((live_text(), LIVE_ENTRY_COUNT),
                                  ({"data": {"campaignList": [{"campaignId": "A", "campaignName": "A",
                                                               "startDate": "2026-10-01",
                                                               "endDate": "2026-10-20"}]}}, 1)):
            with self.subTest(kind=type(payload).__name__):
                bundle = build_bundle(
                    {"campaign-calendar": ToolResult("campaign-calendar", True, payload, mode="mock")},
                    mode="mock", today=TODAY,
                )
                self.assertEqual(len(bundle.campaigns), expected)
                self.assertTrue(all(isinstance(c, Campaign) for c in bundle.campaigns))


class TestParserRobustness(unittest.TestCase):
    """异常与边界：解析不了的部分必须变成警告，不得静默丢弃。"""

    def test_entry_without_title_is_warned(self) -> None:
        text = (
            "#### 2026年10月9日 今日\n\n"
            "-   **活动内容介绍**：只有正文，没有标题\n"
            "    <img src=\"https://example.com/a.jpg\">\n"
        )
        records, warnings = parse_campaign_markdown(text)
        self.assertEqual(records, [])
        self.assertTrue(any("未能提取到标题" in w for w in warnings), warnings)

    def test_date_group_without_entries_is_warned(self) -> None:
        text = "#### 2026年10月9日 今日\n\n（这里本来应该有条目但没有）\n"
        records, warnings = parse_campaign_markdown(text)
        self.assertEqual(records, [])
        self.assertTrue(any("未解析出任何活动条目" in w for w in warnings), warnings)

    def test_fully_unparseable_text_is_warned(self) -> None:
        records, warnings = parse_campaign_markdown("<xml><campaign/></xml>")
        self.assertEqual(records, [])
        self.assertTrue(any("未能解析出任何活动条目" in w for w in warnings), warnings)

    def test_invalid_date_heading_is_warned(self) -> None:
        text = "#### 2026年2月30日 今日\n\n-   **活动标题**：不存在的日期\n"
        records, warnings = parse_campaign_markdown(text)
        self.assertEqual(records, [])
        self.assertTrue(any("不是合法日期" in w for w in warnings), warnings)

    def test_empty_text_yields_nothing_and_no_false_warning(self) -> None:
        records, warnings = parse_campaign_markdown("")
        self.assertEqual(records, [])
        self.assertEqual(warnings, [], "真正的空输入不应报警")

    def test_dash_separated_date_heading_is_tolerated(self) -> None:
        text = "#### 2026-10-09 今日\n\n-   **活动标题**：破折号日期\n"
        records, _ = parse_campaign_markdown(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["_calendarDate"], "2026-10-09")

    def test_image_without_quotes_is_tolerated(self) -> None:
        text = (
            "#### 2026年10月9日 今日\n\n"
            "-   **活动标题**：无引号图片\n"
            "    **活动图片介绍**：\n"
            "    <img src=https://example.com/b.png alt=x>\n"
        )
        records, _ = parse_campaign_markdown(text)
        self.assertEqual(records[0]["_image"], "https://example.com/b.png")

    def test_unknown_field_is_kept_in_content_not_dropped(self) -> None:
        text = (
            "#### 2026年10月9日 今日\n\n"
            "-   **活动标题**：含未知字段\n"
            "    **活动时间**：10月9日 10:00\n"
        )
        records, _ = parse_campaign_markdown(text)
        self.assertIn("活动时间", records[0]["_content"])

    def test_parse_date_accepts_chinese_dates(self) -> None:
        self.assertEqual(parse_date("2026年10月9日"), date(2026, 10, 9))


if __name__ == "__main__":
    unittest.main(verbosity=2)
