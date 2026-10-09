"""把体检结论渲染为 Markdown 权益报告。

输出契约（与 SKILL.md 一致，章节顺序固定）：
1. 元信息  2. 立即行动  3. 本周内  4. 可计划  5. 积分账户
6. 活动日历  7. 待领取（麦麦省）  8. 数据完整性与免责声明

排版原则：任何取不到的字段一律渲染为 ``[字段缺失]``，**不省略、不猜测**——
省略会让人误以为该字段不存在，填值则是编造。
"""

from __future__ import annotations

from datetime import datetime

from normalize import (
    ACCOUNT_ABSENT,
    Bundle,
    FIELD_LABELS,
    MISSING_MARK,
    PayloadState,
    humanize_days,
)
from radar import LEVEL_META, Assessment, Level, RadarResult

MODE_BANNER = {
    "mock": (
        "> ⚠️ **当前为模拟（mock）模式**：下列数据来自本地样例文件 `fixtures/`，"
        "**不是你账户的真实权益**，仅用于演示与测试。\n"
        "> 回放真实响应格式：`MCD_MOCK_FORMAT=real python scripts/run_radar.py --mode mock`。\n"
        "> 切换到真实数据：设置环境变量 `MCD_MCP_TOKEN` 并以 `--mode real` 运行。\n"
    ),
    "real": "> ✅ **当前为真实（real）模式**：数据来自麦当劳中国官方 MCP Server 实时返回。\n",
    "replay": (
        "> 📼 **当前为回放（replay）模式**：数据来自**离线回放目录**中的响应样例。\n"
        "> 本仓库自带的 `fixtures/` 是**结构逐行对标真实响应、取值全部合成**的样例"
        "（真实响应含账户数据，未随仓库分发）；走的是与线上完全相同的解析与排序链路。\n"
    ),
}

DISCLAIMER = (
    "本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。\n"
    "报告输出仅供参考，不构成任何形式的建议；餐品信息、价格、券面规则及供应状态"
    "**以麦当劳官方渠道的实时结果为准**。\n"
    "本报告为只读体检结果，未执行任何下单、领券或积分消费操作。"
)


def _cell(text: object) -> str:
    """Markdown 表格单元格转义。"""
    if text is None:
        return MISSING_MARK
    return str(text).replace("|", "\\|").replace("\n", " ").strip() or MISSING_MARK


def _num(value: float | None, unit: str = "") -> str:
    if value is None:
        return MISSING_MARK
    text = f"{value:g}"
    return f"{text}{unit}" if unit else text


def _coupon_ref(coupon: object) -> str:
    """券的定位编号：官方 ID 优先，否则用带命名空间的合成编号。"""
    return getattr(coupon, "id", None) or getattr(coupon, "ref", None) or MISSING_MARK


def _coupon_row(item: Assessment) -> str:
    coupon = item.item
    # 「剩余时间」取不到时，按来源区分措辞：
    # Markdown 正文不提供有效期 → 「未提供」；结构化返回缺字段 → 「[字段缺失]」。
    remaining = humanize_days(item.days_left) if item.days_left is not None else coupon.unknown_mark
    return (
        "| {level} | {name} | {remaining} | {benefit} | {condition} | {channel} | {ref} |".format(
            level=item.level.value,
            name=_cell(coupon.display_name),
            remaining=_cell(remaining),
            benefit=_cell(coupon.benefit_display),
            condition=_cell(coupon.condition_display),
            channel=_cell(coupon.channel_display),
            ref=_cell(_coupon_ref(coupon)),
        )
    )


_COUPON_HEADER = (
    "| 级别 | 名称 | 剩余时间 | 券面权益 | 使用条件 | 适用渠道 | 编号 |\n"
    "|:---:|---|---|---|---|---|---|"
)


