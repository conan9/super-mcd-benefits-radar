# WorkBuddy 开发对话记录 · super-mcd-benefits-radar（超麦权益雷达）

> **来源与真实性声明**
>
> 本文是 **2026-10-09 本人使用 WorkBuddy 开发本 Skill 的真实对话记录**，
> 按开发阶段整理自实际会话，非事后编写的示例。
>
> **脱敏处理**（仅做遮蔽，未删改技术结论、未美化结果）：
> - MCP Token、环境变量取值 → `***` 或 `YOUR_MCP_TOKEN`
> - 本机绝对路径 → `<WORKSPACE>`、`~`
> - 本机其他已安装 Skill 的目录名 → `<已安装 Skill>`（仅遮蔽名称，不涉及本项目的技术内容）
> - 个人身份信息（姓名、账号、联系方式）→ 不涉及
>
> ⚠️ **本文是经过必要隐私脱敏后的版本**：面向公开仓库分发，凡涉及凭据、
> 本机路径、个人用途与其他技能目录的片段均做了遮蔽或形态化处理。
> 除上述遮蔽项外，开发过程、误判、缺陷与修正均按原貌保留，未做美化。
>
> 记录中保留了开发过程中**发现的问题与修正过程**（包括一次误判与两处缺陷），
> 因为它们才是这次协作的真实内容。
>
> 参加 WorkBuddy 专项奖励时，官方要求提交通过 WorkBuddy 导出的完整对话上下文；
> 如需要，可另附官方导出的原始记录替代/补充本文。

---

## 会话元信息

| 项 | 值 |
|---|---|
| 日期 | 2026-10-09 |
| 工具 | WorkBuddy（Agent 模式） |
| 目标 | 为麦当劳程序员节创意开发大赛开发可开源发布的 Skill |
| 产出 | `super-mcd-benefits-radar`（超麦权益雷达 / Super McBenefits Radar）Skill（SKILL.md + 7 个 Python 模块 + 测试套件 + 参赛文件） |
| 命名变更 | 早期标识 `mcd-benefits-radar` → 正式标识 `super-mcd-benefits-radar`（中文名「超麦权益雷达」、英文名 Super McBenefits Radar 未变）。本文档除下文保留的**用户原话摘录**外，已统一使用正式标识 |
| 公开分发说明 | 本文提到的部分开发期中间产物——真实响应副本（`fixtures/*.md` / `*.txt` 的原始版本）、由真实数据生成的报告与活动板块样例——**含账户数据，未随公开仓库分发**；仓库内 `fixtures/` 为结构逐行对标、取值全部合成的样例。技术结论见 `references/live-verification.md` |
| 隐私脱敏 | **本文为公开发布版，已做必要隐私脱敏**：Token/环境变量取值、本机绝对路径、本机其他已安装 Skill 的目录名、真实账户数值均被遮蔽或替换为形态化占位；开发过程与技术结论未删改。脱敏清单见文首「脱敏处理」小节 |
| 运行环境 | Windows / Python 3.13.12（仅标准库） |

---

## 阶段 0 · 需求澄清与真实性核查

**用户**（原话摘录）：

> 请帮助我为"2026麦当劳程序员创意开发大赛"开发一个可开源发布的 WorkBuddy Skill。
> 项目名称：超麦权益雷达（mcd-benefits-radar）……
> 开发原则：1. 在 WorkBuddy 中直接运行 Skill，使用 https://mcp.mcd.cn。
> 2. 查询工具：query-my-coupons、query-my-account、available-coupons、campaign-calendar。
> 3. 不下单、不消费积分、不自动领券。
> 4. 不编造优惠、金额、有效期。字段缺失时明确说明。
> 5. 模拟模式与真实 MCP 模式区分，严禁泄露 Token。
> 6. Python 标准库负责日期排序，并编写测试。
> ……CONTEST_DECLARATION.md 必须原样采用官方仓库文件。
> workbuddy.md 保留实际开发对话，脱敏且不能伪造。

> **〔原话保留〕** 上面这段是用户当时的原始表述，其中的项目标识写作 `mcd-benefits-radar`。
> 该标识后续在打包为 WorkBuddy 安装包时正式更名为 **`super-mcd-benefits-radar`**
> （中文名「超麦权益雷达」、英文名 Super McBenefits Radar 始终未变）。
> 为遵守"记录不得伪造"的约定，此处**不改写引用原文**；本文档其余部分均已使用正式标识。

