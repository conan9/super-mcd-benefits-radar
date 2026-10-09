"""紧急度评分与排序 —— 纯 Python 标准库实现。

规则与 SKILL.md 中"紧急度分级规则"一节严格一致，改动规则须同步改文档与测试。

* 基准日 ``today`` 由调用方注入，便于测试锁定"今天"。
* 无到期日 → ``UNKNOWN``，**不猜测**、不假定为"永久有效"。
* 排序键 ``(等级序, 剩余天数升序, 优惠值降序, 名称升序)``，
  剩余天数缺失时以哨兵值排在同级末尾。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Iterable

from normalize import Campaign, Coupon, MISSING_MARK, PointsAccount, days_left, humanize_days

#: 剩余天数缺失时的排序哨兵
_DAYS_SENTINEL = 10**6

_EXPIRED_STATUS_WORDS = ("过期", "失效", "已使用", "used", "expired", "invalid")


class Level(str, Enum):
    """紧急度等级。

    前 7 个用于"有明确到期日"的权益（券、积分、结构化活动）。
    后 3 个是**活动日历专用**：官方 Markdown 日历只给出"这条活动出现在哪一天"，
    不给出有效期，因此不能用"到期紧急度"表述——否则等于编造"今天结束"。
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    TODAY = "TODAY"
    UPCOMING = "UPCOMING"
    PAST = "PAST"


#: 展示与排序用的等级元信息
LEVEL_META: dict[Level, dict[str, Any]] = {
    Level.P0: {"label": "P0 · 今天到期", "order": 0, "action": "立即使用，过期作废"},
    Level.P1: {"label": "P1 · 3 天内到期", "order": 1, "action": "尽快安排，优先于其他权益"},
    Level.P2: {"label": "P2 · 本周内到期", "order": 2, "action": "本周内排一次用餐"},
    Level.P3: {"label": "P3 · 本月内到期", "order": 3, "action": "可计划，留意时间"},
    Level.P4: {"label": "P4 · 时间充裕", "order": 4, "action": "正常使用即可"},
    Level.UNKNOWN: {"label": "UNKNOWN · 信息不足", "order": 5, "action": "缺到期日，请在 App 内确认"},
    Level.EXPIRED: {"label": "EXPIRED · 已过期", "order": 6, "action": "仅归档，不再提醒"},
    # 日历专用等级单独占用 10+ 号段，不与到期紧急度抢号码：
    # 两套语义互不相干，但排序号保持全局唯一，避免同一报告内排序歧义。
    Level.TODAY: {"label": "TODAY · 今日日历", "order": 10, "action": "查看活动详情"},
    Level.UPCOMING: {"label": "UPCOMING · 日历未来日", "order": 12, "action": "留意开始时间"},
    Level.PAST: {"label": "PAST · 日历往期日", "order": 16, "action": "仅归档"},
}

#: 仅用于活动日历（Markdown）的等级集合
CALENDAR_LEVELS: frozenset[Level] = frozenset({Level.TODAY, Level.UPCOMING, Level.PAST})

URGENT_LEVELS: frozenset[Level] = frozenset({Level.P0, Level.P1})


@dataclass
class Assessment:
    """一条权益的体检结论。"""

    kind: str  # coupon | campaign | points
    item: Any
    level: Level
    days_left: int | None
    reason: str
    value: float | None = None
    name: str = ""

    @property
    def order(self) -> int:
        return LEVEL_META[self.level]["order"]

    @property
    def action(self) -> str:
        return LEVEL_META[self.level]["action"]

    @property
    def sort_key(self) -> tuple:
        return (
            self.order,
            self.days_left if self.days_left is not None else _DAYS_SENTINEL,
            -(self.value or 0.0),
            self.name,
        )

    @property
    def is_urgent(self) -> bool:
        return self.level in URGENT_LEVELS

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "level": self.level.value,
            "days_left": self.days_left,
            "reason": self.reason,
            "value": self.value,
        }


