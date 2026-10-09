# 超麦权益雷达 · Super McBenefits Radar

> **一句话**：把散落在麦当劳中国 MCP 四个工具里的**优惠券、积分、活动**汇总成一份
> **按到期紧急程度排序**的「权益体检报告」，直接回答那个最容易吃亏的问题——
>
> ### 「我有哪些券和积分快过期了，这几天该怎么用？」
>
> 纯只读、不编造、零第三方依赖。装上就能用，跑一次约 4 次 API 调用。

| 项 | 值 |
|---|---|
| 中文名 | 超麦权益雷达 |
| 英文名 | Super McBenefits Radar |
| Skill 标识 | `super-mcd-benefits-radar`（= 仓库名 / 目录名 / `SKILL.md` 的 `name`） |
| 类型 | WorkBuddy Skill（Python 标准库，无第三方依赖） |
| 运行环境 | Python **3.10+**，无需 `pip install` |
| 许可 | [MIT](LICENSE) |

> ⚠️ **本项目是「麦当劳程序员节创意开发大赛」的独立参赛作品，由参赛者独立开发，
> 不代表麦当劳官方产品，也未获得麦当劳品牌背书。**
> 项目输出仅供参考；餐品信息、价格、规则与供应状态**以麦当劳官方渠道的实时结果为准**。

---

## 30 秒看懂它做什么

麦当劳 App 里「我的优惠券」「麦麦省」「积分」「活动」分散在四处，每张券的到期日各不相同。
真实痛点**不是"没有券"，而是"券太多、到期日不齐，看不出轻重"**。

超麦权益雷达做三件事：

1. **取数**：只读调用 4 个官方 MCP 工具（我的券 / 积分账户 / 可领取券 / 活动日历）；
2. **算**：用本项目自己的代码计算剩余天数、分级排序、跨源去重；
3. **交付**：产出一份 8 节结构的 Markdown 报告，**P0/P1 置顶**，缺什么就写什么。

一句话总结它的设计取舍：

> **它不替用户花钱，只替用户记事。**

---

## 它解决什么问题

| 痛点 | 后果 | 本项目的应对 |
|---|---|---|
| 券太多、到期日不齐，靠翻列表看不出轻重 | 券放着过期 | 按剩余天数分 7 档，`P0`/`P1` 单独置顶 |
| 已有的券和"可领取的券"混在一起 | 重复提醒、白忙一场 | 跨数据源去重，已持有的可领取券单独标注 |
| 积分"即将过期"藏在小字里 | 积分静默清零 | 单列积分板块并升级至 `P1` |
| 活动截止日不明显 | 错过限时活动 | 活动日历按日历日定位（今日 / 未来 / 往期），并如实声明"官方不提供有效期" |
| 看到空白不知道是"没有"还是"没读到" | 做出错误判断 | **解析失败必报警**，绝不把"读不懂"伪装成"没有数据" |

## 目标用户

* **每周会去 1–2 次麦当劳、手上攒着多张券的普通会员**——需要有人替他排优先级；
* **积分余额较高、担心过期的用户**；
* **想验证麦当劳 MCP 能力边界的开发者**——本项目对"只读能做成什么"给出了一个完整样板。

---

## 核心特性

| 特性 | 说明 |
|---|---|
| 🔒 **纯只读** | **不下单、不消费积分、不自动领券**。写入类工具在**代码层**被白名单拦下（默认拒绝），不是文档约定 |
| 🧾 **不编造** | 金额、有效期、折扣一律来自 MCP 返回值；取不到写 `[字段缺失]`，格式本身不含写 `未提供`，绝不推测填充 |
| 🚨 **解析失败必报警** | 响应有内容但解析不出来时，报告写"**收到数据，但解析失败**"，**禁止**说成"本月没有活动" |
| ⚖️ **"缺失"与"未提供"分开** | `[字段缺失]` = 取不到；`未提供` = 官方格式本身不含该字段。两者都不等于 0 |
| 💴 **实付价不当优惠额** | 官方原文 `¥9.9 (用券价格)` 是**用券后实付**，不是"省 9.9 元"。用 `benefit_kind` 区分，绝不换算 |
| 🕗 **北京时间基准** | 到期判定固定用 UTC+8，避免跨时区/凌晨把"今天到期"算成"明天到期" |
| 🔐 **隐私字段不落库** | `accountId` 只记录"存在过"，取值不进数据结构、报告与日志；签名 URL 导出时掩码 |
| 🗓️ **标准库排序** | 紧急度计算与排序纯用 Python `datetime`，**零第三方依赖** |
| 🎭 **三种模式隔离** | `mock` 合成样例 / `replay` 离线回放官方格式 / `real` 实时联网，报告首行显式标注 |
| 🛡️ **Token 零外流** | 只从环境变量读取；异常、日志、报告统一脱敏；仓库内附全仓凭据扫描测试 |
| ♻️ **单点失败降级** | 任一工具失败不影响整份报告，失败原因如实写入报告 |
| ✅ **322 项测试** | 覆盖边界值、排序确定性、脱敏回归、只读门禁、状态分类、**三种真实格式解析**、端到端回放 |

