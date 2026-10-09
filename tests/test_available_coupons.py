"""「麦麦省可领取券」真实 Markdown 格式的解析测试。

格式取自 2026-10-09 对官方 MCP `available-coupons` 的真实调用。
``fixtures/available_coupons.md`` 是**结构逐行对标真实响应、取值全部合成**的样例
（真实响应含账户数据，不随公开仓库分发；样例中的券名一律带 `【合成样例】` 前缀）。

这个格式有两个坑，本组测试专门盯住它们：

1. 字段用**行尾反斜杠**续行，按 Markdown 列表项切分会切错；
2. 列表里**混着「已领取」与「可领取」两种状态**，
   把「已领取」也算成待领取，就是在骗用户去领一张他已经有的券。
"""

from __future__ import annotations

import unittest
from collections import Counter
from datetime import date

import support  # noqa: F401  (注册 scripts/ 到 sys.path)

from normalize import (
    MD_AVAILABLE_ABSENT,
    NOT_PROVIDED_MARK,
    build_bundle,
    normalize_coupon,
    observe_format,
    parse_available_coupons_markdown,
)

TODAY = date(2026, 10, 9)


class TestRealFixtureParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = support.read_fixture("available_coupons.md")
        cls.records, cls.warnings = parse_available_coupons_markdown(cls.text)

    def test_format_is_detected_as_markdown(self) -> None:
        self.assertEqual(observe_format(self.text), "markdown")

    def test_parses_all_entries_despite_backslash_continuation(self) -> None:
        self.assertEqual(len(self.records), 9)

    def test_no_warnings_on_sample_response(self) -> None:
        self.assertEqual(self.warnings, [], "\n".join(self.warnings))

    def test_status_is_captured_for_every_entry(self) -> None:
        self.assertTrue(all(r["couponStatus"] for r in self.records), "每条都必须有状态")

    def test_status_distribution_matches_source(self) -> None:
        counts = Counter(r["couponStatus"] for r in self.records)
        self.assertEqual(counts["已领取"], 6)
        self.assertEqual(counts["可领取"], 3)

    def test_image_extracted_for_every_entry(self) -> None:
        self.assertTrue(all(r["_image"] for r in self.records), "图片必须全部提取到")

    def test_absent_fields_not_reported_per_record(self) -> None:
        """可领取券正文不带有效期等字段，不该逐条报 missing。"""
        coupon = normalize_coupon(self.records[0], "available")
        for field in MD_AVAILABLE_ABSENT:
            self.assertNotIn(field, coupon.missing, f"{field} 属格式不提供，不应逐条报警")
        self.assertEqual(coupon.missing, [])

    def test_unknown_mark_says_not_provided(self) -> None:
        coupon = normalize_coupon(self.records[0], "available")
        self.assertEqual(coupon.unknown_mark, NOT_PROVIDED_MARK)

    def test_remaining_time_is_not_provided_not_zero(self) -> None:
        """没有有效期 → 显示「未提供」，绝不能显示 0 天或"今天到期"。"""
        coupon = normalize_coupon(self.records[0], "available")
        self.assertIsNone(coupon.valid_to)
        self.assertIsNone(coupon.days_left if hasattr(coupon, "days_left") else None)


class TestOwnershipSeparation(unittest.TestCase):
    """「已领取」不得被当成「待领取」——这是最容易误导用户的一处。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)

    def test_owned_entries_are_marked_duplicate(self) -> None:
        owned = [c for c in self.bundle.available_coupons if c.duplicate_of_owned]
        self.assertEqual(len(owned), 6, "6 条已持有的券应被标记")

    def test_truly_claimable_entries_survive(self) -> None:
        fresh = [
            c
            for c in self.bundle.available_coupons
            if not c.duplicate_of_owned and (c.status or "") != "已领取"
        ]
        self.assertEqual(
            sorted(c.name for c in fresh),
            ["【合成样例】免费小食券", "【合成样例】甜品买一送一", "【合成样例】饮品券"],
        )

    def test_report_explains_the_split(self) -> None:
        from radar import build_radar
        from report import render_report

        radar = build_radar(
            self.bundle.my_coupons,
            self.bundle.available_coupons,
            self.bundle.campaigns,
            self.bundle.account,
            TODAY,
        )
        text = render_report(self.bundle, radar)
        section = text.split("## 7. 待领取")[1].split("## 8.")[0]
        self.assertIn("未提供", section, "无有效期的券应显示「未提供」")
        self.assertNotIn("今天到期", section, "可领取券不得被说成今天到期")
        self.assertIn("你已持有", section)


class TestEdgeCases(unittest.TestCase):
    def test_empty_text(self) -> None:
        records, warnings = parse_available_coupons_markdown("")
        self.assertEqual((records, warnings), ([], []))

    def test_heading_only_yields_no_records_and_no_warning(self) -> None:
        records, warnings = parse_available_coupons_markdown("### 麦麦省优惠券列表：\n")
        self.assertEqual(records, [])
        self.assertEqual(warnings, [])

    def test_unrecognized_nonempty_text_warns(self) -> None:
        records, warnings = parse_available_coupons_markdown("完全不是这个格式的一段话")
        self.assertEqual(records, [])
        self.assertTrue(warnings)

    def test_titleless_entry_warns(self) -> None:
        records, warnings = parse_available_coupons_markdown("- 优惠券标题： \\\n  状态：可领取 \\\n")
        self.assertEqual(records, [])
        self.assertTrue(any("标题" in w for w in warnings))

    def test_stray_lines_are_reported_not_dropped(self) -> None:
        text = "### 麦麦省优惠券列表：\n游离内容\n\n- 优惠券标题：某券 \\\n  状态：可领取 \\\n"
        _, warnings = parse_available_coupons_markdown(text)
        self.assertTrue(any("不在任何券条目内" in w for w in warnings), warnings)

    def test_validity_is_parsed_when_present(self) -> None:
        """当前真实返回没有有效期，但格式若加上了也要能解析。"""
        text = "- 优惠券标题：带有效期的券 \\\n  状态：可领取 \\\n  有效期：2026-10-20 00:00-2026-10-25 23:59 \\\n"
        records, _ = parse_available_coupons_markdown(text)
        coupon = normalize_coupon(records[0], "available")
        self.assertEqual(coupon.valid_to, date(2026, 10, 25))
        self.assertNotIn("valid_to", coupon.missing)


if __name__ == "__main__":
    unittest.main()
