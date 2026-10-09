"""超麦权益雷达 · 一键入口。

用法::

    # 离线演示（默认，无需 Token）
    python scripts/run_radar.py --mode mock --out report.md

    # 离线演示 · 官方响应格式（回放 fixtures/ 中的合成格式样例）
    MCD_MOCK_FORMAT=real python scripts/run_radar.py --mode mock --out report.md

    # 回放离线采集到的响应样例（结构对标真实格式，不联网）
    python scripts/run_radar.py --mode replay --replay-dir fixtures --out report.md

    # 真实数据
    MCD_MCP_TOKEN=*** python scripts/run_radar.py --mode real --out report.md

    # 导出原始返回，用于核对字段映射
    python scripts/run_radar.py --mode mock --dump-raw raw/

安全约定：本脚本只调用只读工具；Token 仅从环境变量读取，输出前统一脱敏。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_client import (  # noqa: E402
    MCPAuthError,
    MCDClient,
    ToolResult,
    build_client,
    mask_sensitive,
    mode_from_env,
    redact,
)
from normalize import build_bundle, today_beijing  # noqa: E402
from radar import build_radar  # noqa: E402
from report import render_report, summarize  # noqa: E402

#: 抓取顺序：先核心（我的券），后补充
FETCH_ORDER: tuple[str, ...] = (
    "query-my-coupons",
    "query-my-account",
    "available-coupons",
    "campaign-calendar",
)

#: 回放目录里可识别的样例后缀（真实格式优先）
REPLAY_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".json")

DUMP_PRIVACY_NOTICE = """\
此目录含 MCD MCP 的原始返回，可能包含会员标识、券面信息与带签名的临时 URL。
已做两件事：
  1. 会员身份类字段（accountId / traceId / 手机号等）的值已就地掩码为「{mask}」；
  2. 带签名的图片 URL 只保留路径，签名参数已掩码。
但目录本身仍属**敏感数据**：默认已被 .gitignore 排除，请勿提交、勿上传、勿截图外传。
"""


def fetch_all(client: MCDClient) -> dict:
    """按顺序抓取四个数据源。单个失败不影响其余（降级而非中断）。"""
    return {tool: client.call_tool(tool) for tool in FETCH_ORDER}


def load_replay(directory: Path, tools: tuple[str, ...] = FETCH_ORDER) -> dict:
    """从目录回放已捕获的 MCP 响应，**不联网**。

    用于把"真实调用得到的响应"喂进本项目自己的解析与排序链路，
    使端到端验证可复现，而不是每次都要重新联网。
    """
    results: dict[str, ToolResult] = {}
    for tool in tools:
        stem = tool.replace("-", "_")
        found: Path | None = None
        for suffix in REPLAY_SUFFIXES:
            candidate = directory / f"{stem}{suffix}"
            if candidate.is_file():
                found = candidate
                break
        if found is None:
            results[tool] = ToolResult(
                tool=tool, ok=False, error=f"[replay] 未找到 {stem}.{{md,txt,json}}", mode="replay"
            )
            continue
        text = found.read_text(encoding="utf-8")
        data: object = text
        if found.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = text
        results[tool] = ToolResult(tool=tool, ok=True, data=data, mode="replay")
    return results


def dump_raw(results: dict, directory: Path) -> list[Path]:
    """把原始返回落盘，便于用真实数据核对字段映射。

    落盘前对会员身份类字段与 URL 签名参数做**结构保留式掩码**：
    键名与其它值不动（否则无法核对 schema），只有敏感值被遮蔽。
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for tool, result in results.items():
        payload = {
            "tool": tool,
            "ok": getattr(result, "ok", None),
            "error": redact(getattr(result, "error", None) or ""),
            "data": mask_sensitive(getattr(result, "data", None)),
        }
        path = directory / f"{tool}.raw.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    notice = directory / "README-PRIVACY.txt"
    notice.write_text(DUMP_PRIVACY_NOTICE.format(mask="<已按隐私策略掩码>"), encoding="utf-8")
    written.append(notice)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_radar",
        description="超麦权益雷达：只读汇总麦当劳优惠券/积分/活动，生成按紧急度排序的体检报告。",
    )
    parser.add_argument("--mode", choices=("mock", "real", "replay"), default=None, help="数据模式（默认按环境变量推断）")
    parser.add_argument("--out", default="report.md", help="报告输出路径")
    parser.add_argument("--today", default=None, help="覆盖基准日 YYYY-MM-DD（用于复现历史报告）")
    parser.add_argument("--dump-raw", default=None, metavar="DIR", help="导出原始返回到目录（已脱敏）")
    parser.add_argument(
        "--replay-dir",
        default=None,
        metavar="DIR",
        help="回放目录：从该目录读取已捕获的真实响应，不联网（隐含 --mode replay）",
    )
    parser.add_argument("--json", action="store_true", help="额外输出机器可读的结论摘要")
    parser.add_argument("--quiet", action="store_true", help="仅输出报告路径")
    args = parser.parse_args(argv)

    if args.replay_dir:
        args.mode = "replay"

    mode = "replay" if args.mode == "replay" else mode_from_env(args.mode)
    client: MCDClient | None = None
    if mode != "replay":
        try:
            client = build_client(mode)
        except MCPAuthError as exc:
            print(redact(str(exc)), file=sys.stderr)
            return 2

    # 基准日取北京时间：到期判定必须与麦当劳官方口径（UTC+8）一致，
    # 否则在东八区凌晨或跨时区机器上会把"今天到期"算成"明天到期"。
    today = date.fromisoformat(args.today) if args.today else today_beijing()

    results = load_replay(Path(args.replay_dir)) if mode == "replay" else fetch_all(client)
    bundle = build_bundle(results, mode=mode, today=today)
    radar = build_radar(bundle.my_coupons, bundle.available_coupons, bundle.campaigns, bundle.account, today)
    markdown = render_report(bundle, radar)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    failures = [s for s in bundle.sources if not s.ok]
    if not args.quiet:
        print(summarize(bundle, radar))
        for status in failures:
            print(f"  ! {status.tool} 取数失败：{redact(status.error or '')}", file=sys.stderr)
        print(f"报告已写入：{out_path.resolve()}")

    if args.dump_raw:
        for path in dump_raw(results, Path(args.dump_raw)):
            if not args.quiet:
                print(f"原始返回已导出：{path}")

    if args.json:
        print(
            json.dumps(
                {
                    "mode": bundle.mode,
                    "today": today.isoformat(),
                    "counts": radar.counts,
                    "claimable": len(radar.claimable),
                    "campaigns": len(radar.campaigns),
                    "sources": [s.__dict__ for s in bundle.sources],
                    "urgent": [a.as_dict() for a in radar.urgent],
                    "report": str(out_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    # 全部数据源失败时给出非零退出码，便于 CI 感知
    return 1 if failures and len(failures) == len(bundle.sources) else 0


if __name__ == "__main__":
    raise SystemExit(main())
