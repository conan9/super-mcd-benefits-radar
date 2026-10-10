---
name: super-mcd-benefits-radar
display_name: 超麦权益雷达
display_name_en: Super McBenefits Radar
description: |
  超麦权益雷达 —— 只读汇总麦当劳中国的优惠券、积分与活动信息，按紧急程度排序，
  生成一份「权益体检报告」，回答"我有哪些权益快过期了、该怎么用"。
  当用户提到下列任一项时触发本技能：超麦权益雷达、检查我的麦当劳权益、麦当劳优惠券到期提醒、
  我的麦当劳积分、我的麦当劳优惠券快过期了、麦麦省可领券、麦当劳活动日历、权益体检报告。
  TRIGGER when: 用户想查询或体检自己麦当劳会员权益的券、积分、活动。
  DO NOT TRIGGER when: 用户要点餐、下单、领券、积分兑换或抽奖。本技能为纯只读，不执行任何写操作。
description_zh: 超麦权益雷达：只读汇总麦当劳中国的优惠券、积分与活动，按到期紧急度排序生成权益体检报告。
description_en: Super McBenefits Radar aggregates McDonald's China coupons, points and campaigns through read-only MCP tools and produces an urgency-ranked benefits health report.
version: 1.0.0
author: conan9
license: MIT
agent_created: true
---

# 超麦权益雷达（Super McBenefits Radar）

把散落在麦当劳中国 MCP 各工具里的会员权益，汇总成一份**按紧急程度排序**的体检报告。

## 触发词

用户说出下列任一表述时，直接进入本技能的执行流程：

- 超麦权益雷达
- 检查我的麦当劳权益
- 麦当劳优惠券到期提醒
- 我的麦当劳积分
- 我的麦当劳优惠券快过期了 / 哪些券要过期了
- 麦麦省可领券
- 麦当劳活动日历
- 生成权益体检报告

## 核心定位

| 维度 | 说明 |
|---|---|
| **只读** | 只调用查询类工具。下单 / 核销 / 领券类工具在本技能中被**硬编码拒绝** |
| **不编造** | 金额、有效期、折扣一律来自 MCP 返回值；取不到写 `[字段缺失]`，格式本身不含写 `未提供`，绝不推测填充 |
| **可追溯** | 每条结论都标注数据来源工具与原始字段名 |
| **真实优先** | **默认使用真实 MCP**。没有 Token 或取数失败时**直接报错并停止**，绝不悄悄回退到 `mock` 合成样例 |
| **三模式隔离** | `mock`（合成样例，**必须显式指定**）/ `replay`（**官方响应格式样例**，离线复现线上格式）/ `real`（实时联网）严格分离，报告首行显式标注 |

---

## 强制安全边界（不可绕过）

本技能**绝对不执行**以下操作：

1. ❌ 下单类：`mcdelivery-order`、`pickup-order`、`group-meal-order`、`mall-create-order`、`party-order-create` 等
2. ❌ 核销/领券类：`auto-bind-coupons`、`point-redemption` 等
3. ❌ 抽奖类：`draw-lottery`（消耗积分/次数）
4. ❌ 取消/变更类：任何 `cancel`、`refund` 类工具

代码层已实现**白名单 + 默认拒绝**（`scripts/mcd_client.py` 的 `READ_ONLY_TOOLS`）。
任何不在白名单内的工具调用都会抛出 `WriteOperationBlocked`，这是设计意图，不是缺陷。

> 若用户要求"帮我领券""帮我下单""用积分兑换"，本技能应回答：
> **"本技能仅做只读体检，不会代为领券/下单。我可以把可领/可兑的项按紧急度列给你，由你本人在麦当劳 App 中操作。"**

---

## Token 与隐私

- Token **只能**来自环境变量 `MCD_MCP_TOKEN`，禁止写入任何文件、禁止回显。
- 报告、日志、异常信息统一经过脱敏；`Bearer xxx` 与 32 位以上十六进制串会被替换为 `***`。
- **账号标识（`accountId`）只记录"字段存在过"，不保存取值** —— 不进数据结构、不进报告、
  不进日志、不进 `--dump-raw` 导出。
- 响应中带签名的 CDN 图片 URL（`q-ak=` / `q-signature=` 等）视为**有时效凭据**，
  导出时经结构保留式掩码（键名保留、取值替换）。
- `mcp-config.example.json` 中只允许出现占位符 `YOUR_MCP_TOKEN`。

---

## 使用流程

### 第 0 步：确认模式

