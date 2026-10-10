"""超麦权益雷达 · 采集目录校验器。

**它解决的问题**：在 WorkBuddy 里，四个 MCP 工具的返回需要先落盘、再交给本项目的
解析与排序逻辑。如果落盘的内容不是**逐字原始载荷**，而是被转述过的摘要，
那么报告里的分级与排序就失去了依据——等于让大模型"自由总结"，这正是本 Skill 要避免的。

本脚本对采集目录做三项检查：

1. **完整性**：四个工具的文件都在、且非空；
2. **可读性**（硬性门槛）：每个文件能被本项目解析到 ``PARSED``（有记录）或 ``EMPTY``（确实为空）；
   落在 ``UNRECOGNIZED``（收到内容但读不懂）一律判失败；
3. **逐字性**（启发式告警）：检查是否缺少官方结构特征、是否出现"转述腔"用语。

用法::

    python scripts/verify_capture.py --dir capture/
    python scripts/verify_capture.py --dir capture/ --json

退出码：``0`` 全部通过；``1`` 有文件缺失或解析失败；``2`` 目录不存在。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize import PayloadState, build_bundle, today_beijing  # noqa: E402
from run_radar import FETCH_ORDER, load_replay  # noqa: E402

#: 每个工具在**真实响应**里必然出现的结构特征（用于判断是否为逐字载荷）。
#: 同时给出 JSON 合成样例的替代特征，避免把合法的离线样例误判为"被转述"。
STRUCTURE_MARKERS: dict[str, tuple[str, ...]] = {
    "query-my-coupons": ("##", "- **", "couponList", "couponName"),
    "query-my-account": ("availablePoint", "availablePoints", "Original Response", "data"),
    "available-coupons": ("优惠券标题", "couponName", "麦麦省", "data"),
    "campaign-calendar": ("####", "活动标题", "campaignName", "campaignList"),
}

#: "转述腔"用语：出现即高度怀疑落盘的是摘要而非原文。
TRANSCRIBED_PHRASES: tuple[str, ...] = (
    "我帮你查",
    "帮你整理",
    "以下是汇总",
    "以下是我",
    "总结如下",
    "共查询到",
    "一共找到",
    "根据查询结果",
    "工具返回了",
    "这说明",
)

#: 低于此字符数却声称"有记录"的载荷，多半是被压缩过的摘要
SUSPICIOUS_MIN_CHARS = 40


def check_one(tool: str, status, raw_text: str | None) -> dict:
    """返回单个数据源的检查结果。"""
    state = getattr(status, "state", None)
    result = {
        "tool": tool,
        "present": raw_text is not None,
        "chars": len(raw_text) if raw_text else 0,
        "state": getattr(state, "value", str(state)) if state is not None else "MISSING",
        "observed_format": getattr(status, "observed_format", "unknown"),
        "records": getattr(status, "record_count", 0),
        "ok": getattr(status, "ok", False),
        "error": getattr(status, "error", None),
        "problems": [],
        "warnings": [],
    }

    if raw_text is None:
        result["problems"].append("文件缺失：采集目录里找不到该工具的原始返回")
        return result

    if not raw_text.strip():
        result["problems"].append("文件为空")
        return result

    if state is PayloadState.FAILED:
        result["problems"].append(f"取数失败：{result['error']}")
    elif state is PayloadState.UNRECOGNIZED:
        result["problems"].append(
            f"收到 {result['chars']} 字符内容，但本项目的解析器读不懂——"
            "该板块的空白不代表没有权益。请确认落盘的是原始返回（不是摘要）。"
        )

    # ---- 逐字性启发式 ----
    markers = STRUCTURE_MARKERS.get(tool, ())
    if markers and not any(m in raw_text for m in markers):
        result["warnings"].append(
            "未发现该工具返回的已知结构特征（如 " + " / ".join(markers[:2]) + " …），疑似被转述或格式有变"
        )

    hit_phrases = [p for p in TRANSCRIBED_PHRASES if p in raw_text]
    if hit_phrases:
        result["warnings"].append("出现疑似转述用语：" + "、".join(hit_phrases))

    if result["records"] > 0 and result["chars"] < SUSPICIOUS_MIN_CHARS:
        result["warnings"].append(f"仅 {result['chars']} 字符却解析出 {result['records']} 条记录，疑为压缩后的摘要")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_capture",
        description="校验采集目录里四个 MCP 工具的原始返回是否完整、可解析、未被转述。",
    )
    parser.add_argument("--dir", required=True, metavar="DIR", help="采集目录（含四个工具的原始返回文件）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    args = parser.parse_args(argv)

    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"❌ 采集目录不存在：{directory.resolve()}", file=sys.stderr)
        return 2

    results = load_replay(directory)
    bundle = build_bundle(results, mode="replay", today=today_beijing())

    checks: list[dict] = []
    tool_by_name = {s.tool: s for s in bundle.sources}
    for tool in FETCH_ORDER:
        status = tool_by_name.get(tool)
        raw = results.get(tool)
        raw_text = None
        if raw is not None and getattr(raw, "ok", False) and isinstance(getattr(raw, "data", None), str):
            raw_text = raw.data
        elif raw is not None and getattr(raw, "ok", False):
            raw_text = json.dumps(getattr(raw, "data", None), ensure_ascii=False)
        checks.append(check_one(tool, status, raw_text))

    failed = [c for c in checks if c["problems"]]

    if args.json:
        print(json.dumps({"dir": str(directory.resolve()), "checks": checks, "ok": not failed}, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"采集目录校验  —  {directory.resolve()}")
        print("=" * 62)
        for c in checks:
            label = "✅" if not c["problems"] else "❌"
            print(f"{label} {c['tool']}")
            print(
                f"     文件：{'有' if c['present'] else '缺失'} | 体量：{c['chars']} 字符"
                f" | 识别格式：{c['observed_format']} | 解析记录：{c['records']} 条"
                f" | 状态：{c['state']}"
            )
            for p in c["problems"]:
                print(f"     ⛔ {p}")
            for w in c["warnings"]:
                print(f"     ⚠️  {w}")
        print("-" * 62)
        if failed:
            print(f"结论：{len(failed)} 个数据源未通过。**请勿**据此生成报告——先补齐/重采原始返回。")
        else:
            warned = [c for c in checks if c["warnings"]]
            if warned:
                print(f"结论：四个数据源均可解析，但有 {len(warned)} 处逐字性告警，请人工确认落盘内容为原始返回。")
            else:
                print("结论：四个数据源的原始返回齐备且可解析，可以进入解析与排序流程。")
            print("下一步：python scripts/run_radar.py --mode replay --replay-dir " + str(directory) + " --out report.md")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
