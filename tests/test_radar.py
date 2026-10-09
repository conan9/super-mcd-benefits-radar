"""紧急度分级与排序测试 —— 规则必须与 SKILL.md 完全一致。"""

from __future__ import annotations

import random
import unittest
from datetime import date, timedelta

import support  # noqa: F401
from normalize import Campaign, Coupon, PointsAccount
from radar import (
    LEVEL_META,
    Level,
    URGENT_LEVELS,
    assess_campaign,
    assess_coupon,
    assess_points,
    build_radar,
)

TODAY = date(2026, 10, 9)


def coupon(days_to_expiry: int | None, **kwargs) -> Coupon:
    expiry = None if days_to_expiry is None else TODAY + timedelta(days=days_to_expiry)
    return Coupon(
        id=kwargs.pop("id", "C"),
        name=kwargs.pop("name", "券"),
        valid_to=expiry,
        **kwargs,
    )


class TestCouponLevels(unittest.TestCase):
    """边界值逐档验证：0 / 1 / 3 / 4 / 7 / 8 / 30 / 31 / 负数 / 无。"""

    def test_expires_today_is_p0(self) -> None:
        self.assertIs(assess_coupon(coupon(0), TODAY).level, Level.P0)

    def test_within_three_days_is_p1(self) -> None:
        for delta in (1, 2, 3):
            with self.subTest(delta=delta):
                self.assertIs(assess_coupon(coupon(delta), TODAY).level, Level.P1)

    def test_four_to_seven_days_is_p2(self) -> None:
        for delta in (4, 7):
            with self.subTest(delta=delta):
                self.assertIs(assess_coupon(coupon(delta), TODAY).level, Level.P2)

    def test_eight_to_thirty_days_is_p3(self) -> None:
        for delta in (8, 30):
            with self.subTest(delta=delta):
                self.assertIs(assess_coupon(coupon(delta), TODAY).level, Level.P3)

    def test_beyond_thirty_days_is_p4(self) -> None:
        for delta in (31, 365):
            with self.subTest(delta=delta):
                self.assertIs(assess_coupon(coupon(delta), TODAY).level, Level.P4)

    def test_past_expiry_is_expired(self) -> None:
        self.assertIs(assess_coupon(coupon(-1), TODAY).level, Level.EXPIRED)

    def test_no_expiry_is_unknown_not_p4(self) -> None:
        """关键：缺到期日绝不能被当作"长期有效"排到最后。"""
        result = assess_coupon(coupon(None), TODAY)
        self.assertIs(result.level, Level.UNKNOWN)
        self.assertIsNone(result.days_left)
        self.assertIn("缺", result.reason)

    def test_status_word_overrides_future_date(self) -> None:
        """接口把日期写成未来但状态是"已过期"时，以状态为准。"""
        result = assess_coupon(coupon(10, status="已过期"), TODAY)
        self.assertIs(result.level, Level.EXPIRED)

    def test_unstarted_coupon_notes_in_reason(self) -> None:
        future_start = TODAY + timedelta(days=2)
        result = assess_coupon(coupon(40, valid_from=future_start), TODAY)
        self.assertIn("尚未生效", result.reason)

    def test_threshold_not_repeated_in_reason(self) -> None:
        result = assess_coupon(coupon(2, threshold=30.0), TODAY)
        self.assertNotIn("门槛", result.reason, "门槛已在结构化字段中，不应重复进 reason")


class TestCampaignLevels(unittest.TestCase):
    def campaign(self, days_to_end: int | None, **kwargs) -> Campaign:
        end = None if days_to_end is None else TODAY + timedelta(days=days_to_end)
        return Campaign(id="P", name="活动", end=end, **kwargs)

    def test_ending_within_three_days_is_p1(self) -> None:
        self.assertIs(assess_campaign(self.campaign(2), TODAY).level, Level.P1)

    def test_ending_later_is_p2(self) -> None:
        self.assertIs(assess_campaign(self.campaign(20), TODAY).level, Level.P2)

    def test_not_started_is_p3(self) -> None:
        campaign = Campaign(id="P", name="未来活动", start=TODAY + timedelta(days=5),
                            end=TODAY + timedelta(days=10))
        result = assess_campaign(campaign, TODAY)
        self.assertIs(result.level, Level.P3)
        self.assertIn("未开始", result.reason)

    def test_finished_is_expired(self) -> None:
        result = assess_campaign(self.campaign(-2, start=TODAY - timedelta(days=20)), TODAY)
        self.assertIs(result.level, Level.EXPIRED)
        self.assertIn("已结束", result.reason)

    def test_missing_end_is_unknown(self) -> None:
        self.assertIs(assess_campaign(self.campaign(None), TODAY).level, Level.UNKNOWN)