**助手**先做核查，不直接动手写代码。核查动作与结果：

| 核查项 | 动作 | 结果 |
|---|---|---|
| 端点是否真实 | `nslookup mcp.mcd.cn` + 不带 Token 的 `POST /initialize` | DNS 解析至腾讯云；返回 `403` + `{"code":"0001","msg":"系统错误"}`，**是受鉴权保护的官方服务** |
| 赛事是否存在 | GitHub API 检索 | 找到官方仓库 `M-China/mcd-developer-innovation-challenge`（描述即"1024 Programmers' Day"）与 `M-China/mcd-mcp-server` |
| 工具名是否准确 | 抓取官方 `README.md` 工具列表 | 见下 |
| 提交要求 | 读官方 `README.md` 的《开发 Skill》一节 | README.md / CONTEST_DECLARATION.md / MCP_INTEGRATION.md 必需；workbuddy.md 为 WorkBuddy 专项必需 |
| 截止时间 | 读官方赛事时间表 | 报名及排名 2026-10-09 10:30 — 10-25 23:59 |

### 一次误判与纠正（如实记录）

初步检索时，部分**第三方** MCP 目录站列出的工具名是 `my-coupons`、`campaign-calender`，
与用户给的 `query-my-coupons`、`campaign-calendar` 不一致。助手据此**提示用户可能存在工具名错误**。

随后抓取官方仓库原文核对，**证明是助手判断有误**：

| 工具名 | 官方 v1.0.9 文档 | 第三方站点（旧版） |
|---|---|---|
| `query-my-coupons` | ✅ 我的优惠券查询 | ❌ 写作 `my-coupons` |
| `query-my-account` | ✅ 我的积分查询 | ❌ 未列出 |
| `available-coupons` | ✅ 麦麦省券列表查询 | ✅ |
| `campaign-calendar` | ✅ 活动日历查询工具 | ❌ 写作 `campaign-calender`（拼写不同） |

**结论**：用户提供的四个工具名**全部正确**；第三方目录站信息陈旧。
此事在回复中已向用户明示更正。

> 这条记录保留下来，是因为它印证了本项目的一条设计选择：
> **字段与工具名以官方仓库原文为准，第三方二手信息不足为凭。**
> 后续 `test_submission_ready.py` 中"文档工具名 == 代码工具名"的一致性测试即源于此。

---

## 阶段 1 · SKILL.md 骨架

**动作**：先读取本机已安装的既有 Skill（`~/.workbuddy/skills/<已安装 Skill>/SKILL.md`）
确认 frontmatter 规范（`name` + 多行 `description`），再据此编写 `SKILL.md`。

**写下的关键约束**（后续全部落到代码）：

- 强制安全边界章节，列出绝不执行的工具类别；
- 声明"字段缺失时标注 `[字段缺失]`"；
- 声明 Token 只来自环境变量。

**验证**：新建 `tests/test_skill_manifest.py`，
用**纯标准库**实现受限 YAML frontmatter 解析（环境无 PyYAML，不为测试引入依赖）。

```
Ran 8 tests — OK
```

其中 `test_name_matches_directory` 断言 frontmatter 的 `name` 与目录名一致，
`test_token_only_from_env` 断言正文不含形如真实 Bearer 的长串。

---

## 阶段 2 · MCP 连通性与工具清单验证

**动作**：实现 `scripts/mcd_client.py`（Streamable HTTP 客户端 + 只读白名单 + 双模式 + 脱敏），
再写 `scripts/verify_mcp.py` 做结构化验证。

**验证结果**：

```
==============================================================
麦当劳 MCP 连通性验证  —  https://mcp.mcd.cn
==============================================================
[PASS] 端点可达性与鉴权保护
       status: 403   guarded: True
[PASS] 只读白名单包含全部官方查询工具
[PASS] mock 工具清单 == 官方清单
[PASS] skipped 真实服务器工具清单 vs 官方清单（未配置 Token）
--------------------------------------------------------------
结论：全部通过
```

**随即发现并修复一个真实脱敏漏洞。** 手工验证脱敏时输出：

```
Authorization: Bearer abcd…          -> Bearer ***        ✅
sk_live_aaaaaaaa…(40 位十六进制)      -> 原文泄露 ❌
```