def _coupon_value(coupon: Coupon) -> float | None:
    """优惠力度：优先取折扣值；缺失返回 ``None``（排序时按 0 兜底，展示时仍标缺失）。"""
    return coupon.discount_value


def _status_says_expired(status: str | None) -> bool:
    if not status:
        return False
    lowered = status.lower()
    return any(word in lowered for word in _EXPIRED_STATUS_WORDS)


def assess_coupon(coupon: Coupon, today: date) -> Assessment:
    """判定单张券的紧急度。"""
    delta = days_left(coupon.valid_to, today)
    name = coupon.display_name
    value = _coupon_value(coupon)

    if delta is None:
        return Assessment(
            kind="coupon",
            item=coupon,
            level=Level.UNKNOWN,
            days_left=None,
            # 措辞跟随来源：Markdown 正文不提供有效期 → 「未提供」；
            # 结构化返回缺字段 → 「[字段缺失]」。与报告表格保持同一口径。
            reason=f"缺少到期日，无法判断紧急度（{coupon.unknown_mark}）",
            value=value,
            name=name,
        )

    if delta < 0 or _status_says_expired(coupon.status):
        return Assessment(
            kind="coupon",
            item=coupon,
            level=Level.EXPIRED,
            days_left=delta,
            reason=f"已过期（{humanize_days(delta)}）",
            value=value,
            name=name,
        )

    if delta == 0:
        level = Level.P0
    elif delta <= 3:
        level = Level.P1
    elif delta <= 7:
        level = Level.P2
    elif delta <= 30:
        level = Level.P3
    else:
        level = Level.P4

    reason = humanize_days(delta)
    if coupon.valid_from and coupon.valid_from > today:
        reason += f"；尚未生效（{coupon.valid_from} 起）"
    return Assessment(
        kind="coupon",
        item=coupon,
        level=level,
        days_left=delta,
        reason=reason,
        value=value,
        name=name,
    )


def _assess_calendar_campaign(campaign: Campaign, today: date) -> Assessment:
    """官方活动日历（Markdown）条目的评估。

    **不得使用到期紧急度措辞。** 官方日历只回答"这条活动出现在哪一天"，
    不回答"什么时候结束"。把它渲染成"今天结束"是编造：

    * 9.9 元早餐两件套在 2026-10-09 被标注为「今日」，而其售卖期是 10-08 至 10-21；
    * 「往期回顾」只表示该条已归档，不代表活动本身已结束。

    因此这里改用日历语义（今日 / 未来日 / 往期日），并保留官方原始分组标签。
    """
    day = campaign.calendar_date or campaign.start
    name = campaign.display_name
    delta = days_left(day, today)

    if delta is None:
        return Assessment(
            "campaign", campaign, Level.UNKNOWN, None, f"缺少日历日期（{MISSING_MARK}）", None, name
        )
    if delta < 0:
        reason = f"日历日 {day} · {abs(delta)} 天前的往期条目"
        return Assessment("campaign", campaign, Level.PAST, delta, reason, None, name)
    if delta == 0:
        reason = f"官方标注「{campaign.group_label}」" if campaign.group_label else "日历日为今天"
        return Assessment("campaign", campaign, Level.TODAY, 0, reason, None, name)
    reason = f"日历日 {day} · {delta} 天后"
    return Assessment("campaign", campaign, Level.UPCOMING, delta, reason, None, name)


