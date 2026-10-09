# 麦当劳 MCP 工具清单（本技能相关部分）

> 来源：麦当劳中国官方仓库 [M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server) 的 `README.md`，
> 仓库内版本日志最新条目为 **v1.0.9（2026-09-10）**。
> 本文件为**摘录**，仅保留本技能用到的只读查询工具与必须拒绝的写入类工具。
> 如官方清单更新，请以官方仓库为准并同步修订 `scripts/mcd_client.py` 的 `OFFICIAL_TOOLS`。

## 接入参数（官方原文）

| 项 | 值 |
|---|---|
| 服务器接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权 | 请求头 `Authorization: Bearer YOUR_MCP_TOKEN` |
| 限流 | 每个 Token 每分钟最多 600 次请求（超出返回 `429`） |
| Token 申请 | https://open.mcd.cn/mcp |

### 官方错误码

| code | 原因 | 处理建议 |
|:---:|---|---|
| 401 | MCP Token 无效、已过期或未提供 | 检查 Authorization 请求头与 Token 配置 |
| 429 | 触发限流（超过 600 次/分钟） | 降低请求频率 |

## 本技能调用的四个只读工具（官方描述原文 + 实测返回格式）

| 工具名 | 官方名称 | 官方描述 |
|---|---|---|
| `query-my-coupons` | 我的优惠券查询 | 查询用户有哪些可用的优惠券。支持用户查看账户下所有优惠券列表 |
| `query-my-account` | 我的积分查询 | 查询用户积分账户信息，包括可用积分、累计积分、冻结积分、即将过期积分等 |
| `available-coupons` | 麦麦省券列表查询 | 查询用户当前可领取的麦麦省的优惠券列表 |
| `campaign-calendar` | 活动日历查询工具 | 查询麦当劳中国当月的营销活动日历，返回进行中、往期和未来日期的活动 |

**实测补充（2026-10-09，四个工具均完成真实调用）**：官方**只公开用途描述，不公开字段级 schema**，
且四个工具的返回**没有一个是纯 JSON**：

| 工具 | 实测返回格式 | 结构要点 | 格式基准样例 |
|---|---|---|---|
| `query-my-coupons` | **Markdown** | `# 您的优惠券列表` + `## 券名` + `- **字段**: 值`；字段种类随券类型浮动 | `fixtures/query_my_coupons.md` |
| `query-my-account` | **说明性文本 + 内嵌 JSON** | `## Response Structure`（字段说明）之后是 `## Original Response` 下的真 JSON | `fixtures/query_my_account.txt` |
| `available-coupons` | **Markdown** | `### 麦麦省优惠券列表：` + 每条以 `- ` 起始，**换行处有行尾 `\` 续行** | `fixtures/available_coupons.md` |
| `campaign-calendar` | **Markdown** | `#### YYYY年MM月DD日 [往期回顾\|今日]` 分组 + 每条含 `活动标题` / `活动内容介绍` / `活动图片介绍` | `fixtures/campaign_calendar.md` |

补充事实：

* 三份 Markdown **均不提供条目 ID**；本项目报告中的编号是解析生成的**定位编号**
  （`MC-MY-` / `MC-AVAIL-` / `MD-` 前缀），不是官方 ID。
* `campaign-calendar` **不提供活动有效期**，只回答"这条活动出现在哪一天"。
* `query-my-account` 的积分字段拼写为 `currentMouthExpirePoint`（**`Mouth` 而非 `Month`**），
  别名表按真实现状收录。
* `query-my-account` 返回含 `accountId`（会员账户 UUID），按隐私策略**只记录存在、不保存取值**。

格式结论与修复过程：`live-verification.md`；解析器：
`normalize.parse_coupon_markdown()` / `extract_embedded_json()` /
`parse_available_coupons_markdown()` / `parse_campaign_markdown()`。

辅助：`now-time-info`（获取当前时间信息）也在只读白名单中，用于校准基准日；
本技能默认以**北京时间**（UTC+8，`normalize.today_beijing()`）为准，仅在必要时参考该工具。

## 被本技能**明确拒绝**的工具（官方清单中存在，但不调用）

| 工具名 | 官方名称 | 拒绝理由 |
|---|---|---|
| `auto-bind-coupons` | 麦麦省一键领券 | 会改变账户权益状态 |
| `mcdelivery-order` | 麦乐送下单 | 产生消费 |
| `pickup-order` | 到店取餐下单 | 产生消费 |
| `group-meal-order` | 团餐下单 | 产生消费 |
| `mall-create-order` | 积分兑换商品下单 | 消耗积分 |
| `party-order-create` | 主题活动订单创建 | 产生消费 |
| `draw-lottery` | 积分抽奖 | 消耗积分或次数 |

> 拒绝策略在代码层实现为**白名单 + 默认拒绝**（`MCDClient.assert_read_only`），
> 因此上表只是"友好提示清单"，真正兜底的是白名单：
> **任何不在 `READ_ONLY_TOOLS` 里的工具都会被拦下**，包括将来官方新增的工具。
> 测试用例：`tests/test_client_guardrails.py::TestReadOnlyGuardrail`。

## 命名注意

第三方站点上流传的 `my-coupons` / `campaign-calender` 等写法来自**更早版本**的文档。
本技能采用官方仓库当前版本的工具名。若你看到的返回与本文不符，
请先运行 `python scripts/verify_mcp.py --real` 比对真实服务器清单。
