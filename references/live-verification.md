# 真实 MCP 调用验证记录（脱敏摘要）

本文件记录 2026-10-09 使用 WorkBuddy 已托管授权的 `mcd-mcp` 连接器，
对四个**只读**工具做真实调用后得到的**格式结论**与**解析结果**。

> **数据边界**：本文只保留工程结论。真实响应的逐字副本**含账户数据**
> （券清单、积分余额），**未随公开仓库分发**；仓库内 `fixtures/` 是
> 结构逐行对标、取值全部合成的样例。本文不复制任何响应原文、账号标识或素材地址。

## 1. 调用条件

| 项 | 值 |
|---|---|
| 时间 | 2026-10-09 |
| 端点 | `https://mcp.mcd.cn` |
| 连接器 | `mcd-mcp`（由 WorkBuddy 托管授权，Token 不进子进程环境变量） |
| 调用工具 | `query-my-coupons`、`query-my-account`、`available-coupons`、`campaign-calendar`（另有 `now-time-info` 用于校准基准日） |
| 写入类工具 | **一律未调用**（下单 / 领券 / 积分兑换 / 抽奖 / 取消） |
| Token 处理 | 全程不出现在输入、输出、日志与本仓库任何文件中 |

## 2. 核心结论：四个工具、三种格式

这是本项目最重要的一项实测事实——**官方返回不是统一 JSON**：

| 工具 | 实测格式 | 解析入口 | 解析率 |
|---|---|---|:---:|
| `query-my-coupons` | Markdown（`# 您的优惠券列表` + `## 券名` + `- **字段**: 值`） | `parse_coupon_markdown()` | 100% |
| `query-my-account` | 说明性文本 + **内嵌 JSON**（`## Response Structure` 字段说明段之后） | `extract_embedded_json()` | 100% |
| `available-coupons` | Markdown（`### 麦麦省优惠券列表：`，条目内**行尾反斜杠续行**） | `parse_available_coupons_markdown()` | 100% |
| `campaign-calendar` | Markdown（`#### 日期 + [往期回顾\|今日]` 分组） | `parse_campaign_markdown()` | 100% |

格式判定由 `normalize.observe_format()` **程序完成**，不是人工声称；
判定结果直接印在报告第 1 节的数据源状态表里。

## 3. 实测暴露的缺陷与修复

真实数据一到，暴露的都是"理想化 JSON 假设"留下的坑。按严重程度排列：

| # | 缺陷 | 后果 | 修复 |
|:---:|---|---|---|
| 1 | 活动日历是 Markdown，JSON 解析路径读不懂 | 报告显示"本月没有活动"且**不带任何警告**——静默假阴性 | 引入 `PayloadState` 四态（`PARSED` / `EMPTY` / `UNRECOGNIZED` / `FAILED`），只有 `EMPTY` 允许说"没有数据"；新增 `parse_campaign_markdown()` |
| 2 | 内嵌 JSON 外面裹着字段说明文本 | 直接 `json.loads` 整段失败，被误判为"读不懂" | `extract_embedded_json()` 逐字符配平大括号，优先在 `## Original Response` 标记后定位 |
| 3 | 可领取券 Markdown 不含到期日 | 若沿用「我的券」的必需字段集，9 条券全部虚报"缺到期日" | `normalize_coupon()` 按 `source` 分流必需字段集；并区分 `[字段缺失]`（取不到）与 `未提供`（格式本身不含） |
| 4 | 券面原文形如 `¥X (用券价格)` | 读成"优惠 X 元"就是编造 | 新增 `benefit_kind`（`price` / `discount` / `unknown`），实付价单独存放，绝不换算 |
| 5 | 日历条目被渲染成"今天结束" | 官方日历只有归档日、没有有效期，这是编造 | 活动分级按来源分流：JSON 用有效期，Markdown 用日历语义（`TODAY` / `UPCOMING` / `PAST`），全文档禁用"到期/结束"措辞 |
| 6 | 图片素材地址是 32 位十六进制文件名 | 凭据扫描器把公开资源名误报为密钥 | 扫描器识别"URL 资源名"上下文；独立出现的长十六进制**仍拦截**（三条用例锁定） |
| 7 | 返回含会员标识 `accountId` | 可能落进报告或导出 | 归一化时即**丢弃取值**，只记录"字段存在过" |

> 第 1 条是本项目"不编造"原则的分水岭：**误报比报错危险，因为无从察觉**。

## 4. 可复现性

上述结论在仓库内可**完全离线复核**：

```bash
python run_tests.py          # 全部测试，其中格式与端到端回放断言直接覆盖上述结论
python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md
```

`fixtures/` 的四个样例与真实响应**格式逐行同构**，因此解析器行为一致；
若要复核你自己账号的数据，把新采集的响应按同名覆盖 `fixtures/` 后重跑即可。

## 5. 局限（如实声明）

1. 上述格式结论是 **2026-10-09 的单次快照**。官方字段名随券类型与活动配置浮动；
   本项目对已出现过的字段做了映射，**对未出现过的字段只保留为"未映射"**
   并在报告第 8 节列出。
2. **CLI `--mode real` 未在 WorkBuddy 会话内验证。** 连接器由 WorkBuddy 托管，
   Token 不会导出到子进程环境变量，因此会话内的真实链路是
   "WorkBuddy 原生调度取数 → 写回放目录 → `--mode replay` 解析"，
   而不是 CLI 直连。README 与 `SKILL.md` 均已如实写明，未宣称 CLI `real` 可用。
3. **模型转写限制**：MCP 工具的返回需经模型上下文才能落到本机文件，
   因此落盘内容属于**模型转写**，`verify_capture.py` 一类校验**无法证明字节级一致**。
   本项目不对此做任何"逐字一致"的声明。
