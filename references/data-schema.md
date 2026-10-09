# 数据字典（规范化结构）

> ⚠️ **本文件由 `scripts/dump_schema.py` 从 `scripts/normalize.py` 自动生成，请勿手工编辑。**
> 修改字段映射请改代码，然后运行 `python scripts/dump_schema.py` 重新生成。

## 四个工具的真实响应格式

2026-10-09 对官方 MCP Server 的真实调用结果（结论摘要见
`references/live-verification.md`）。**格式由程序判定**（`normalize.observe_format`），
不是人工声称：

| 工具 | 真实格式 | 解析入口 |
|---|---|---|
| `query-my-coupons` | Markdown：`## 券名` + `- **字段**: 值` | `parse_coupon_markdown()` |
| `query-my-account` | 说明性文本 + **内嵌 JSON**（`## Original Response` 之后） | `extract_embedded_json()` |
| `available-coupons` | Markdown：`- 优惠券标题：… \` 行尾反斜杠续行 | `parse_available_coupons_markdown()` |
| `campaign-calendar` | Markdown：`#### 日期` 分组 + 条目 | `parse_campaign_markdown()` |

**四个工具同时保留 JSON 结构解析能力**：`find_records()` 先走结构化路径，
只有在"结构化路径解析出零条记录"时才回退到文本解析器。因此官方把返回改回 JSON 也不会失效。

## 关于字段映射的诚实说明

别名列中带 ✅ 的是**已在真实返回中实际观测到**的字段名；其余是**按语义推测的兼容别名**，
用于接口字段改名时不至于完全失联，**未经实测**。

**真实返回里根本没有的字段不会出现在别名表里**，而是列在「格式不提供的字段」一节——
报告一律记为 `[字段缺失]`，绝不推测、绝不用 0 顶替。

## 缺失与解析失败

| 情况 | 结果 | 报告呈现 |
|---|---|---|
| 别名全部未命中 | 字段为 `None`，记入 `missing` | `[字段缺失]` |
| 命中但值为 `null` / 空串 | 同上 | `[字段缺失]` |
| 日期无法解析 | 字段为 `None`，记入 `missing` | `[字段缺失]` |
| 数值字符串含多个数字（如 `满30减8`） | 返回 `None`，记入 `missing` | `[字段缺失]` |
| 接口本身不返回该字段 | 记入 `SourceStatus.absent_fields`（格式属性，不逐条报警） | `[字段缺失]` + 数据源说明一次 |
| **响应有内容但解析器读不懂** | 记 `UNRECOGNIZED` | **"收到数据，但解析失败"**（禁止说"没有数据"） |

日期解析支持：`2026-10-25`、`2026-10-25 23:59:59`、`2026-10-25T10:00:00+08:00`、
`2026/10/25`、`2026.10.25`、`2026年10月25日`、`20261025`、10 位秒级与 13 位毫秒级时间戳。

**到期判定基准取北京时间**（`normalize.today_beijing()`，固定 UTC+8）：
官方有效期以北京时间书写，若用本机 `date.today()`，
在东八区凌晨或跨时区机器上会把"今天到期"算成"明天到期"。

## 金额语义：`benefit_kind` —— 为什么不能只有一个 `discount_value`

真实返回把券面权益写成 `¥9.9 (用券价格)`，含义是**用券后实付 9.9 元**，
**不是"省 9.9 元"**。若直接塞进 `discount_value`，报告就会显示"优惠 9.9 元"——那是编造。

因此：

| `benefit_kind` | 含义 | `price` | `discount_value` |
|---|---|---|---|
| `price` | 原文标注为"用券价格/券后价/到手价" | 有值 | 保持 `[字段缺失]` |
| `discount` | 原文含"减 / 省 / 抵扣 / 返"等减免字样 | `None` | 有值 |
| `unknown` | 判不准（如"买一送一""免费""8折"） | `None` | 保持 `[字段缺失]` |

`benefit_text` 始终保留官方原文，**任何情况下都不做换算**。

## 活动日历：两种来源

| 来源 | `date_source` | 字段 | 分级 |
|---|---|---|---|
| 结构化 JSON | `json` | 显式 `start` / `end` 有效期 | `P1` / `P2` / `P3` / `EXPIRED` |
| **官方 Markdown 正文** | `markdown` | 只有 `calendar_date`（归档日）+ `group_label` | `TODAY` / `UPCOMING` / `PAST` |

官方活动日历的**真实返回是 Markdown 正文**（已实测，基准存于 `fixtures/campaign_calendar.md`），
按日期分组，每条含 `活动标题` / `活动内容介绍` / `活动图片介绍`。