def _campaign_remaining(delta: int | None) -> str:
    """活动的剩余时间用"结束"而非"到期"措辞（**仅适用于有有效期的结构化活动**）。"""
    if delta is None:
        return MISSING_MARK
    if delta < 0:
        return f"已结束 {abs(delta)} 天"
    if delta == 0:
        return "今天结束"
    if delta == 1:
        return "明天结束"
    return f"{delta} 天后结束"


def _calendar_offset(delta: int | None) -> str:
    """日历条目的相对距离。

    刻意**不使用"结束"字样**——日历日期不是截止日，写成"今天结束"就是编造。
    """
    if delta is None:
        return MISSING_MARK
    if delta < 0:
        return f"{abs(delta)} 天前"
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    return f"{delta} 天后"


def _section(title: str, items: list[Assessment], empty_hint: str) -> list[str]:
    lines = [f"### {title}", ""]
    if not items:
        lines += [f"_{empty_hint}_", ""]
        return lines
    lines += [_COUPON_HEADER]
    lines += [_coupon_row(item) for item in items]
    lines.append("")
    return lines


def _source_table(bundle: Bundle) -> list[str]:
    """数据源状态表。

    「返回格式」一列是**程序判定**的结果（见 ``normalize.observe_format``），
    不是人工声称——参赛要求核对"每个接口到底返回 JSON 还是 Markdown"。
    """
    lines = [
        "| 数据源工具 | 状态 | 返回格式 | 记录数 | 返回体量 | 说明 |",
        "|---|:---:|---|---:|---:|---|",
    ]
    for status in bundle.sources:
        if status.state is PayloadState.PARSED:
            detail = "—"
        elif status.state is PayloadState.EMPTY:
            detail = "工具返回成功，且确实没有数据"
        elif status.state is PayloadState.UNRECOGNIZED:
            detail = "**收到数据但解析失败**——不等于没有数据"
        else:
            detail = _cell(status.error)
        size = f"{status.payload_chars:,}" if status.payload_chars else "0"
        lines.append(
            f"| `{status.tool}` | {status.summary()} | {_cell(status.observed_format)} "
            f"| {status.record_count} | {size} | {detail} |"
        )
    lines.append("")
    return lines


def _urgent_bullets(items: list[Assessment]) -> list[str]:
    if not items:
        return ["**当前没有需要立即处理的权益。**", ""]
    lines = []
    for index, item in enumerate(items, 1):
        coupon = getattr(item, "item", None)
        hint = ""
        if item.kind == "coupon" and coupon is not None:
            extras = []
            if coupon.benefit_text:
                extras.append(f"券面权益 {coupon.benefit_text}")
            elif coupon.discount_value is not None:
                extras.append(f"优惠 {_num(coupon.discount_value, ' 元')}")
            if coupon.threshold is not None:
                extras.append(f"门槛 {_num(coupon.threshold, ' 元')}")
            if coupon.valid_window:
                extras.append(f"适用时段 {coupon.valid_window}")
            if coupon.channel:
                extras.append(f"渠道 {coupon.channel}")
            if coupon.ref and not coupon.id:
                extras.append(f"编号 {coupon.ref}")
            if extras:
                hint = "（" + "，".join(extras) + "）"
        lines.append(f"{index}. **{item.level.value}** — {item.name}{hint} —— {item.reason}")
    lines.append("")
    return lines