---

## 安装教程

### 1. 申请 MCP Token

前往 <https://open.mcd.cn/mcp> → 右上角【登录】（手机号验证）→【控制台】→【激活】→ 复制 Token。

> MCP 服务免费。每个 Token 限 **600 次请求/分钟**。

### 2. 在 WorkBuddy 中配置 MCP 连接器

左侧边栏【专家 · 技能 · 连接器】→【连接器】→ 右上角【自定义连接器】→【配置 MCP】，
填入 [`mcp-config.example.json`](mcp-config.example.json) 的内容
（**务必把 `YOUR_MCP_TOKEN` 换成你的真实 Token**）：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
    }
  }
}
```

保存后回到【自定义连接器】，把 `mcd-mcp` 打开【启用】。

> 🔐 该文件只含占位符。**填好 Token 的文件不要提交到任何仓库**——`.gitignore` 已覆盖常见路径。

### 3. 安装本 Skill

**方式 A（推荐）**：把本目录复制到用户级技能目录，目录名必须保持为 `super-mcd-benefits-radar`：

```bash
cp -r super-mcd-benefits-radar ~/.workbuddy/skills/
```

**方式 B**：完全不用装 Skill，直接跑命令行：

```bash
cd super-mcd-benefits-radar
python scripts/run_radar.py --mode mock   --out report.md   # 离线看效果（合成数据）
python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md  # 离线看官方格式
```

### 4. 环境要求

* Python **3.10+**（仅用标准库：`json` / `urllib` / `datetime` / `unittest`）
* 不需要 `pip install` 任何东西

---

## 使用示例

三种模式产出的报告**结构完全一致**，只有首行的模式横幅不同。
建议顺序：**先离线看效果 → 再回放官方格式 → 最后联网取自己的权益**。

### 1. 离线体验（合成样例，不需要 Token）

```bash
$ python scripts/run_radar.py --mode mock --out report.md
[mock] 券 6 张 | P0=1 P1=1 P2=1 P3=0 P4=1 UNKNOWN=1 EXPIRED=1 | 可领取 2 | 活动 4 | 取数失败 0 | 解析失败 0
报告已写入：report.md
```

报告首行标注 `[mock]`，**不会**和真实数据混淆。

### 2. 回放官方响应格式（不需要 Token）

官方四个工具的返回**没有一个是纯 JSON**。`fixtures/` 里存着**结构逐行对标真实响应、
取值全部合成**的样例；replay 模式把它们喂进**完全相同的解析、排序、渲染链路**：

```bash
$ python scripts/run_radar.py --mode replay --replay-dir fixtures --today 2026-10-09 --out report.md
[replay] 券 14 张 | P0=2 P1=3 P2=4 P3=5 P4=0 UNKNOWN=0 EXPIRED=0 | 可领取 9 | 活动 30 | 取数失败 0 | 解析失败 0
```

* 完整样例：[`examples/sample-report-replay.md`](examples/sample-report-replay.md)
* 活动板块节选：[`examples/sample-campaign-section-replay.md`](examples/sample-campaign-section-replay.md)

> 为什么样例要"结构真实、取值合成"？见 [`fixtures/README.md`](fixtures/README.md)。

### 3. 联网取自己的权益（需要 Token）

```bash
$ export MCD_MCP_TOKEN=你的Token        # 注意：不要写进任何文件
$ python scripts/run_radar.py --mode real --out report.md
[real] 券 14 张 | P0=2 P1=3 ... | 可领取 9 | 活动 30 | 取数失败 0 | 解析失败 0
```

> ⚠️ **`--mode real` 的适用条件（如实声明）**
>
> 该模式的实现是：Python 进程直接用 `urllib` 连接 `https://mcp.mcd.cn`，
> Token 取自环境变量 `MCD_MCP_TOKEN`。
>
> **在 WorkBuddy 里使用时，这条路径通常走不通**——连接器由 WorkBuddy 托管，
> Token 保存在客户端凭据库，**不会**导出到子进程环境变量。
> 也就是说：`--mode real` 只在"你手上有一个可直接使用的 Token、且愿意放进环境变量"的
> 场景下可用；**它在 WorkBuddy 会话内没有被验证过**。