**根因**：原正则 `\b[0-9a-fA-F]{32,}\b` 依赖词边界，
而 `sk_live_` 末尾的 `_` 是单词字符，`_` 与 `a` 之间**不存在词边界**，故未匹配。

**修复**：重写为规则表，并对长十六进制 / 长 base64url 串**去掉词边界限制**，
取向明确为"宁可过度脱敏，也不放过一枚 Token"。

修复后复验：

```
Authorization: Bearer abcd…   -> Bearer ***
sk_live_aaaa…                 -> sk_***
"authorization": "Bearer …"   -> "authorization": "***"
64 位 SHA-256                  -> ***
正常内容 "MOCK-C-1001 麦辣鸡腿堡买一送一 8元" -> 不受影响 ✅
```

该缺陷已固化为回归用例 `test_sk_live_regression`。

---

## 阶段 3 · 统一数据结构

**动作**：实现 `scripts/normalize.py`。

**关键设计**（源于阶段 0 的核查结论——官方未公开响应字段级 schema）：

- 每个规范字段配一组**别名**，逐个试取；
- 取不到 → `None` + 记入 `missing`，**不填默认值**；
- 日期解析覆盖 11 种形态；
- 解析失败返回 `None` 而非抛异常。

**验证**（对内置 fixtures 做往返解析）：

```
--- parse_date ---
  2026-10-25 / 2026/10/25 / 2026年10月25日 / 20261025 / 时间戳 / 带时区ISO  -> 均正确
  2026-02-30  -> None      （不存在的日期，绝不"修正"为 2-28）
  "无"        -> None

--- 我的券 ---
  MOCK-C-1001  left=0     今天到期        val=None missing=2
  MOCK-C-1005  left=None  [字段缺失]      val=3.0  missing=2
  MOCK-C-1006  left=-10   已过期 10 天    val=10.0 missing=0
```

**开发中调整的一处**：`parse_number` 初版对 `"满30减8"` 会取到第一个数字 `30`。
若真实接口把折扣写成这种句式，就会把"优惠 8 元"误报成"优惠 30 元"——**属于编造**。
改为：**字符串中出现多于一个数字时拒绝解析**，交上层登记为缺失。

---

## 阶段 4 · 紧急度评分与报告

**动作**：实现 `radar.py`（纯 stdlib `datetime` 分级排序）与 `report.py`（8 节输出契约）。

**首次渲染发现问题 4 处**：

| # | 问题 | 修正 |
|:---:|---|---|
| 1 | `UNKNOWN` 券只在完整性段落被提及，**正文没有表格**，违反"单列展示"契约 | 第 4 节改为「可计划与待确认（P3/P4/UNKNOWN）」，UNKNOWN 独立成表；同步更新 SKILL.md |
| 2 | `query-my-account` 状态表显示"记录数 0"，实际数据已取到（积分是单对象而非列表） | 归一化后按"是否取到"记 1 |
| 3 | 已结束活动显示"已过期 15 天" | 活动措辞改为"已结束" |
| 4 | P1 条目里门槛信息重复出现两次 | 从 reason 中移除，只保留结构化字段 |

**端到端验证**：

```
[mock] 券 6 张 | P0=1 P1=1 P2=1 P3=0 P4=1 UNKNOWN=1 EXPIRED=1 | 可领取 2 | 活动 4 | 取数失败 0
```

**降级验证**（注入单点失败：`MCD_MOCK_FAIL=query-my-account`）：

```
  ! query-my-account 取数失败：[mock] 工具 query-my-account 被要求模拟失败
[mock] 券 6 张 | … | 取数失败 1
报告已写入：…
```

报告中该板块如实写为"**积分数据获取失败或未返回**"，其余 7 节照常输出。

---

## 阶段 5 · 自动化测试

**动作**：补全 `tests/`（共 7 个测试文件）与 `run_tests.py`。

**第一次全量运行：136 项，2 项失败。**

```
FAIL: test_token_implies_real
  AssertionError: 'mock' != 'real'

FAIL: test_table_escaping_of_pipe_characters
  AssertionError: '含\|竖线的券' not found
```

**两处都是测试代码自身的缺陷，不是产品逻辑错误**（如实记录）：

