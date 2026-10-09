"""归一化与解析测试 —— 对应开发原则 4「不编造、缺字段明确说明」。"""

from __future__ import annotations

import json
import unittest
from datetime import date

import support  # noqa: F401
from mcd_client import ToolResult
from normalize import (
    MISSING_MARK,
    build_bundle,
    days_left,
    find_records,
    humanize_days,
    normalize_account,
    normalize_coupon,
    parse_date,
    parse_number,
    pick,
)


class TestParseDate(unittest.TestCase):
    def test_iso_date(self) -> None:
        self.assertEqual(parse_date("2026-10-25"), date(2026, 10, 25))

    def test_iso_datetime(self) -> None:
        self.assertEqual(parse_date("2026-10-25 23:59:59"), date(2026, 10, 25))

    def test_iso_datetime_with_t_and_timezone(self) -> None:
        self.assertEqual(parse_date("2026-10-25T10:00:00+08:00"), date(2026, 10, 25))

    def test_slash_and_dot_separators(self) -> None:
        self.assertEqual(parse_date("2026/10/25"), date(2026, 10, 25))
        self.assertEqual(parse_date("2026.10.25"), date(2026, 10, 25))

    def test_chinese_date(self) -> None:
        self.assertEqual(parse_date("2026年10月25日"), date(2026, 10, 25))

    def test_compact_date(self) -> None:
        self.assertEqual(parse_date("20261025"), date(2026, 10, 25))

    def test_non_padded_month_day(self) -> None:
        self.assertEqual(parse_date("2026-1-5"), date(2026, 1, 5))

    def test_unix_seconds_and_milliseconds(self) -> None:
        self.assertEqual(parse_date(1792972800), parse_date(1792972800000))

    def test_numeric_string_timestamp(self) -> None:
        self.assertEqual(parse_date("1792972800"), parse_date(1792972800))

    def test_invalid_calendar_date_returns_none(self) -> None:
        """2 月 30 日不存在 —— 必须返回 None，绝不"修正"为 2 月 28 日。"""
        self.assertIsNone(parse_date("2026-02-30"))

    def test_garbage_returns_none(self) -> None:
        for value in (None, "", "   ", "无", "长期有效", "abc"):
            with self.subTest(value=value):
                self.assertIsNone(parse_date(value))

    def test_date_object_passthrough(self) -> None:
        self.assertEqual(parse_date(date(2026, 10, 25)), date(2026, 10, 25))

    def test_never_raises(self) -> None:
        for value in (object(), [], {}, float("nan"), 10**20):
            with self.subTest(value=repr(value)):
                parse_date(value)  # 不抛异常即通过


class TestParseNumber(unittest.TestCase):
    def test_plain_number(self) -> None:
        self.assertEqual(parse_number(8), 8.0)

    def test_float(self) -> None:
        self.assertEqual(parse_number(8.5), 8.5)

    def test_currency_string(self) -> None:
        self.assertEqual(parse_number("￥8.50"), 8.5)
        self.assertEqual(parse_number("8元"), 8.0)

    def test_thousand_separator(self) -> None:
        self.assertEqual(parse_number("1,234.5"), 1234.5)

    def test_multiple_numbers_rejected(self) -> None:
        """核心防错：一句话里多个数字时拒绝解析，交由上层标 [字段缺失]。"""
        self.assertIsNone(parse_number("满30减8"))
        self.assertIsNone(parse_number("买2送1立减10"))

    def test_date_string_rejected(self) -> None:
        self.assertIsNone(parse_number("2026-10-09"))

    def test_bool_rejected(self) -> None:
        """True 在 Python 里是 1，但语义上是布尔值，不能当作金额。"""
        self.assertIsNone(parse_number(True))

    def test_empty_rejected(self) -> None:
        for value in (None, "", "abc"):
            with self.subTest(value=value):
                self.assertIsNone(parse_number(value))


class TestPickAndFindRecords(unittest.TestCase):
    def test_pick_uses_alias_priority(self) -> None:
        record = {"couponName": "优先名", "name": "次选名"}
        value, hit = pick(record, ("couponName", "name"))
        self.assertEqual(value, "优先名")
        self.assertTrue(hit)

    def test_pick_skips_null_and_empty(self) -> None:
        record = {"couponName": None, "name": ""}
        value, hit = pick(record, ("couponName", "name"))
        self.assertFalse(hit)
        self.assertIsNone(value)

    def test_pick_reports_miss(self) -> None:
        self.assertEqual(pick({}, ("a", "b")), (None, False))

    def test_find_records_nested(self) -> None:
        payload = {"data": {"couponList": [{"couponId": "1"}, {"couponId": "2"}]}}
        self.assertEqual(len(find_records(payload)), 2)

    def test_find_records_from_json_text(self) -> None:
        payload = json.dumps({"couponList": [{"couponId": "1"}]})
        self.assertEqual(len(find_records(payload)), 1)

    def test_find_records_empty_payload(self) -> None:
        self.assertEqual(find_records({"data": {}}), [])

    def test_find_records_non_dict_list(self) -> None:
        self.assertEqual(find_records({"list": [1, 2, 3]}), [])