### 4. 在 WorkBuddy 中直接用（推荐路径）

安装 Skill 后，直接说：

> "帮我看看我的麦当劳优惠券哪些快过期了"
> "生成一份权益体检报告"
> "我的积分有多少，会不会过期？"

此时取数由 **WorkBuddy 原生 MCP 调度**完成（连接器已托管 Token），
但**判断必须由本项目的代码产出**，不能由大模型直接总结工具返回。正确姿势：

1. 让 WorkBuddy 只读调用四个工具；
2. 把四个工具的返回写入一个回放目录（例如 `fixtures-dump/`，文件名为
   `query_my_coupons.md` / `query_my_account.txt` / `available_coupons.md` / `campaign_calendar.md`）；
3. 运行 `python scripts/run_radar.py --mode replay --replay-dir fixtures-dump --out report.md`。

这样报告里的分级、排序、字段缺失标记 **100% 出自本项目的代码**，可复现、可审计。

> 📌 **凡是"哪个券更急""哪个字段缺了"这类判断，都必须由代码算出来。**

### 5. 先验证连通性

```bash
$ python scripts/verify_mcp.py
[PASS] 端点可达性与鉴权保护      status: 403  guarded: True
[PASS] 只读白名单包含全部官方查询工具
[PASS] mock 工具清单 == 官方清单
[SKIP] 真实服务器工具清单 vs 官方清单   已跳过（未加 --real 或未配置 MCD_MCP_TOKEN）
```

---

## 报告长什么样

固定 8 节：**元信息 / 立即行动 / 本周内 / 可计划与待确认 / 积分账户 / 活动日历 / 待领取 / 数据完整性与免责声明**。

```markdown
## 2. 立即行动（P0 / P1）

1. **P0** — 【合成样例】现制甜品任选（券面权益 ¥9.9 (用券价格)，编号 MC-MY-0001） —— 今天到期
2. **P1** — 积分账户 —— 500 积分即将过期（12 天后过期）

## 4. 可计划与待确认（P3 / P4 / UNKNOWN）

### 信息不足 · 无法排序（UNKNOWN）

| 级别 | 名称 | 剩余时间 | 券面权益 | 使用条件 | 适用渠道 | 编号 |
|:---:|---|---|---|---|---|---|
| UNKNOWN | 【样例】新品尝鲜券 | [字段缺失] | 3 元 | [字段缺失] | 到店取餐 | MC-MY-0005 |
```

> 表格列名含义：「**券面权益**」是官方文案描述的权益本身（买一送一 / 满减 / 实付价），
> 不是换算后的优惠额；「**编号**」是解析生成的定位编号（`MC-MY-` / `MC-AVAIL-` /
> `MD-` 前缀），**不是官方 ID**。

### 紧急度分级

设 `剩余天数 = 到期日 − 今天`：

| 等级 | 条件 | 行动建议 |
|:---:|---|---|
| `P0` | `== 0` | 今天到期，立即使用 |
| `P1` | `1 – 3` | 尽快安排（积分"即将过期" > 0 也升到 `P1`） |
| `P2` | `4 – 7` | 本周内排一次 |
| `P3` | `8 – 30` | 可计划 |
| `P4` | `> 30` | 时间充裕 |
| `UNKNOWN` | 无有效到期日 | **信息不足**，请自行确认，不假定永久有效 |
| `EXPIRED` | 已过期 | 仅归档 |

同级排序键：`(等级序, 剩余天数升序, 优惠值降序, 名称升序)`，同输入必得同输出（有测试保证）。

---

## 技术架构