1. `mock.patch.dict(support.clean_env(), {...})` —— 打补丁的目标是一个**临时字典**，
   根本没有作用于 `os.environ`，因此"设置了 Token 应进入 real 模式"这条断言是**假通过**。
   修正：新增 `support.env_with()` 助手，统一 patch `os.environ` 本身并 `clear=True`。

2. 管道符转义用例里，那张券是"当天到期"，被归入第 2 节"立即行动"的**要点列表**——
   列表不需要表格转义。修正：改用 5 天后到期的券（落入表格），
   并额外补一条断言说明"要点列表按原文输出"。

**修复后**：

```
$ python run_tests.py
OK
------------------------------------------------------------
共 136 项 | 失败 0 | 错误 0 | 跳过 0
```

---

## 阶段 6 · 参赛文件整理

**动作与验证**：

| 动作 | 验证 |
|---|---|
| 抓取官方 `CONTEST_DECLARATION.md` 并**字节级拷贝** | `md5sum` 双方均为 `91a7b32ec28098b609ca3f215cdf7147`，`cmp` 通过，1522 字节 |
| 写 `mcp-config.example.json` | 仅含 `Bearer YOUR_MCP_TOKEN` 占位符 |
| 写 `README.md` / `MCP_INTEGRATION.md` | 覆盖官方要求的三项内容 |
| 由代码生成 `references/data-schema.md` | `dump_schema.py --check` 通过，杜绝文档与代码漂移 |
| 新增 `tests/test_submission_ready.py` | 锁定必需文件、官方声明哈希（含 **CRLF 检测**）、仓库无凭据、文档与代码一致 |

`test_no_credentials_in_repo` 会对全部文本文件做凭据扫描
（Bearer 长串 / `sk_live_` / 32 位以上十六进制 / 中国大陆手机号），
并配有已核实的白名单（官方声明 MD5、测试用已知哈希），避免误报。

---

## 开发结果速览

| 指标 | 值 |
|---|---|
| 代码文件 | 7 个 Python 模块（全标准库，零第三方依赖） |
| 测试 | 13 个测试文件，**322 项，全绿**（第一轮 222 → 第三轮 322） |
| 只读拦截 | 8 个具名写入类工具 + 任意未知工具（默认拒绝） |
| 报告结构 | 8 节固定章节 + 已过期附录 |
| 真实缺陷修复 | 1 个脱敏漏洞、1 个数值误解析风险、4 处渲染问题、**1 个静默假阴性、1 个编造措辞**、1 处必需字段集误用（自查）、2 处"看起来像没数据"的误判 |
| 假通过修正 | 2 处测试缺陷 + 4 处断言口径问题 |

---

## 第二轮：接上真实连接器后的修复（同一日，15:25–15:45）

用户在 WorkBuddy 中配置好 `mcd-mcp` 连接器后，要求做一次**真实**连接测试：
先确认能发现工具，然后**只**调用 `campaign-calendar`，不得使用 mock、不得调用任何
下单/领券/积分兑换工具、不得暴露 Token 或账户敏感信息。

### 真实调用暴露的问题

工具发现正常（5 个只读工具，与官方 v1.0.9 名称一致），`campaign-calendar` 调用成功，
但**返回的是 Markdown 正文，不是 JSON**。本地验证发现现有链路的后果：

```
_maybe_json()      → 返回 str（类型没错）
find_records()     → 返回 []
build_bundle()     → 归一化后活动条数 0
integrity_notes()  → 空，不给任何提示
```

即：报告会显示"本月没有活动"，且不带任何警告。**这是静默假阴性**——
用户看到空白会认为确实没有活动，而真相是程序没读懂。
按项目的"不编造"原则，这比报错更危险，因为无从察觉。

### 修复一：状态分类（禁止假阴性）

引入 `PayloadState`，把"调用成功"与"数据被读懂"分开：

| 状态 | 含义 | 报告措辞 |
|---|---|---|
| `PARSED` | 成功且解析出记录 | 正常展示 |
| `EMPTY` | 成功，确实没有数据 | **只有此时**才可以说"没有活动" |
| `UNRECOGNIZED` | 成功、有内容、但读不懂 | 必须写"**收到数据，但解析失败**" |
| `FAILED` | 调用失败 | "取数失败 + 原因" |