class TestNormalizeCoupon(unittest.TestCase):
    def test_missing_fields_are_recorded_not_filled(self) -> None:
        coupon = normalize_coupon({}, "my")
        for field_name in ("id", "name", "coupon_type", "discount_value", "valid_to"):
            self.assertIn(field_name, coupon.missing, f"{field_name} 应被登记为缺失")
        self.assertIsNone(coupon.valid_to)
        self.assertIsNone(coupon.discount_value)

    def test_display_name_marks_missing(self) -> None:
        coupon = normalize_coupon({"couponId": "X"}, "my")
        self.assertIn(MISSING_MARK, coupon.display_name)

    def test_full_record_no_missing(self) -> None:
        record = {
            "couponId": "C1",
            "couponName": "测试券",
            "couponType": "满减",
            "discountValue": 8,
            "thresholdAmount": 30,
            "startDate": "2026-10-01",
            "endDate": "2026-10-20",
            "useChannel": "全渠道",
            "couponStatus": "可用",
        }
        coupon = normalize_coupon(record, "my")
        self.assertEqual(coupon.id, "C1")
        self.assertEqual(coupon.discount_value, 8.0)
        self.assertEqual(coupon.valid_to, date(2026, 10, 20))
        self.assertEqual(coupon.missing, [])

    def test_alias_fallback(self) -> None:
        """接口字段改名后仍应能取到值。"""
        record = {"id": "C9", "title": "改名字段", "endTime": "2026-10-20"}
        coupon = normalize_coupon(record, "my")
        self.assertEqual(coupon.id, "C9")
        self.assertEqual(coupon.name, "改名字段")
        self.assertEqual(coupon.valid_to, date(2026, 10, 20))

    def test_unparseable_expiry_counts_as_missing(self) -> None:
        coupon = normalize_coupon({"couponId": "C", "endDate": "长期有效"}, "my")
        self.assertIsNone(coupon.valid_to)
        self.assertIn("valid_to", coupon.missing)

    def test_ambiguous_value_marks_missing(self) -> None:
        coupon = normalize_coupon({"couponName": "满30减8", "discountValue": "满30减8"}, "my")
        self.assertIsNone(coupon.discount_value)
        self.assertIn("discount_value", coupon.missing)


class TestNormalizeAccount(unittest.TestCase):
    def test_present_account(self) -> None:
        account = normalize_account({"data": {"availablePoints": 2380, "expiringPoints": 500}})
        self.assertTrue(account.present)
        self.assertEqual(account.available, 2380.0)
        self.assertEqual(account.expiring_points, 500.0)

    def test_missing_expiring_points_stays_missing(self) -> None:
        """不得把缺失的「即将过期积分」当成 0。"""
        account = normalize_account({"data": {"availablePoints": 100}})
        self.assertIsNone(account.expiring_points)
        self.assertIn("expiring_points", account.missing)

    def test_empty_payload_not_present(self) -> None:
        account = normalize_account({})
        self.assertFalse(account.present)
        self.assertIsNone(account.available)


class TestBuildBundle(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = support.mock_bundle()

    def test_counts(self) -> None:
        self.assertEqual(len(self.bundle.my_coupons), 6)
        self.assertEqual(len(self.bundle.available_coupons), 2)
        self.assertEqual(len(self.bundle.campaigns), 4)

    def test_account_present(self) -> None:
        self.assertTrue(self.bundle.account.present)

    def test_account_record_count_not_zero(self) -> None:
        """积分是单对象，状态表不能因为找不到列表就显示 0 条。"""
        status = next(s for s in self.bundle.sources if s.tool == "query-my-account")
        self.assertEqual(status.record_count, 1)

    def test_failed_tool_is_reported_and_degrades(self) -> None:
        results = support.mock_results()
        results["query-my-account"] = ToolResult(
            tool="query-my-account", ok=False, error="模拟失败", mode="mock"
        )
        bundle = build_bundle(results, mode="mock", today=support.TODAY)
        self.assertFalse(bundle.account.present)
        # 其余数据仍然可用
        self.assertEqual(len(bundle.my_coupons), 6)
        self.assertTrue(any("取数失败" in note for note in bundle.integrity_notes()))

    def test_integrity_notes_mention_missing_fields(self) -> None:
        joined = "\n".join(self.bundle.integrity_notes())
        self.assertIn("缺失字段", joined)
        self.assertIn("MOCK-C-1005", joined)

    def test_duplicate_detection_across_sources(self) -> None:
        results = support.mock_results()
        results["available-coupons"] = ToolResult(
            tool="available-coupons",
            ok=True,
            data={"data": {"couponList": [{"couponId": "MOCK-C-1002", "couponName": "【样例】满30减8"}]}},
            mode="mock",
        )
        bundle = build_bundle(results, mode="mock", today=support.TODAY)
        self.assertTrue(bundle.available_coupons[0].duplicate_of_owned)


class TestDayHelpers(unittest.TestCase):
    def test_days_left(self) -> None:
        self.assertEqual(days_left(date(2026, 10, 12), date(2026, 10, 9)), 3)
        self.assertEqual(days_left(date(2026, 10, 9), date(2026, 10, 9)), 0)
        self.assertEqual(days_left(date(2026, 10, 4), date(2026, 10, 9)), -5)

    def test_days_left_none_when_no_expiry(self) -> None:
        self.assertIsNone(days_left(None, date(2026, 10, 9)))

    def test_humanize(self) -> None:
        self.assertEqual(humanize_days(0), "今天到期")
        self.assertEqual(humanize_days(1), "明天到期")
        self.assertEqual(humanize_days(5), "5 天后到期")
        self.assertEqual(humanize_days(-3), "已过期 3 天")
        self.assertEqual(humanize_days(None), MISSING_MARK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