```
super-mcd-benefits-radar/
├── SKILL.md                      # Skill 入口（WorkBuddy 加载）
├── README.md                     # 本文件
├── CONTEST_DECLARATION.md        # 参赛声明（官方原文，字节级未改动）
├── MCP_INTEGRATION.md            # MCP 集成说明（用了哪些 Server / Tool / 调用流程 / 业务价值）
├── mcp-config.example.json       # 脱敏配置示例（仅占位符）
├── workbuddy.md                  # WorkBuddy 开发对话记录（脱敏）
├── LICENSE
├── run_tests.py                  # 一条命令跑全部测试
├── scripts/
│   ├── mcd_client.py             # MCP 客户端：只读白名单 / 三模式 / 脱敏
│   ├── normalize.py              # 统一数据结构 + 四态分类 + JSON/Markdown 双解析
│   ├── radar.py                  # 紧急度评分排序（纯 stdlib datetime）
│   ├── report.py                 # 报告渲染（8 节契约）
│   ├── run_radar.py              # 一键 CLI（mock / replay / real）
│   ├── verify_mcp.py             # 连通性与工具清单验证
│   └── dump_schema.py            # 由代码生成数据字典
├── references/
│   ├── mcp-tools.md              # 官方工具清单 + 实测格式
│   ├── data-schema.md            # 数据字典（由代码生成，不会与实现漂移）
│   ├── safety.md                 # 只读与隐私设计
│   ├── live-verification.md      # 真实调用的格式结论与缺陷修复（脱敏摘要）
│   └── privacy-and-publication.md# 隐私边界与公开发布范围
├── fixtures/                     # 数据样例（全部合成，见 fixtures/README.md）
├── examples/                     # 样例报告（由本项目代码生成）
└── tests/                        # 322 项测试
```

### 数据处理链路

```
MCP 原始返回（dict / 纯 JSON / 说明文本包裹 JSON / Markdown）
    │  ⓪ classify_state() —— 先分清"空 / 读不懂 / 失败"，再谈解析
    ▼
    ├── 调用失败 ──────────────────────────► FAILED        → "取数失败 + 原因"
    ├── 成功 + 解析出记录 ─────────────────► PARSED        → 正常展示
    ├── 成功 + 有内容 + 零记录 ────────────► UNRECOGNIZED  → "收到数据，但解析失败"
    └── 成功 + 确实为空 ───────────────────► EMPTY         → 才可以说"没有"
    │  ① coerce_payload() → observe_format() → find_records()
    │     零记录且该工具注册了文本解析器 → 回退 _TEXT_PARSERS
    ▼
    │  ② COUPON_ALIASES / CAMPAIGN_ALIASES / POINTS_ALIASES 逐个别名试取
    │     必需字段集按来源分流（"我的券" ≠ "可领取券"）
    ▼
    │  ③ 取不到 → None + 记入 missing（绝不填默认值）
    ▼
    │  ④ days_left = (valid_to − today_beijing()).days   ← 纯 stdlib datetime
    │     活动按来源分流：JSON → 有效期紧急度；Markdown → 日历语义
    ▼
    │  ⑤ 排序 (等级序, 剩余天数升序, 优惠值降序, 名称升序)
    ▼
Markdown 报告（8 节固定结构 + 数据完整性声明）
```

### 四个工具、三种真实格式（本项目最大的技术发现）

官方**只公开工具用途描述，不公开响应字段级 schema**。实测四个工具的返回格式**互不相同，
且没有一个是纯 JSON**：

| 工具 | 实测格式 | 解析难点 | 解析结果 |
|---|---|---|---|
| `query-my-coupons` | Markdown | `## 券名` 分块 + `- **字段**: 值`；字段种类随券类型变化 | 14/14 |
| `query-my-account` | 说明性文本 + **内嵌 JSON** | JSON 外裹字段说明，需靠**括号配平**定位 | 1/1 |
| `available-coupons` | Markdown | 换行处有**行尾 `\` 续行符**，需先拼接 | 9/9 |
| `campaign-calendar` | Markdown | `#### 日期` 分组（`今日` / `往期回顾` / 无标签未来日） | 30/30 |

格式判定由 `normalize.observe_format()` **程序完成**，不是人工声称；
判定结果直接印在报告第 1 节的数据源状态表里。

**这套"实测"不是一次性目测**：结论、被推翻的假设与全部修复过程记录在
[`references/live-verification.md`](references/live-verification.md)，
并由 `tests/` 中的格式测试与端到端回放测试**离线锁定**。

### 为什么"解析失败"必须独立成一个状态

只记录"解析出几条"的做法有个致命盲区：**解析器读不懂**与**接口确实返回空**
在报告里长得一模一样，都显示"没有数据"。用户看到"本月没有活动"会认为确实没有，
而真相是程序没读懂——这是**静默的假阴性**，比报错更危险，因为无从察觉。