def _points_section(bundle: Bundle, radar: RadarResult) -> list[str]:
    lines = ["## 5. 积分账户", ""]
    account = bundle.account
    if not account.present:
        lines += ["**积分数据获取失败或未返回**，本板块无法评估。请检查 `query-my-account` 的取数状态。", ""]
        return lines

    lines += [
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 可用积分 | {_num(account.available)} |",
        f"| 累计积分 | {_num(account.total)} |",
        f"| 冻结积分 | {_num(account.frozen)} |",
        f"| 即将过期积分（本月） | {_num(account.expiring_points)} |",
        f"| 下月将过期积分 | {_num(account.next_expiring_points)} |",
        f"| 已使用积分 | {_num(account.used)} |",
        f"| 已过期积分 | {_num(account.expired)} |",
        f"| 过期日 | {account.expiring_date.isoformat() if account.expiring_date else MISSING_MARK} |",
        f"| 会员等级 | {_cell(account.level)} |",
        f"| 积分类型 | {_cell(account.currency)} |",
        "",
    ]
    # 接口不返回的项，明说原因——避免读成"是不是没读到"。
    absent = [key for key in ACCOUNT_ABSENT if key in account.missing]
    if absent:
        labels = "、".join(FIELD_LABELS.get(key, key) for key in absent)
        lines += [f"> ℹ️ {labels}：麦当劳积分接口不返回该字段，故记为 `{MISSING_MARK}`，未做推测。", ""]
    if account.account_id_excluded:
        lines += [
            "> 🔒 本次返回中含会员账户标识，已按隐私策略**只记录其存在、不保存取值**，"
            "报告与导出中均不出现。",
            "",
        ]
    if radar.points is not None:
        lines += [f"**体检结论**：`{radar.points.level.value}` — {radar.points.reason}", ""]
    return lines


def _campaign_section(bundle: Bundle, radar: RadarResult) -> list[str]:
    """活动日历板块。

    关键约束：**「解析失败」绝不允许被渲染成「本月没有活动」。**
    四种状态各自有独立措辞，其中只有 ``EMPTY`` 才可以说"没有活动"。
    """
    lines = ["## 6. 活动日历", ""]
    status = bundle.source("campaign-calendar")

    if not radar.campaigns:
        if status is None:
            lines += ["_本次运行未调用 `campaign-calendar`，无活动数据。_", ""]
        elif status.state is PayloadState.FAILED:
            lines += [
                f"**活动数据取数失败**：{_cell(status.error)}",
                "本板块无法评估，请修复取数问题后重跑。",
                "",
            ]
        elif status.state is PayloadState.UNRECOGNIZED:
            lines += [
                "> ⚠️ **收到数据，但解析失败。**",
                f"> `campaign-calendar` 返回了 {status.payload_chars:,} 字符内容，"
                "但本次未能从中识别出任何活动记录。",
                "> **这不代表当月没有活动**，请勿据本板块做出任何判断。",
                "> 排查方式：`python scripts/run_radar.py --mode real --dump-raw raw/`，"
                "对照 `raw/campaign-calendar.raw.json` 的实际结构修正解析器。",
                "",
            ]
        elif status.state is PayloadState.EMPTY:
            lines += ["_工具返回成功，且本次确实没有任何活动数据（本月无活动）。_", ""]
        else:  # pragma: no cover - 防御性
            lines += ["_未获取到活动数据。_", ""]
        return lines

    if status is not None and status.state is PayloadState.UNRECOGNIZED:  # pragma: no cover
        lines += [
            "> ⚠️ 部分活动已解析，但本次响应中仍有内容未能识别，可能存在遗漏。",
            "",
        ]

    # 两类来源语义不同（有效期 vs 日历日），分开成表，避免同一张表混用两种列含义。
    markdown_items = [i for i in radar.campaigns if i.item.date_source == "markdown"]
    json_items = [i for i in radar.campaigns if i.item.date_source != "markdown"]

    if markdown_items:
        lines += [
            "> ℹ️ 官方活动日历按**日期**归档，**不提供活动的有效期**。下表的「日历日」是该活动"
            "在日历中出现的日期，**不是截止日**，请勿据此判断活动还剩几天。",
            "> 官方原文只对「往期回顾」「今日」给出分组标签，未来日期无标签，故记为 `—`。",
            "",
            "| 日历状态 | 活动 | 日历日 | 官方分组 | 距今 |",
            "|:---:|---|---|---|---|",
        ]
        for item in markdown_items:
            campaign = item.item
            day = campaign.calendar_date or campaign.start
            lines.append(
                f"| {item.level.value} | {_cell(campaign.display_name)} "
                f"| {_cell(day.isoformat() if day else MISSING_MARK)} "
                f"| {_cell(campaign.group_label or '—')} | {_cell(_calendar_offset(item.days_left))} |"
            )
        lines.append("")
        lines += [
            f"_共 {len(markdown_items)} 条日历条目。同一条活动可能在多个日期下重复出现"
            "（官方日历即为如此），本技能**未做去重合并**，以免丢失官方原始信息。_",
            "",
        ]

    if json_items:
        if markdown_items:
            lines += ["**另有带有效期的结构化活动：**", ""]
        lines += ["| 级别 | 活动 | 起止 | 剩余 |", "|:---:|---|---|---|"]
        for item in json_items:
            campaign = item.item
            span = " ~ ".join(
                [campaign.start.isoformat() if campaign.start else MISSING_MARK,
                 campaign.end.isoformat() if campaign.end else MISSING_MARK]
            )
            lines.append(
                f"| {item.level.value} | {_cell(campaign.display_name)} | {_cell(span)} "
                f"| {_cell(_campaign_remaining(item.days_left))} |"
            )
        lines.append("")
    return lines