⚠️ Markdown 来源**不提供有效期**，因此：

* 报告中写的是「日历日」而非「起止」，**不是截止日**；
* **禁止**出现"今天结束 / 已结束"等措辞——那会把"出现在今天的日历上"曲解成"今天到期"；
* 官方**不提供活动ID**，`MD-YYYYMMDD-NN` 是解析生成的**定位编号**（`synthetic_id=True`），不是官方 ID；
* 官方只对「往期回顾」「今日」给出分组标签，未来日期无标签，记为 `—`，**不计入 `missing`**。


## 优惠券 `Coupon` · JSON 路径

| 规范字段 | 中文名 | 别名（按优先级） |
|---|---|---|
| `id` | 券ID | `couponId` / `coupon_id` / `couponCode` / `id` / `code` |
| `name` | 名称 | `couponName` / `name` / `couponTitle` / `title` / `description` / `desc` |
| `coupon_type` | 类型 | `couponType` / `coupon_type` / `type` / `category` |
| `discount_value` | 优惠值 | `discountValue` / `discountAmount` / `reduceAmount` / `discount` / `value` / `amount` |
| `threshold` | 门槛 | `thresholdAmount` / `threshold` / `minAmount` / `conditionAmount` / `limitAmount` |
| `valid_from` | 生效日 | `startDate` / `validFrom` / `beginTime` / `startTime` / `effectiveTime` |
| `valid_to` | 到期日 | `endDate` / `validTo` / `expireTime` / `endTime` / `expireDate` / `deadline` |
| `channel` | 适用渠道 | `useChannel` / `channel` / `useScene` / `scene` |
| `status` | 状态 | `couponStatus` / `status` / `state` |

### 券 · Markdown 来源专属字段

官方「我的优惠券」返回 Markdown 正文时，由 `parse_coupon_markdown()` 填充下列字段。
它们**不来自 JSON 字段别名**，而是解析产物，因此单独列出。

| 规范字段 | 中文名 | 解析来源 |
|---|---|---|
| `benefit_text` | 券面权益原文 | `_benefitText`（原文照登，不换算） |
| `benefit_kind` | 权益类型 price/discount/unknown | `_benefitKind` |
| `price` | 用券价格（仅 kind=price） | `_price` |
| `tags` | 官方标签（如「今日到期」） | `_tags` |
| `valid_window` | 适用时段原文（如「周一、二、三、四、五 10:30-23:59」） | `_validWindow` |
| `received_text` | 领取时间原文（如「4日前收到」） | `_receivedText` |
| `image` | 券图地址 | `_image` |
| `source_format` | 来源（json / markdown） | `_source` |
| `ref` | 定位编号（非官方ID） | 由 `build_bundle()` 分配 |
| `synthetic_id` | 定位编号标记（非官方ID） | `_syntheticId` |

### 券 · 「已领取」与「可领取」

`available-coupons` 的正文会**同时包含** `状态：已领取` 与 `状态：可领取` 两种条目。
本技能按状态区分：只有 `可领取` 才进入「待领取」板块；
`已领取` 的记入 `duplicate_of_owned` 或单独说明，**不会被算作待领取**。

## 活动 `Campaign`

| 规范字段 | 中文名 | 别名（按优先级） |
|---|---|---|
| `id` | 活动ID | `campaignId` / `activityId` / `id` / `code` |
| `name` | 名称 | `campaignName` / `activityName` / `name` / `title` |
| `start` | 开始日 | `startDate` / `startTime` / `beginTime` / `validFrom` |
| `end` | 结束日 | `endDate` / `endTime` / `expireTime` / `validTo` |
| `status` | 状态 | `status` / `campaignStatus` / `state` |

### 活动 · Markdown 来源专属字段

官方活动日历返回 Markdown 正文时，由 `parse_campaign_markdown()` 填充下列字段。
它们**不来自 API 字段别名**，而是解析产物，因此单独列出。

| 规范字段 | 中文名 | 解析来源 |
|---|---|---|
| `calendar_date` | 日历归档日 | `_calendarDate` |
| `group_label` | 官方分组标签 | `_groupLabel` |
| `date_source` | 来源（json / markdown） | `_source` |
| `content` | 活动内容介绍 | `_content` |
| `image` | 活动图片地址 | `_image` |
| `synthetic_id` | 定位编号标记（非官方ID） | `_syntheticId` |

## 积分账户 `PointsAccount`

