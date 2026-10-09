"""「我的优惠券」真实 Markdown 格式的解析测试。

格式取自 2026-10-09 对官方 MCP `query-my-coupons` 的真实调用。
``fixtures/query_my_coupons.md`` 是**结构逐行对标真实响应、取值全部合成**的样例
（真实响应含账户数据，不随公开仓库分发；样例中的券名一律带 `【合成样例】` 前缀）。

这一组的重点不是"能解析出来"，而是**不解析错**：
把 `¥9.9 (用券价格)` 读成"优惠 9.9 元"、把缺失的条数静默吞掉，
都是会让用户做出错误决定的缺陷。
"""

from __future__ import annotations

import unittest
from datetime import date

import support  # noqa: F401  (注册 scripts/ 到 sys.path)

from normalize import (
    MD_COUPON_ABSENT,
    NOT_PROVIDED_MARK,
    build_bundle,
    classify_benefit,
    normalize_coupon,
    observe_format,
    parse_coupon_markdown,
    parse_coupon_validity,
)

TODAY = date(2026, 10, 9)


def _records() -> list[dict]:
    text = support.read_fixture("query_my_coupons.md")
    records, _ = parse_coupon_markdown(text)
    return records


class TestFixtureParsing(unittest.TestCase):
    """正常返回：锁住"线上格式的结构一定能被读懂"。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = support.read_fixture("query_my_coupons.md")
        cls.records, cls.warnings = parse_coupon_markdown(cls.text)

    def test_format_is_detected_as_markdown(self) -> None:
        self.assertEqual(observe_format(self.text), "markdown")

    def test_parses_every_coupon_declared_in_heading(self) -> None:
        """正文声明 14 张，就必须解析出 14 张——数量不符是硬失败。"""
        self.assertEqual(len(self.records), 14)
        self.assertEqual(self.warnings, [])

    def test_no_warnings_on_sample_response(self) -> None:
        self.assertEqual(self.warnings, [], "\n".join(self.warnings))

    def test_validity_range_split_into_start_and_end(self) -> None:
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.valid_from, date(2026, 10, 5))
        self.assertEqual(first.valid_to, date(2026, 10, 9))

    def test_period_restriction_kept_verbatim(self) -> None:
        """「周一、二、三、四、五 10:30-23:59」是使用条件，必须原样保留。"""
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.valid_window, "周一、二、三、四、五 10:30-23:59")

    def test_status_and_channel_split_from_tags(self) -> None:
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.status, "今日到期")
        self.assertEqual(first.channel, "到店专用、外送专用")

    def test_benefit_is_price_not_discount(self) -> None:
        """最关键的断言：`¥9.9 (用券价格)` 绝不能被当成"优惠 9.9 元"。"""
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.benefit_kind, "price")
        self.assertEqual(first.price, 9.9)
        self.assertEqual(first.benefit_text, "¥9.9 (用券价格)")
        self.assertIsNone(first.discount_value, "用券价格不是优惠金额，不得写入 discount_value")

    def test_benefit_display_keeps_official_wording(self) -> None:
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.benefit_display, "¥9.9 (用券价格)")

    def test_image_extracted(self) -> None:
        first = normalize_coupon(self.records[0], "my")
        self.assertTrue(first.image and first.image.endswith("icecream-1.jpg"))

    def test_received_time_kept_as_text(self) -> None:
        first = normalize_coupon(self.records[0], "my")
        self.assertEqual(first.received_text, "4日前收到")

    def test_absent_fields_are_not_reported_as_per_record_missing(self) -> None:
        """格式不提供的字段（券ID/类型/优惠值/门槛）不该逐条进 missing。"""
        coupon = normalize_coupon(self.records[0], "my")
        for field in MD_COUPON_ABSENT:
            self.assertNotIn(field, coupon.missing, f"{field} 属格式不提供，不应逐条报警")

    def test_unknown_mark_says_not_provided_for_markdown(self) -> None:
        coupon = normalize_coupon(self.records[0], "my")
        self.assertEqual(coupon.unknown_mark, NOT_PROVIDED_MARK)


class TestMultipleCoupons(unittest.TestCase):
    """多条优惠券：顺序、日期递增、同名不同券不被合并。"""

    def test_dates_are_strictly_increasing(self) -> None:
        dates = [normalize_coupon(r, "my").valid_to for r in _records()]
        self.assertEqual(dates, sorted(dates))

    def test_duplicate_names_kept_as_separate_coupons(self) -> None:
        """同名但日期不同的券**不能**被去重——它们是不同的券。"""
        names = [normalize_coupon(r, "my").name for r in _records()]
        pancakes = [n for n in names if n == "【合成样例】早餐套餐甲"]
        self.assertEqual(len(pancakes), 4, "同名 4 张应全部保留")
        # 同一名称出现在多个日期上，且到期日各不相同
        dates = {
            normalize_coupon(r, "my").valid_to
            for r in _records()
            if normalize_coupon(r, "my").name == "【合成样例】早餐套餐甲"
        }
        self.assertEqual(len(dates), 4)

    def test_ref_is_namespaced_and_unique(self) -> None:
        bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        refs = [c.ref for c in bundle.my_coupons]
        self.assertEqual(len(refs), len(set(refs)), "定位编号必须唯一")
        self.assertTrue(all(r.startswith("MC-MY-") for r in refs))

    def test_ref_never_collides_between_lists(self) -> None:
        """两个列表各自从 1 编号；命名空间不可省，否则会误判重复。"""
        bundle = build_bundle(support.real_results(), mode="replay", today=TODAY)
        mine = {c.ref for c in bundle.my_coupons}
        avail = {c.ref for c in bundle.available_coupons}
        self.assertEqual(mine & avail, set())


class TestEdgeCases(unittest.TestCase):
    """空数据 / 格式异常 / 日期缺失 / 解析错误。"""

    def test_empty_text_yields_no_records_and_no_warning(self) -> None:
        records, warnings = parse_coupon_markdown("")
        self.assertEqual(records, [])
        self.assertEqual(warnings, [], "真正的空不该报警")

    def test_nonempty_unrecognized_text_produces_warning(self) -> None:
        """有内容但读不懂 → 必须报警，不能静默返回零条。"""
        records, warnings = parse_coupon_markdown("这是一段完全不符合格式的文本 <xml/>")
        self.assertEqual(records, [])
        self.assertTrue(warnings, "非空却解析不出任何券，必须产生警告")

    def test_count_mismatch_produces_warning(self) -> None:
        text = "共 14 张可用优惠券 | 第 1/1 页\n\n## 只有一张\n- **优惠**: ¥9.9\n"
        records, warnings = parse_coupon_markdown(text)
        self.assertEqual(len(records), 1)
        self.assertTrue(
            any("共 14 张" in w and "解析出 1 张" in w for w in warnings),
            f"条数不符必须报警，实际警告：{warnings}",
        )

    def test_missing_validity_marks_valid_to_as_missing(self) -> None:
        text = "共 1 张可用优惠券\n\n## 没有有效期的券\n- **优惠**: ¥9.9 (用券价格)\n"
        records, warnings = parse_coupon_markdown(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(warnings, [])
        coupon = normalize_coupon(records[0], "my")
        self.assertIsNone(coupon.valid_to)
        self.assertIn("valid_to", coupon.missing, "「我的券」缺有效期必须逐条报警")

    def test_titleless_block_is_warned_not_dropped_silently(self) -> None:
        text = "共 1 张可用优惠券\n\n## \n- **优惠**: ¥9.9\n"
        records, warnings = parse_coupon_markdown(text)
        self.assertEqual(records, [])
        self.assertTrue(any("券名" in w for w in warnings))

    def test_unknown_extra_field_is_kept_not_discarded(self) -> None:
        """官方将来新增字段时，内容进 content / extra_text，不能丢。"""
        text = "共 1 张可用优惠券\n\n## 新券\n- **使用规则**: 每人限用一次\n"
        records, _ = parse_coupon_markdown(text)
        self.assertIn("使用规则", records[0]["_content"] or "")
        coupon = normalize_coupon(records[0], "my")
        self.assertIn("使用规则", coupon.extra_text or "")
        self.assertIn("使用规则", str(coupon.raw), "未归类字段必须留在 raw 里")


class TestValidityParsing(unittest.TestCase):
    def test_weekday_and_time_tail_becomes_window(self) -> None:
        start, end, window = parse_coupon_validity(
            "2026-10-05 10:30-2026-10-09 23:59 周一、二、三、四、五 10:30-23:59"
        )
        self.assertEqual((start, end), (date(2026, 10, 5), date(2026, 10, 9)))
        self.assertEqual(window, "周一、二、三、四、五 10:30-23:59")

    def test_single_day_window(self) -> None:
        start, end, window = parse_coupon_validity("2026-10-10 05:00-2026-10-10 10:29 周六 05:00-10:29")
        self.assertEqual((start, end), (date(2026, 10, 10), date(2026, 10, 10)))
        self.assertEqual(window, "周六 05:00-10:29")

    def test_single_date_used_for_both_ends(self) -> None:
        start, end, _ = parse_coupon_validity("2026-10-11")
        self.assertEqual((start, end), (date(2026, 10, 11), date(2026, 10, 11)))

    def test_unparsable_validity_returns_none_with_raw_text(self) -> None:
        start, end, window = parse_coupon_validity("长期有效")
        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertEqual(window, "长期有效")

    def test_empty_validity(self) -> None:
        self.assertEqual(parse_coupon_validity(""), (None, None, None))

    def test_illegal_date_is_rejected(self) -> None:
        start, end, _ = parse_coupon_validity("2026-02-30 10:00-2026-02-30 11:00")
        self.assertIsNone(start)
        self.assertIsNone(end)


class TestBenefitClassification(unittest.TestCase):
    def test_price_qualifier_wins(self) -> None:
        kind, value, _ = classify_benefit("¥9.9 (用券价格)")
        self.assertEqual((kind, value), ("price", 9.9))

    def test_discount_keyword_detected(self) -> None:
        kind, _, _ = classify_benefit("立减 5 元")
        self.assertEqual(kind, "discount")

    def test_ambiguous_text_stays_unknown_without_value(self) -> None:
        for text in ("买一送一", "免费", "8折", "第二份半价"):
            with self.subTest(text=text):
                kind, value, note = classify_benefit(text)
                self.assertEqual(kind, "unknown")
                self.assertIsNone(value, "判不准时绝不能给出数值")
                self.assertTrue(note, "必须留下'未做换算'的说明")

    def test_multi_number_text_never_yields_a_value(self) -> None:
        """`满30减8` 含两个数字，任何情况下都不得取其中一个当优惠额。"""
        _, value, _ = classify_benefit("满30减8")
        self.assertIsNone(value)

    def test_empty_text(self) -> None:
        kind, value, note = classify_benefit("")
        self.assertEqual((kind, value, note), ("unknown", None, ""))


if __name__ == "__main__":
    unittest.main()