```bash
echo "${MCD_MODE:-real}"          # 未设置时默认 real（刻意**不**回退 mock）
echo "${MCD_MCP_TOKEN:+已配置}"    # 仅判断是否存在，不打印内容
```

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `real`（**默认**） | 未显式指定模式时 | 连接 `https://mcp.mcd.cn` 真实调用。**未配置 `MCD_MCP_TOKEN` 时直接报错退出（退出码 `2`）** |
| `replay` | `--mode replay`（或 `--replay-dir DIR`） | 读取离线回放目录中的**响应样例**，走与线上完全相同的解析/排序链路，不联网 |
| `mock` | **必须显式**：`--mode mock` 或 `MCD_MODE=mock` | 读取 `fixtures/*.json` **合成样例**，不发起网络请求 |

> ⚠️ **不存在"没有 Token 就自动换成 mock"的行为。** 那会让用户拿到一份看起来正常的
> 合成假报告，却误以为是自己账户的真实权益——这比直接报错危险得多。
> `mock` 只能由用户显式指定，且报告首行与终端**双双**标注"合成样例、非真实权益"。

**报告首行必须显式声明当前模式**，mock 模式下的报告顶部须有醒目提示，避免被误当作真实权益。

> ℹ️ 在 WorkBuddy 中，连接器由客户端托管，Token 通常**不在**子进程环境变量里，
> 因此 `real` 模式在会话内往往不可用。推荐做法：由 WorkBuddy 原生调度四个只读工具取数，
> 把返回**原样**写入回放目录，再用 `--mode replay` 生成报告——
> 这样分级与排序仍由本项目代码产出，而不是由大模型直接总结工具输出。
>
> ⛔ **连接器不可用时不得改用 `--mode mock`，也不得编造权益条目。**

### 第 1 步：抓取四个数据源（顺序执行，失败可降级）

| 顺序 | 工具 | 用途 | 实测返回格式 | 缺失时的影响 |
|---|---|---|---|---|
| 1 | `query-my-coupons` | 我账户里已有的券（最关键） | **Markdown** | 报告核心缺失 |
| 2 | `query-my-account` | 积分账户（可用/累计/冻结/即将过期） | **说明文本 + 内嵌 JSON** | 积分板块标注缺失 |
| 3 | `available-coupons` | 麦麦省**可领取**的券 | **Markdown**（行尾 `\` 续行） | 仅作"可补充"提示，不代领 |
| 4 | `campaign-calendar` | 当月营销活动日历 | **Markdown**（`#### 日期` 分组） | 活动板块标注取数/解析状态 |

> ⚠️ **四个工具没有一个是纯 JSON**，且互不相同（上表为 2026-10-09 真实调用实测，
> 由 `normalize.observe_format()` 程序判定）。解析必须走 `coerce_payload()` →
> `observe_format()` → `find_records()`（零记录时回退文本解析器）的链路，
> **不得假设返回是 JSON，也不得靠关键字切分内嵌 JSON**（`query-my-account` 的 JSON
> 外面裹着字段说明文本，必须用括号配平提取）。

> 任一工具失败**不得**中断整份报告：记录失败原因，报告对应板块写"数据获取失败 + 原因"。
> `now-time-info` 可用于校准"今天"的基准日期（可选，优先级低于本地系统时间）。

### 取数状态：四种状态必须分开表述（关键约束）

每个数据源都要判定状态，**"调用成功"不等于"数据被读懂"**：

| 状态 | 含义 | 报告必须怎么写 |
|---|---|---|
| `PARSED` | 调用成功且识别出记录 | 正常展示 |
| `EMPTY` | 调用成功，确实没有数据 | **只有此时**才可以说"没有活动 / 没有券" |
| `UNRECOGNIZED` | 调用成功、**收到内容但解析器读不懂** | 必须写"**收到数据，但解析失败**"，并禁止下"没有数据"的结论 |
| `FAILED` | 调用失败（网络 / 鉴权 / 限流 / 工具报错） | 必须写"取数失败 + 原因" |

> ⚠️ **禁止把解析失败展示成"本月没有活动"。** 这是静默假阴性：用户看到空白会认为
> "确实没有活动"，而真相是程序没读懂。误报比报错危险，因为无从察觉。
> 该规则有专项测试锁定（`tests/test_payload_state.py`）。

判定 `EMPTY` 时用的是 `_is_effectively_empty()`：**先跳过标题行与计数声明，仍无内容才算真空**。
`### 麦麦省优惠券列表：` 这种"只有标题"的返回应判为 `EMPTY`（真空），**不是**"解析失败"——
否则用户会以为接口坏了。同理，仅含协议信封（`{"code":0,"success":true,…}`）而不含
任何积分字段的返回**不算**"有数据"，不列出满屏 `[字段缺失]`。

### 缺失语义：「取不到」与「格式不含」是两件事