因此状态被显式拆成四种，并且**只有 `EMPTY` 才允许下"没有数据"的结论**。
该约束由 `tests/test_payload_state.py` 的专项用例锁定，防止回归。

---

## 真实 MCP 接入说明

### 使用的 Server 与 Tool

| 项 | 值 |
|---|---|
| 服务方 | 麦当劳中国（官方远程托管） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权 | 请求头 `Authorization: Bearer <你的 Token>` |
| Token 申请 | <https://open.mcd.cn/mcp> |
| 官方文档 | <https://github.com/M-China/mcd-mcp-server> |
| 收费 | 免费（600 请求/分钟/Token） |

**调用 4 个只读工具**：`query-my-coupons`、`query-my-account`、`available-coupons`、
`campaign-calendar`（辅助：`now-time-info`）。

官方清单中还有约 30 个工具（点餐、下单、积分兑换、抽奖、派对预约等）。
本项目**一个都不用**——它们被 `READ_ONLY_TOOLS` 白名单**默认拒绝**。
拦截机制是白名单而非黑名单：官方将来新增任何写入类工具都会被自动拦下。

### 两种接入方式

| 方式 | Token 在哪 | 本项目如何取数 | 适用场景 |
|---|---|---|---|
| **A. WorkBuddy 连接器**（推荐） | WorkBuddy 凭据库（进程外） | WorkBuddy 原生调度四个只读工具 → 写入回放目录 → `--mode replay` | 在 WorkBuddy 会话中使用 |
| B. 环境变量 | 进程环境 `MCD_MCP_TOKEN` | `--mode real` 由 Python 直接联网 | 本地命令行 / CI |

方式 A 下端到端链路与方式 B **完全相同**（同一套解析、排序、渲染代码），
差别只在"谁发起 HTTP 请求"。

### 数据边界与可复现性（**请务必阅读**）

1. **仓库内 `fixtures/` 是合成样例，不是真实响应。**
   真实响应**含账户数据**（券清单、积分余额），**未随公开仓库分发**。
   样例与真实响应**逐行结构同构**，因此解析器面对的是真实格式，测试仍然有意义。
   判定依据是行内可见的 `【合成样例】` 前缀，不会与真实数据混淆。
2. **模型转写限制（如实声明）**：在 WorkBuddy 会话中，MCP 工具的返回需经模型上下文
   才能落到本机文件，因此落盘内容属于**模型转写**；
   任何校验都无法证明它与服务端原文**字节级一致**。本项目**不对"逐字一致"做任何声明**。
   要拿到字节级原文，请使用方式 B（进程内直连）并由程序自行落盘。
3. **格式结论是单次快照。** 官方字段名随券类型与活动配置浮动；本项目对**已出现过的字段**
   做了映射，对**未出现过的字段**只保留为"未映射"并在报告第 8 节列出。
   拿到新 Token 后建议再跑一次 `--dump-raw raw/` 收敛别名表。

---

## 测试

```bash
$ python run_tests.py
OK
------------------------------------------------------------
共 322 项 | 失败 0 | 错误 0 | 跳过 0

$ python run_tests.py redaction -v     # 只看脱敏相关
$ python run_tests.py radar            # 只看紧急度分级
```

覆盖重点：

| 测试文件 | 关注点 |
|---|---|
| `test_skill_manifest.py` | SKILL.md frontmatter 合法性与声明完整性 |
| `test_submission_ready.py` | 必需文件齐全、官方声明哈希未变、仓库无凭据、文档与代码一致 |
| `test_client_guardrails.py` | 写入类工具被拦截、白名单未扩大、mock 不联网 |
| `test_redaction.py` | Token 不外流（含一个真实回归用例） |
| `test_normalize.py` | 日期/数字解析边界、缺失字段登记、去重 |
| `test_payload_state.py` | **解析失败 vs 真空 vs 取数失败**三态区分，禁止假阴性 |
| `test_coupon_markdown.py` | `query-my-coupons` 官方 Markdown：多券、字段不定、`[字段缺失]` vs `未提供`、同名券保留、实付价不当优惠额 |
| `test_available_coupons.py` | `available-coupons` 官方 Markdown：行尾续行、状态剔除、编号命名空间 |
| `test_account_payload.py` | `query-my-account` 内嵌 JSON 提取、`Mouth` 拼写、字段缺失、`accountId` 不落库 |
| `test_campaign_markdown.py` | 活动 Markdown 解析、双格式兼容、日历语义、不丢活动 |
| `test_replay_pipeline.py` | 四个格式样例走完整解析→排序→渲染链路，端到端断言 |
| `test_radar.py` | 分级边界值、排序确定性、`UNKNOWN` 不被误判 |
| `test_report.py` | 输出契约、端到端 CLI、报告中零 Token |