def _claimable_section(radar: RadarResult) -> list[str]:
    lines = [
        "## 7. 待领取（麦麦省）",
        "",
        "> 🔒 本技能**不会**代为领券。以下仅为可领取项排序，请在麦当劳 App 内自行领取。",
        "",
    ]
    fresh = [item for item in radar.claimable if not getattr(item.item, "duplicate_of_owned", False)]
    owned = [item for item in radar.claimable if getattr(item.item, "duplicate_of_owned", False)]

    # 可领取列表中会混有「已领取」的条目（官方正文如实标注了状态），
    # 这类既不该算作"待领取"，也不该被悄悄丢掉——单独说明。
    already = [i for i in fresh if (getattr(i.item, "status", None) or "") == "已领取"]
    fresh = [i for i in fresh if (getattr(i.item, "status", None) or "") != "已领取"]

    if not fresh:
        lines += ["_没有新的可领取券。_", ""]
    else:
        lines += [_COUPON_HEADER]
        lines += [_coupon_row(item) for item in fresh]
        lines.append("")
    if already:
        lines += [
            f"_另有 {len(already)} 条在该列表中状态为「已领取」——你已持有，未按待领取处理。_",
            "",
        ]
    if owned:
        lines += [f"_其中 {len(owned)} 张你已持有，未重复列出。_", ""]
    return lines


def _integrity_section(bundle: Bundle, radar: RadarResult) -> list[str]:
    lines = ["## 8. 数据完整性与免责声明", ""]

    unknown_keys = sorted({k for status in bundle.sources for k in status.unknown_keys if k})
    if unknown_keys:
        lines += [
            f"**顶层字段核对**：本次返回中出现以下顶层字段，尚未被规范化映射："
            f"`{'`, `'.join(unknown_keys)}`。",
            "",
        ]

    unrecognized = [s for s in bundle.sources if s.state is PayloadState.UNRECOGNIZED]
    if unrecognized:
        lines += [
            "> 🚨 **有数据源返回了内容，但解析器未能读懂。**"
            "此时「没有数据」的结论**不成立**，相关板块的空白不代表权益不存在。",
            "",
        ]

    notes = bundle.integrity_notes()
    if notes:
        lines += ["**本次发现的缺失 / 异常 / 来源说明**：", ""]
        lines += [f"- {note}" for note in notes]
        lines.append("")
    else:
        lines += ["**未发现字段缺失。**", ""]

    unknown_level = [a for a in radar.coupons if a.level is Level.UNKNOWN]
    if unknown_level:
        lines += [
            f"**其中 {len(unknown_level)} 条因缺少到期日无法排序**，已单列于 UNKNOWN 级别，"
            "请在 App 内自行确认，请勿视作永久有效。",
            "",
        ]

    lines += ["---", "", DISCLAIMER, ""]
    return lines