判定"有内容"时忽略协议信封字段（`code` / `msg` / `success` / `total` …），
以免把 `{"code":0,"msg":"ok"}` 误判成"收到了数据"。
元信息里的活动条数在解析失败时显示"解析失败（原文 N 字符，**非 0**）"，
**不允许**显示 `0`——`0` 会被直接读成"本月没有活动"。

### 修复二：Markdown 活动解析器

按第一轮真实响应的实际结构实现 `parse_campaign_markdown()`：

* 识别 `#### 2026年10月9日 今日` 形式的日期分组（分隔符容忍 `年/月/日` 与 `-`/`/`/`.`）；
* 识别 `-   **活动标题**：` 起始的条目，及其下 `**活动内容介绍**` / `**活动图片介绍**` 字段块；
* 产出与 `CAMPAIGN_ALIASES` 对齐的记录字典 → **JSON 与 Markdown 共享同一套归一化逻辑**；
* 无法提取标题的条目、无条目的日期分组、非法日期标题、整份无法解析——**一律进警告列表**。

### 修复三：发现并改掉一处会编造的措辞

第一版修好后，报告把日历条目渲染成了 `P1 … 今天结束`。这是**编造**：

> 「超值 9.9 元早餐两件套」在 2026-10-09 被官方标注为「今日」，
> 而其实际售卖期是 **10-08 至 10-21**。

官方日历只回答"这条活动出现在哪一天"，**不提供有效期**；同理
「往期回顾」只表示该条已归档，**不代表活动本身已结束**。因此：

* 活动分级按来源分流：JSON 用有效期（`P0`–`P4`/`EXPIRED`），
  Markdown 用日历语义（`TODAY` / `UPCOMING` / `PAST`，排序号 10/12/16 单独号段）；
* 报告列名改为「日历状态 / 活动 / 日历日 / 官方分组 / 距今」，
  相对时间用"今天 / 明天 / N 天后"，**全文档不出现"今天结束""已结束"**；
* 官方不提供活动 ID，`MD-YYYYMMDD-NN` 明确标注为**解析生成的定位编号**
  （`synthetic_id=True`），报告与数据字典里都声明"不是官方 ID"。

### 修复四：凭据扫描器的一个真实误报

真实响应的 CDN 图片名（形如 `<32位十六进制>.jpg`）是长十六进制串，
被扫描器当成密钥拦下。加白名单是治标——真实响应样例会源源不断带进这类名字。
改为让扫描器**识别 URL 资源名上下文**（左侧紧邻 `/`、右侧紧邻 `.扩展名`），并补三条用例锁定：

* 独立出现的 32 位十六进制 → **仍拦截**；
* 藏在 URL 路径里的密钥（无扩展名）→ **仍拦截**；
* CDN 图片名 → 豁免。

顺带一提：新写的用例里那个假密钥字面量，**立刻被扫描器自己抓了出来**——
这正是它该做的事。

### 第二轮验证结果

```
$ python run_tests.py
共 222 项 | 失败 0 | 错误 0 | 跳过 0
```

第二轮真实调用 `campaign-calendar`（2026-10-09 15:39:31）与解析结果比对：

| 指标 | 人工计数 | 解析结果 | 结论 |
|---|---|---|---|
| 日期分组 | 12 | 12 | ✅ |
| 活动条目 | 30 | 30 | ✅ **无遗漏** |
| 2026-10-09「今日」 | 14 | 14 | ✅ |
| 解析警告 | — | 0 | — |

修复前后：报告显示的活动数 **0 → 30**；且不再出现"今天结束"这类编造措辞。
基准响应逐字副本存于 `fixtures/campaign_calendar.md`，完整验证过程存于
`references/live-verification.md`，渲染样例存于
`examples/sample-campaign-section-replay.md`。

## 第三轮：补齐另外三个工具的真实联调（同一日，15:48–16:02）

`campaign-calendar` 修好后，用户要求补齐**剩余三个只读工具**：
`query-my-coupons`、`query-my-account`、`available-coupons`。约束同样是
**不允许 Mock**、**不领取/不兑换/不下单**、**不需要用户把 Token 粘进聊天框**
（连接器已托管授权），涉及会员身份/券 ID/隐私的内容仅在受保护本地环境处理。

### 真实调用：四个工具返回三种格式