def assess_campaign(campaign: Campaign, today: date) -> Assessment:
    """判定一个活动的紧急度。

    按 ``date_source`` 分流：结构化数据用有效期算紧急度；
    Markdown 日历只有归档日期，改用日历语义（见 :func:`_assess_calendar_campaign`）。
    """
    if campaign.date_source == "markdown":
        return _assess_calendar_campaign(campaign, today)

    delta = days_left(campaign.end, today)
    name = campaign.display_name

    if delta is None:
        return Assessment("campaign", campaign, Level.UNKNOWN, None, f"缺少结束日（{MISSING_MARK}）", None, name)

    started = campaign.start is None or campaign.start <= today
    if not started:
        return Assessment(
            "campaign",
            campaign,
            Level.P3,
            delta,
            f"未开始（{campaign.start} 起），{humanize_days(delta).replace('到期', '结束')}",
            None,
            name,
        )
    if delta < 0:
        return Assessment("campaign", campaign, Level.EXPIRED, delta, f"已结束（{abs(delta)} 天前）", None, name)

    level = Level.P1 if delta <= 3 else Level.P2
    return Assessment("campaign", campaign, level, delta, humanize_days(delta).replace("到期", "结束"), None, name)


def assess_points(account: PointsAccount, today: date) -> Assessment | None:
    """积分账户的紧急度。

    * 工具未取到数据 → 返回 ``None``（由报告层写"数据获取失败"）。
    * 「即将过期积分」字段缺失 → ``UNKNOWN``，**不得**当作 0。
    * 即将过期积分 > 0 → ``P1``（依据 SKILL.md 规则）。
    """
    if not account.present:
        return None

    if "expiring_points" in account.missing or account.expiring_points is None:
        return Assessment(
            "points",
            account,
            Level.UNKNOWN,
            days_left(account.expiring_date, today),
            f"「即将过期积分」字段缺失（{MISSING_MARK}），无法判断积分过期风险",
            None,
            "积分账户",
        )

    if account.expiring_points <= 0:
        return Assessment(
            "points",
            account,
            Level.P4,
            days_left(account.expiring_date, today),
            "无即将过期积分",
            account.expiring_points,
            "积分账户",
        )

    delta = days_left(account.expiring_date, today)
    reason = f"{account.expiring_points:g} 积分即将过期"
    reason += f"（{humanize_days(delta).replace('到期', '过期')}）" if delta is not None else f"（过期日{MISSING_MARK}）"
    return Assessment("points", account, Level.P1, delta, reason, account.expiring_points, "积分账户")


@dataclass
class RadarResult:
    """一次体检的全部结论。"""

    today: date
    coupons: list[Assessment] = field(default_factory=list)
    claimable: list[Assessment] = field(default_factory=list)
    campaigns: list[Assessment] = field(default_factory=list)
    points: Assessment | None = None

    def by_level(self, levels: Iterable[Level]) -> list[Assessment]:
        wanted = set(levels)
        return [a for a in sorted(self.coupons, key=lambda x: x.sort_key) if a.level in wanted]

    @property
    def urgent(self) -> list[Assessment]:
        """立即行动：P0 + P1（券 + 积分）。"""
        items = [*self.by_level(URGENT_LEVELS)]
        if self.points is not None and self.points.is_urgent:
            items.append(self.points)
        return sorted(items, key=lambda x: x.sort_key)

    @property
    def counts(self) -> dict[str, int]:
        counter: dict[str, int] = {}
        for item in self.coupons:
            counter[item.level.value] = counter.get(item.level.value, 0) + 1
        return counter


def build_radar(coupons: list[Coupon], claimable: list[Coupon], campaigns: list[Campaign],
                account: PointsAccount, today: date) -> RadarResult:
    """对全部权益做体检并排序。"""
    return RadarResult(
        today=today,
        coupons=sorted((assess_coupon(c, today) for c in coupons), key=lambda x: x.sort_key),
        claimable=sorted((assess_coupon(c, today) for c in claimable), key=lambda x: x.sort_key),
        campaigns=sorted((assess_campaign(c, today) for c in campaigns), key=lambda x: x.sort_key),
        points=assess_points(account, today),
    )


__all__ = [
    "Assessment",
    "CALENDAR_LEVELS",
    "Level",
    "LEVEL_META",
    "RadarResult",
    "URGENT_LEVELS",
    "assess_campaign",
    "assess_coupon",
    "assess_points",
    "build_radar",
]