def _campaign_count_cell(bundle: Bundle, radar: RadarResult) -> str:
    """元信息里的活动条数。

    解析失败或取数失败时**绝不显示 0**——"0"会被直接读成"本月没有活动"，
    而那正是我们要消除的误导。
    """
    if radar.campaigns:
        return str(len(radar.campaigns))
    status = bundle.source("campaign-calendar")
    if status is None:
        return "未查询"
    if status.state is PayloadState.UNRECOGNIZED:
        return f"解析失败（原文 {status.payload_chars:,} 字符，非 0）"
    if status.state is PayloadState.FAILED:
        return "取数失败"
    return "0"


def render_report(bundle: Bundle, radar: RadarResult) -> str:
    """渲染完整 Markdown 报告。"""
    generated = bundle.generated_at.strftime("%Y-%m-%d %H:%M:%S")
    counts = radar.counts
    total = len(radar.coupons)

    lines: list[str] = [
        "# 超麦权益雷达 · 权益体检报告",
        "",
        MODE_BANNER.get(bundle.mode, "").rstrip(),
        "",
        "## 1. 元信息",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 生成时间 | {generated} |",
        f"| 数据模式 | `{bundle.mode}` |",
        f"| 基准日（用于计算剩余天数） | {bundle.today.isoformat()} |",
        f"| 我的优惠券总数 | {total} |",
        f"| 其中 P0 / P1 | {counts.get('P0', 0)} / {counts.get('P1', 0)} |",
        f"| 可领取（麦麦省） | {len(radar.claimable)} |",
        f"| 活动 | {_campaign_count_cell(bundle, radar)} |",
        "",
        "**数据源状态**",
        "",
        *_source_table(bundle),
        "> 表格约定：`[字段缺失]` 表示**该字段取不到**；`未提供` 表示**官方返回格式本身不含该字段**。",
        "> 两者都**不等于 0、也不代表该权益不存在**，且一律不做推测填充。",
        "",
        "## 2. 立即行动（P0 / P1）",
        "",
        "> 这些权益在 3 天内到期（或积分即将过期），建议优先处理。",
        "",
        *_urgent_bullets(radar.urgent),
        "## 3. 本周内到期（P2）",
        "",
        *_section("4–7 天内到期", radar.by_level({Level.P2}), "本周内没有到期的券。"),
        "## 4. 可计划与待确认（P3 / P4 / UNKNOWN）",
        "",
        *_section("8 天以上到期", radar.by_level({Level.P3, Level.P4}), "较长期限内没有到期的券。"),
        *_section(
            "信息不足 · 无法排序（UNKNOWN）",
            radar.by_level({Level.UNKNOWN}),
            "所有券的到期日均已获取。",
        ),
        *_points_section(bundle, radar),
        *_campaign_section(bundle, radar),
        *_claimable_section(radar),
        *_integrity_section(bundle, radar),
    ]

    expired = radar.by_level({Level.EXPIRED})
    if expired:
        lines += [
            "## 附录：已过期（仅归档）",
            "",
            *_section(f"共 {len(expired)} 张", expired, "无。"),
        ]

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def summarize(bundle: Bundle, radar: RadarResult) -> str:
    """终端用的一句话摘要（不含任何敏感信息）。"""
    counts = radar.counts
    unread = sum(1 for status in bundle.sources if not status.ok)
    unparsed = sum(1 for status in bundle.sources if status.state is PayloadState.UNRECOGNIZED)
    return (
        f"[{bundle.mode}] 券 {len(radar.coupons)} 张 | "
        f"P0={counts.get('P0', 0)} P1={counts.get('P1', 0)} P2={counts.get('P2', 0)} "
        f"P3={counts.get('P3', 0)} P4={counts.get('P4', 0)} UNKNOWN={counts.get('UNKNOWN', 0)} "
        f"EXPIRED={counts.get('EXPIRED', 0)} | 可领取 {len(radar.claimable)} | "
        f"活动 {len(radar.campaigns)} | 取数失败 {unread} | 解析失败 {unparsed}"
    )


__all__ = ["DISCLAIMER", "MODE_BANNER", "render_report", "summarize"]