这一步最大的收获是**推翻了"响应应该是 JSON"的默认假设**——
四个工具里**只有一个是 JSON，而且是内嵌的**：

| 工具 | 真实格式 | 解析入口 |
|---|---|---|
| `query-my-coupons` | **Markdown**（`## 券名` + `- **字段**: 值`） | `parse_coupon_markdown()` |
| `query-my-account` | **说明性文本 + 内嵌 JSON**（`## Original Response` 之后） | `extract_embedded_json()` |
| `available-coupons` | **Markdown**（行尾 `\` 续行） | `parse_available_coupons_markdown()` |
| `campaign-calendar` | **Markdown**（`#### 日期` 分组） | `parse_campaign_markdown()` |

格式由 `normalize.observe_format()` **程序判定**，不是人工声称；判定结果直接印在报告第 5 节。

### 修复一：内嵌 JSON 的定位难题

`query-my-account` 的返回长得像这样（示意）：

```
## Response Structure
- **data.availablePoint**: 可用积分
- **data.accumulatedPoint**: 累计积分
...
## Original Response
{"code":0,"success":true,"data":{"availablePoint":120.0,...}}
```

用关键字切分会被上面那段**字段说明文本**骗到。改为
`extract_embedded_json()`：逐字符扫描并**配平大括号**，优先在 `## Original Response`
标记之后寻找完整对象。命中后交给既有 JSON 路径，与"纯 JSON"共用同一套别名表。

### 修复二：必需字段集必须按来源分流（自查发现）

为"我的券"设的必需字段集是 `(名称, 到期日)`。这个集合被**误用**到了
`available-coupons` 上，导致 9 条可领取券**全部虚报"缺到期日"**——
官方那一份 Markdown 本来就不含到期日。

修法：`normalize_coupon()` 里按 `source` 分流必需字段集：

```python
if coupon.source_format == "markdown":
    required = MD_COUPON_REQUIRED if source == "my" else MD_AVAILABLE_REQUIRED
else:
    required = None          # JSON 路径不做必需字段硬校验
```

**这是我自己复查出来的，不是测试报出的**——说明"看起来绿的测试"不等于覆盖到位。

### 修复三：「字段缺失」与「未提供」是两件事

真实数据里暴露出两种"没有值"：

* `[字段缺失]`：**取不到**（字段该有，解析器没拿到）；
* `未提供`：**官方格式本身不含这个字段**（例如可领取券的 Markdown 根本文没有到期日行）。

二者含义不同，混用会误导用户。新增 `Coupon.unknown_mark`，按 `source_format`
自动选择措辞；`ABSENT_FIELD_NOTES` 给出人话解释。

### 修复四：实付价不能被当成优惠额

`query-my-coupons` 里有券的官方原文是 `¥9.9 (用券价格)`。这是**用券后实付 9.9 元**，
**不是"省了 9.9 元"**。若粗暴地把数字读成优惠额，就是编造。新增
`benefit_kind`（`price` / `discount` / `unknown`）与 `classify_benefit()`，
把这类文案归为 `price` 并在报告列名上区分为「券面权益」。

### 修复五：北京时间基准

到期提醒必须按**北京时间**判定"今天"，否则跨时区/凌晨会把"今天到期"算成"明天到期"。
新增 `today_beijing()` / `now_beijing()`，固定 `timezone(timedelta(hours=8))`——
刻意**不用 `zoneinfo`**，因为 Windows 上它需要 tzdata 包，会破坏"零第三方依赖"承诺。

### 修复六：`accountId` 与签名 URL 的隐私处理

* `accountId`（UUID）：归一化时**即丢弃取值**，只记录"字段存在过"。
  不进数据结构、不进报告、不进日志、不进 `--dump-raw`。
* CDN 图片 URL 带 `q-ak=` / `q-signature=` 等参数：属**有时效凭据**，
  导出时经 `mask_sensitive()` 掩码（**键名保留、取值替换**，便于排查又不泄密）。

上一轮用的 `redact()` 是"宁可过度遮蔽"，用在 `--dump-raw` 上会把结构也涂掉；
本轮改为"结构保留式掩码"，两个函数按用途分工。

### 修复七：三种"看起来像没数据"的情况必须分开