| 标记 | 含义 | 何时使用 |
|---|---|---|
| `[字段缺失]` | 字段**该有**，但解析器没取到 | JSON 路径，或 Markdown 里该行本应存在却缺失 |
| `未提供` | 官方**格式本身不含**该字段 | 例如可领取券的 Markdown 根本没有到期日行 |

两者都不等于 `0`，也都不代表权益不存在。措辞由 `Coupon.unknown_mark` 按 `source_format`
自动选择，**不得混用**。

### 第 2 步：把原始返回逐字落盘并校验

新建采集目录（例如 `fixtures-dump/`），把四个工具返回**原样逐字**写入：

```text
fixtures-dump/
├── query_my_coupons.md      # query-my-coupons 的原始返回
├── query_my_account.txt     # query-my-account 的原始返回
├── available_coupons.md     # available-coupons 的原始返回
└── campaign_calendar.md     # campaign-calendar 的原始返回
```

文件名还接受连字符写法（`query-my-coupons.md`）与 `.text` / `.raw` / `.json` 后缀。

> ⚠️ **严禁改写、摘要、翻译、截断、补全或"整理格式"。** Markdown 的 `##` / `####`、
> 行尾续行反斜杠、emoji、JSON 括号与全部字段名都必须原样保留。一旦落盘的是转述内容，
> 后续分级与排序就失去依据——等于让大模型自由总结，这正是本技能要避免的。

校验采集结果（**硬门槛，不可跳过**）：

```bash
python scripts/verify_capture.py --dir fixtures-dump/
```

- 退出码 `0`：四个数据源齐备且可被解析 → 继续下一步。
- 退出码 `1` / `2`：**停止，不要生成报告。** 如实说明哪些数据源缺失或无法解析，并重新采集。
- 出现"疑似被转述"告警时，回到本步重新逐字落盘。

### 第 3 步：生成报告

```bash
# WorkBuddy 内的标准路径：回放刚采集的原始载荷（推荐）
python scripts/run_radar.py --mode replay --replay-dir fixtures-dump/ --out report.md

# 离线复现仓库自带的合成格式样例
python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md

# 显式离线演示（合成样例，报告与终端都会标注"非真实权益"）
python scripts/run_radar.py --mode mock --out report.md

# 命令行直连真实接口（需要进程环境变量 MCD_MCP_TOKEN）
MCD_MCP_TOKEN=*** python scripts/run_radar.py --mode real --out report.md
```

`run_radar.py` 的退出码：`0` 正常；`1` 四个数据源全部取数失败；`2` 鉴权 / 配置问题；
`3` 有数据源**收到数据但解析失败**——此时**不得**把相关板块的空白说成"没有权益"。

### 第 4 步：交付话术

先给「P0/P1 立即行动」清单（最多 5 条），再说明完整性缺口与失败的数据源，最后附完整报告文件。

---

## 紧急度分级规则

判定基准为**报告生成日**，固定按**北京时间（UTC+8）**计算（`normalize.today_beijing()`）
——刻意不用 `zoneinfo`，避免 Windows 上需要 tzdata 而破坏零依赖承诺。
纯粹使用 Python 标准库 `datetime`。

### 优惠券

设 `days_left = (valid_to - today_beijing()).days`：

| 等级 | 条件 | 行动建议 |
|:---:|---|---|
| `EXPIRED` | `days_left < 0` | 已过期，仅归档展示 |
| `P0` | `days_left == 0` | **今天到期**，立即使用 |
| `P1` | `1 ≤ days_left ≤ 3` | 3 天内到期，尽快安排 |
| `P2` | `4 ≤ days_left ≤ 7` | 本周内到期 |
| `P3` | `8 ≤ days_left ≤ 30` | 本月内到期，可计划 |
| `P4` | `days_left > 30` | 充裕，观察 |
| `UNKNOWN` | 无有效 `valid_to` | **字段缺失**，无法排序，单列展示 |

### 积分

- 存在「即将过期积分 > 0」→ 整体提升至 `P1`，并给出精确数值。
- 「即将过期积分」字段缺失 → 标注 `[字段缺失]`，**不得**假定为 0。

### 活动

活动有两种来源，**分级规则不同，不得混用**：

**A. 结构化来源**（JSON，含显式有效期 `startDate` / `endDate`）

- 进行中且 `days_left ≤ 3` → `P1`；进行中且 `> 3` → `P2`；未开始 → `P3`。

**B. 官方活动日历**（Markdown 正文，**实测的真实格式**）

官方日历**按日期归档**，只回答"这条活动出现在哪一天"，**不提供有效期**。因此：

