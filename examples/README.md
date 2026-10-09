# examples/ · 样例报告说明

本目录中的报告**全部由本项目代码生成**，数据来自 `fixtures/` 的合成样例。

| 文件 | 生成命令 | 数据来源 |
|---|---|---|
| `sample-report-mock.md` | `python scripts/run_radar.py --mode mock --out ...` | `fixtures/*.json`（合成） |
| `sample-report-replay.md` | `python scripts/run_radar.py --mode replay --replay-dir fixtures --out ...` | `fixtures/*.md` / `*.txt`（合成，结构对标真实响应） |
| `sample-campaign-section-replay.md` | 上一份报告第 6 节的节选 | 同上 |

三种模式（`mock` / `replay` / `real`）产出的报告**结构完全一致**，只有首行的模式横幅不同。

## 关于真实数据

开发期间曾用真实 MCP 返回生成过一份报告，**未随本仓库分发**——它包含
真实账户的券清单与积分余额。本目录中的 replay 样例与之结构完全同构，
区别仅在于取值全部为合成值（券名/活动名带 `【合成样例】` 前缀）。

验证过程中的**格式结论与解析率**（四个工具返回三种格式、解析率 100% 等）
记录在 [`../references/live-verification.md`](../references/live-verification.md)。

## 复现

```bash
python scripts/run_radar.py --mode mock --out report.md
python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md
```

两条命令都不联网、不需要 Token。