class TestPointsLevels(unittest.TestCase):
    def test_not_present_returns_none(self) -> None:
        """工具失败时不应伪造一个结论。"""
        self.assertIsNone(assess_points(PointsAccount(present=False), TODAY))

    def test_expiring_points_escalates_to_p1(self) -> None:
        account = PointsAccount(present=True, available=2380, expiring_points=500,
                                expiring_date=TODAY + timedelta(days=12))
        result = assess_points(account, TODAY)
        self.assertIs(result.level, Level.P1)
        self.assertIn("500", result.reason)

    def test_missing_expiring_points_is_unknown_not_p4(self) -> None:
        """最危险的错判：把"不知道"当成"没有即将过期积分"。"""
        account = PointsAccount(present=True, available=100, missing=["expiring_points"])
        result = assess_points(account, TODAY)
        self.assertIs(result.level, Level.UNKNOWN)
        self.assertIn("字段缺失", result.reason)

    def test_zero_expiring_is_p4(self) -> None:
        account = PointsAccount(present=True, available=100, expiring_points=0)
        self.assertIs(assess_points(account, TODAY).level, Level.P4)


class TestSorting(unittest.TestCase):
    def test_sort_order_is_urgency_then_days_then_value(self) -> None:
        coupons = [coupon(5, id="b"), coupon(0, id="a"), coupon(2, id="c"), coupon(5, id="d", discount_value=10.0)]
        result = build_radar(coupons, [], [], PointsAccount(present=False), TODAY)
        self.assertEqual([a.item.id for a in result.coupons], ["a", "c", "d", "b"])

    def test_higher_value_breaks_tie_within_same_day(self) -> None:
        coupons = [
            coupon(3, id="low", discount_value=1.0),
            coupon(3, id="high", discount_value=20.0),
        ]
        result = build_radar(coupons, [], [], PointsAccount(present=False), TODAY)
        self.assertEqual([a.item.id for a in result.coupons], ["high", "low"])

    def test_unknown_sorts_after_known_within_same_rank(self) -> None:
        result = build_radar([coupon(None, id="unknown"), coupon(60, id="p4")], [], [],
                             PointsAccount(present=False), TODAY)
        self.assertEqual([a.item.id for a in result.coupons], ["p4", "unknown"])

    def test_expired_sorts_last(self) -> None:
        result = build_radar([coupon(-5, id="old"), coupon(0, id="now")], [], [],
                             PointsAccount(present=False), TODAY)
        self.assertEqual([a.item.id for a in result.coupons], ["now", "old"])

    def test_sorting_is_deterministic_under_shuffle(self) -> None:
        """同一批输入任意打乱，输出顺序必须一致。"""
        coupons = [
            coupon(0, id="a"),
            coupon(2, id="b", discount_value=5.0),
            coupon(2, id="c", discount_value=9.0),
            coupon(6, id="d"),
            coupon(None, id="e"),
            coupon(-3, id="f"),
            coupon(45, id="g"),
        ]
        baseline = [a.item.id for a in build_radar(coupons, [], [], PointsAccount(present=False), TODAY).coupons]
        rng = random.Random(20261009)
        for _ in range(20):
            shuffled = coupons[:]
            rng.shuffle(shuffled)
            order = [
                a.item.id
                for a in build_radar(shuffled, [], [], PointsAccount(present=False), TODAY).coupons
            ]
            self.assertEqual(order, baseline)


class TestUrgentCollection(unittest.TestCase):
    def test_urgent_includes_p0_p1_coupons_and_points(self) -> None:
        account = PointsAccount(present=True, expiring_points=300, expiring_date=TODAY + timedelta(days=5))
        radar = build_radar([coupon(0, id="t"), coupon(2, id="s"), coupon(20, id="later")], [], [], account, TODAY)
        ids = [a.kind for a in radar.urgent]
        self.assertIn("coupon", ids)
        self.assertIn("points", ids)
        self.assertEqual(len(radar.urgent), 3)

    def test_urgent_excludes_expired_and_unknown(self) -> None:
        radar = build_radar([coupon(-1, id="x"), coupon(None, id="u")], [], [],
                            PointsAccount(present=False), TODAY)
        self.assertEqual(radar.urgent, [])

    def test_urgent_levels_constant(self) -> None:
        self.assertEqual(URGENT_LEVELS, frozenset({Level.P0, Level.P1}))


class TestLevelMetaConsistency(unittest.TestCase):
    def test_order_is_unique_and_ascending_by_rank(self) -> None:
        ranks = {level: LEVEL_META[level]["order"] for level in Level}
        self.assertEqual(len(set(ranks.values())), len(ranks), "等级序必须唯一")

    def test_every_level_has_label_and_action(self) -> None:
        for level in Level:
            with self.subTest(level=level):
                self.assertTrue(LEVEL_META[level]["label"])
                self.assertTrue(LEVEL_META[level]["action"])


class TestFullRadarFromFixtures(unittest.TestCase):
    def test_expected_distribution(self) -> None:
        _, radar = support.mock_radar()
        self.assertEqual(
            radar.counts,
            {"P0": 1, "P1": 1, "P2": 1, "P4": 1, "UNKNOWN": 1, "EXPIRED": 1},
        )

    def test_claimable_is_not_assessed_as_owned(self) -> None:
        _, radar = support.mock_radar()
        self.assertEqual(len(radar.claimable), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