| 等级 | 条件 | 含义 |
|:---:|---|---|
| `TODAY` | 归档日 == 今天 | 官方标注「今日」 |
| `UPCOMING` | 归档日 > 今天 | 日历中的未来日期 |
| `PAST` | 归档日 < 今天 | 官方标注「往期回顾」 |
| `UNKNOWN` | 无归档日 | 无法定位 |

> ⚠️ **禁止用"到期/结束"措辞描述日历条目。** 例：9.9 元早餐两件套在 2026-10-09 被标注为
> 「今日」，而其实际售卖期是 10-08 至 10-21。把它写成"今天结束"就是**编造**。
> 同理「往期回顾」只表示该条已归档，**不代表活动本身已结束**。

> 💴 **券面权益 ≠ 优惠额。** 官方原文 `¥9.9 (用券价格)` 是**用券后实付**，不是"省 9.9 元"。
> 由 `benefit_kind`（`price` / `discount` / `unknown`）区分，报告列名写「券面权益」，
> **绝不把实付价换算成优惠额**。

### 同级排序

`(等级序, days_left 升序, 折扣价值降序, 名称升序)`

> 折扣价值缺失时按 `0` 参与排序，但报告中仍显示 `[字段缺失]`——排序兜底不等于数据填充。

---

## 输出契约

报告为 Markdown，固定章节顺序：

1. **元信息**：生成时间 / 数据模式 / 基准日 / **数据源状态表（含状态、记录数、返回体量）**
2. **立即行动**（P0 + P1）
3. **本周内**（P2）
4. **可计划与待确认**（P3 / P4 / UNKNOWN）
5. **积分账户**
6. **活动日历**（日历来源：`日历状态 | 活动 | 日历日 | 官方分组 | 距今`；
   结构化来源：`级别 | 活动 | 起止 | 剩余`；解析失败时本板块必须显式声明）
7. **待领取（麦麦省）** —— 只提示，不代领；状态为「已领取」的条目从此板块剔除，
   避免与"我的券"重复提醒
8. **数据完整性与免责声明**

免责声明必含：非麦当劳官方产品、权益以麦当劳官方渠道实时结果为准、本报告不构成任何建议。

---

## 文件导航

| 文件 | 作用 |
|---|---|
| `scripts/run_radar.py` | 一键入口，产出报告（支持 `mock` / `replay` / `real`） |
| `scripts/verify_capture.py` | 采集目录校验：完整性、可解析性、逐字性（生成报告前的硬门槛） |
| `scripts/mcd_client.py` | MCP 客户端：白名单、三模式（**默认真实、绝不自动回退 mock**）、脱敏与结构保留式掩码 |
| `scripts/normalize.py` | 统一数据结构 + 缺失登记 + 四态分类 + 四种真实格式解析 |
| `scripts/radar.py` | 紧急度评分与排序（纯 stdlib） |
| `scripts/report.py` | Markdown 报告渲染 |
| `references/data-schema.md` | 数据字典（由代码生成） |
| `fixtures/query_my_coupons.md` | `query-my-coupons` 格式基准样例（Markdown，14 张券，取值合成） |
| `fixtures/query_my_account.txt` | `query-my-account` 格式基准样例（说明文本 + 内嵌 JSON，取值合成） |
| `fixtures/available_coupons.md` | `available-coupons` 格式基准样例（Markdown，9 条，取值合成） |
| `fixtures/campaign_calendar.md` | `campaign-calendar` 格式基准样例（Markdown，30 条活动，取值合成） |
| `fixtures/*.json` | 对应工具的兼容 JSON 合成样例（mock 模式用） |
| `references/safety.md` | 只读与隐私边界 |
| `references/mcp-tools.md` | 官方工具清单、实测格式与来源标注 |
| `references/live-verification.md` | 真实 MCP 连接与验证记录 |

## 验收标准

- [ ] **默认模式为 `real`；没有 Token 时报错退出，绝不自动回退 `mock`**
- [ ] `mock` 只能显式指定，且报告首行与终端都标注"合成样例、非真实权益"
- [ ] replay 模式可从响应样例跑出完整报告，且分级/排序由代码产出
- [ ] `verify_capture.py` 对采集目录的退出码为 0（缺件 / 无法解析 / 疑似转述均判失败）
- [ ] 真实模式下无 Token 时给出明确指引，不抛裸异常
- [ ] 报告中 Token 出现次数恒为 0，账号标识取值出现次数恒为 0
- [ ] 写入类工具被拒绝，且有测试覆盖
- [ ] 字段缺失处均标注 `[字段缺失]` 或 `未提供`，无编造值
- [ ] 解析失败必报"收到数据，但解析失败"，不出现静默假阴性