---

## 隐私与安全

* **Token** 只从环境变量 `MCD_MCP_TOKEN` 读取，不落盘、不回显、不进 URL；
  `mcp-config.example.json` 只含占位符。
* **账号标识不落库。** `query-my-account` 返回里的 `accountId` 在归一化时即被**丢弃取值**——
  只记录"这个字段存在过"，取值不进数据结构、不进报告、不进日志、也不进 `--dump-raw` 导出。
* **报告**不写入任何账号标识；`--dump-raw` 的导出经过**结构保留式掩码**
  （键名保留、取值替换）。带签名的 CDN 图片 URL 视为**有时效凭据**，一并掩码。
* **只读保证**由 `READ_ONLY_TOOLS` 白名单实现，**默认拒绝**。
* 仓库内含**全仓凭据扫描测试**（Token / `sk_live_` / 长十六进制 / 手机号），防止误提交。

> 完整的隐私边界与公开发布范围见 [`references/privacy-and-publication.md`](references/privacy-and-publication.md)。

### 如需代领券或下单

本 Skill 明确不做。请打开麦当劳 App 自行操作——报告会把"该领什么、该优先用什么"排好序给你。

---

## 已知限制（如实说明）

1. **格式结论是 2026-10-09 的单次快照。** 四个工具的格式已实测确认，字段映射覆盖了
   已出现过的字段；对**新出现的字段**，别名表在补充验证之前仍属假设。
2. **CLI `--mode real` 在 WorkBuddy 会话内不可用**（连接器 Token 不进子进程环境变量）。
   WorkBuddy 场景请走"原生调度 + replay 回放"路径。
3. **活动日历只有归档日期，没有有效期。** 官方不提供起止时间，因此无法判断
   "这个活动还剩几天"。需要具体售卖期时请查活动详情页。
4. **同一活动可能跨多日重复出现，本项目不去重。** 这是官方日历本身的组织方式，
   去重反而会掩盖"今天仍有"的事实。
5. **积分过期规则只呈现不推断。** 报告只给出"即将过期积分"数值与日期，
   不推断麦当劳的积分计息/过期规则。
6. **不做预测。** 不预测下周会有什么券、不预测价格变动。
7. **单账号。** 一次只处理当前 Token 对应账号的权益。
8. **`accountId` 等隐私字段仅记录"存在过"**，因此项目无法据此做多账号区分。

---

## 参赛信息

| 项 | 内容 |
|---|---|
| 赛事 | 麦当劳程序员节创意开发大赛 |
| 官方仓库 | <https://github.com/M-China/mcd-developer-innovation-challenge> |
| MCP 文档 | <https://github.com/M-China/mcd-mcp-server> |
| 必需文件 | `README.md`、`CONTEST_DECLARATION.md`（官方原文，未改动）、`MCP_INTEGRATION.md`、`mcp-config.example.json`、源代码 |
| WorkBuddy 专项 | 已附 `workbuddy.md`（脱敏开发对话记录） |
| 真实验证 | 四个只读工具均于 2026-10-09 完成真实调用，格式结论见 [`references/live-verification.md`](references/live-verification.md) |
| 自动化测试 | 322 项，全绿（`python run_tests.py`） |
| Git 历史 | 公开仓库使用**干净的初始提交**，不继承任何开发期历史 |

---

## 免责声明

本项目为**独立参赛作品**，由参赛者独立开发，**非麦当劳官方产品**，也未获得麦当劳品牌背书。
项目对所有只读 MCP 返回的展示仅供参考，**不构成任何形式的建议**；
餐品信息、价格、券面规则及供应状态**以麦当劳官方渠道的实时结果为准**。
本项目**未执行任何下单、领券或积分消费操作**。

对"麦当劳""麦麦省""麦乐送"等名称的使用仅限**描述性指代**，
不构成对麦当劳及其关联方商标的任何授权，亦不暗示官方背书。
麦当劳 MCP 服务的使用须遵守麦当劳中国的《使用条款》及《麦当劳 MCP 服务规则》。

## 许可

[MIT](LICENSE)。
