# fixtures/ · 数据样例说明

本目录是 **mock 模式与 replay 模式的唯一数据来源**。仓库内所有样例都是
**合成样例**，不含任何真实账户数据、积分记录、凭据或素材地址。

| 文件 | 用途 | 内容性质 |
|---|---|---|
| `query_my_coupons.json` | mock 模式：结构化「我的券」 | 合成（`_mock: true`） |
| `query_my_account.json` | mock 模式：结构化积分账户 | 合成（`_mock: true`） |
| `available_coupons.json` | mock 模式：结构化可领取券 | 合成（`_mock: true`） |
| `campaign_calendar.json` | mock 模式：结构化活动列表 | 合成（`_mock: true`） |
| `query_my_coupons.md` | replay 模式：Markdown 券列表（14 张） | **合成**（结构对标真实响应） |
| `query_my_account.txt` | replay 模式：说明文本 + 内嵌 JSON | **合成**（结构对标真实响应） |
| `available_coupons.md` | replay 模式：Markdown 可领取券（9 条） | **合成**（结构对标真实响应） |
| `campaign_calendar.md` | replay 模式：Markdown 活动日历（30 条 / 12 分组） | **合成**（结构对标真实响应） |

## 为什么是合成样例

四个 `.md` / `.txt` 的**格式结构**来自 2026-10-09 对麦当劳中国官方 MCP 的
真实调用（四个工具没有一个是纯 JSON，且互不相同）。**真实响应本身含有账户数据**
（券清单、积分余额），因此：

* 不随公开仓库分发；
* 仓库内提供**逐行结构一致、取值全部替换**的合成样例，用于：
  1. 让解析器面对真实格式（而不是理想化的 JSON）；
  2. 让 `tests/` 中的格式测试与端到端回放测试可以完全离线运行；
  3. 让任何人 clone 之后就能跑出完整报告，而不需要先申请 Token。

合成方式见仓库内的转换说明；判定依据是**行内标记**：
合成样例中的券名/活动名一律带 `【合成样例】` 前缀，一眼可辨，不会与真实数据混淆。

## 用真实数据替换

把你自己采集的四个响应按**同名**覆盖到本目录，再运行：

```bash
python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md
```

解析、分级、排序、渲染走的是与联网完全相同的链路；
`tests/test_coupon_markdown.py`、`test_available_coupons.py`、
`test_account_payload.py`、`test_campaign_markdown.py`、`test_replay_pipeline.py`
的断言以本目录样例的取值为基准，替换数据后需同步更新这些断言。

> ⚠️ 请勿把含真实账户数据的响应提交到任何公开仓库。