| 情况 | 之前 | 现在 |
|---|---|---|
| 只有标题 `### 麦麦省优惠券列表：` | 报"**解析失败**"（吓人，其实是真空） | 判为 `EMPTY`，说"确实没有" |
| 只有协议信封 `{"code":0,"success":true}` | 列出一屏 `[字段缺失]`（像接口坏了） | 判为"无有效数据"，不列表 |
| 有实质内容但零记录 | 说"没有数据"（**静默假阴性**） | 判为 `UNRECOGNIZED`，报"**收到数据，但解析失败**" |

新增 `_is_effectively_empty()`（先跳过标题与计数声明再判断）与
`_has_account_fields()`（确认真的含积分字段），把三者分开。

### 第三轮验证结果

```
$ python run_tests.py
共 322 项 | 失败 0 | 错误 0 | 跳过 0
```

四个工具的真实响应解析率：

| 工具 | 状态 | 识别格式 | 解析/实际 | 成功率 | 未映射字段 |
|---|---|---|---|:---:|---|
| `query-my-coupons` | ✅ PARSED | markdown | 14 / 14 | 100% | 无 |
| `query-my-account` | ✅ PARSED | json（内嵌于说明文本） | 1 / 1 | 100% | `accountId`（按隐私策略刻意排除） |
| `available-coupons` | ✅ PARSED | markdown | 9 / 9 | 100% | 无 |
| `campaign-calendar` | ✅ PARSED | markdown | 30 / 30 | 100% | 无 |

端到端（replay 模式，跑的是真实响应副本）：

```
[replay] 券 14 张 | P0=2 P1=3 P2=4 P3=5 P4=0 UNKNOWN=0 EXPIRED=0
       | 可领取 9 | 活动 30 | 取数失败 0 | 解析失败 0
```

`campaign-calendar` 经三轮真实调用（15:26 / 15:39 / 16:02）结构一致，
**零回归**。本轮新增测试文件 4 个（`test_coupon_markdown.py` 33 项、
`test_available_coupons.py` 18 项、`test_account_payload.py` 25 项、
`test_replay_pipeline.py` 24 项），测试总数 222 → **322**。

### 本轮修掉的一个测试自身缺陷（如实记录）

`test_duplicate_names_kept_as_separate_coupons` 期望 5 张同名券，实际 4 张。
核对 fixture 后确认**是断言写错了**（该名称确实只有 4 条，第 5 条是另一个名字），
改为 4 并补一条"4 个不同到期日"的校验。

另有三处断言口径问题（`counts` 未出现的等级、UNKNOWN 的 reason 措辞、
报告中 `accountId` 作为字段名出现）也已按真实语义修正。

---

## 未完成事项（如实列出）

1. **四个工具的真实格式已确认，但字段映射是"单次快照"级验证。**
   已实测：`query-my-coupons` / `available-coupons` / `campaign-calendar` 返回 Markdown，
   `query-my-account` 返回说明文本包裹的内嵌 JSON，解析率均 100%。
   但这是 **2026-10-09 单次快照**——官方字段名随券类型与活动配置浮动。
   本项目对已出现字段做了映射，对**未出现过字段**只能保留为"未映射"并在报告第 8 节列出。
   拿到新 Token 后建议再跑一次收敛别名表：
   ```bash
   MCD_MCP_TOKEN=*** python scripts/run_radar.py --mode real --dump-raw raw/
   ```
2. **活动日历没有有效期。** 官方不提供起止时间，无法回答"还剩几天"，报告已如实声明。
3. **同一活动在多日重复出现时不去重。** 官方日历本身即如此，刻意保留原貌。
4. **本机无法直接跑 `--mode real`。** 连接器由 WorkBuddy 托管，Token 不在本进程环境变量中，
   真实链路验证通过"真实响应逐字副本 + 本地解析（`--mode replay`）"完成，
   **未走 CLI 的 real 分支**。README 已如实写明 `--mode real` 的适用条件，
   **未宣称在 WorkBuddy 会话内验证通过**。
5. **GitHub 仓库尚未创建、未提交 Issue 报名。** 项目需为 Public 仓库且创建时间在
   2025-12-25 至 2026-10-25 之间。
6. **Skill 尚未安装到 `~/.workbuddy/skills/`。** 当前验证均在项目目录内以 CLI 完成。
7. 本文为对话整理稿，若官方要求 WorkBuddy 导出的原始记录，需另行导出附上。