| 规范字段 | 中文名 | 别名（按优先级） |
|---|---|---|
| `available` | 可用积分 | `availablePoint` ✅ / `availablePoints` / `available` / `usablePoints` / `points` / `balance` |
| `total` | 累计积分 | `accumulativePoint` ✅ / `totalPoints` / `accumulatedPoints` / `total` |
| `frozen` | 冻结积分 | `frozenPoint` ✅ / `frozenPoints` / `frozen` / `frozenAmount` |
| `expiring_points` | 即将过期积分 | `currentMouthExpirePoint` ✅ / `currentMonthExpirePoint` / `expiringPoints` / `expiringSoonPoints` / `willExpirePoints` / `expirePoints` / `soonExpiredPoints` |
| `expiring_date` | 过期日 | `expiringDate` / `expireDate` / `expiryDate` / `expiringTime` |
| `level` | 会员等级 | `memberLevel` / `level` / `grade` / `memberGrade` |
| `used` | 已使用积分 | `usedPoint` ✅ / `usedPoints` / `used` |
| `expired` | 已过期积分 | `expiredPoint` ✅ / `expiredPoints` / `expired` |
| `next_expiring_points` | 下月将过期积分 | `nextMouthExpirePoint` ✅ / `nextMonthExpirePoint` |
| `last_expired` | 上月已过期积分 | `lastMouthExpirePoint` ✅ / `lastMonthExpirePoint` |
| `currency` | 积分类型（如「麦享会积分」） | `currency` ✅ |
| `account_id` | 会员账户标识（隐私，不落库） | `accountId` ✅ / `account_id` |

数值型字段共 8 项，真实返回中**全部为字符串型数字**（如 `"120.0"`），一律经 `parse_number()` 转换；
转换失败即视为缺失，**不会当成 0**。

## 格式不提供的字段（各接口的固有覆盖范围）

官方正文不携带的字段是**格式属性**，不是单条数据的缺陷，
因此不逐条登记 `missing`，而是由数据源状态聚合说明一次。

### `query-my-coupons`（Markdown 正文）

| 字段 | 中文名 |
|---|---|
| `id` | 券ID |
| `coupon_type` | 类型 |
| `discount_value` | 优惠值 |
| `threshold` | 门槛 |

### `available-coupons`（Markdown 正文）

| 字段 | 中文名 |
|---|---|
| `id` | 券ID |
| `coupon_type` | 类型 |
| `discount_value` | 优惠值 |
| `threshold` | 门槛 |
| `valid_from` | 生效日 |
| `valid_to` | 到期日 |
| `channel` | 适用渠道 |

### `query-my-account`（内嵌 JSON）

| 字段 | 中文名 |
|---|---|
| `expiring_date` | 过期日 |
| `level` | 会员等级 |

## 隐私字段

| 字段 | 说明 | 处理方式 |
|---|---|---|
| `accountId` | 会员账户标识 | 只记录存在，不保存取值 |

`accountId` 会被**识别到存在**（`PointsAccount.account_id_excluded = True`），
但**取值不落库、不进报告、不写日志**。`--dump-raw` 导出时另有键级掩码
（`mcd_client.mask_sensitive`），带签名的临时 URL 只保留路径。

## 派生字段

| 字段 | 计算方式 |
|---|---|
| `days_left` | `(valid_to - today).days`；`valid_to` 缺失时为 `None` |
| 紧急度等级 | 见 `SKILL.md` 的「紧急度分级规则」，实现于 `scripts/radar.py` |
| 排序键 | `(等级序, days_left 升序, 优惠值降序, 名称升序)`；`days_left` 缺失按哨兵值排同级末尾 |
| 重复标记 | 名称或 ID 与「我的券」重合的可领取券标记 `duplicate_of_owned`，不在报告中重复推荐 |
| `ref` | 无官方 ID 时的**定位编号**，带命名空间（`MC-MY-0001` / `MC-AVAIL-0001`）。命名空间不可省：两个列表各自从 1 编号，不加前缀会互相碰撞并导致误判重复 |
| `AccountStatus.observed_format` | 程序判定的真实返回格式（`json` / `json（内嵌于说明文本）` / `markdown` / `text` / `empty`） |
| 取数状态 | `PARSED` / `EMPTY` / `UNRECOGNIZED` / `FAILED`，见 `normalize.PayloadState` |
| 解析警告 | Markdown 解析中无法提取标题的条目、无条目的日期分组、**正文声明条数与实际解析条数不符**，一律进入 `Bundle.parse_notes`，不静默丢弃 |
