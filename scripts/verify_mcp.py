"""S2 验证脚本：核实 MCP 端点真实可达性 + 工具清单与官方文档一致性。

用法::

    python scripts/verify_mcp.py            # 探测端点 + 校验 mock 清单
    MCD_MCP_TOKEN=xxx python scripts/verify_mcp.py --real   # 额外与真实服务器比对

退出码：0 = 全部通过；1 = 存在需人工确认的差异。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_client import (  # noqa: E402
    DEFAULT_URL,
    OFFICIAL_TOOLS,
    PROTOCOL_VERSION,
    READ_ONLY_TOOLS,
    MCDClient,
    redact,
)


def probe_endpoint(url: str, timeout: int = 15) -> dict:
    """不带 Token 握手，用返回码判断端点是否为受保护的 MCP 服务。

    预期：401 / 403 —— 说明服务真实存在且要求鉴权。
    若返回 200，反而说明该地址不是受保护的 MCP 入口。
    """
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "verify-mcd", "version": "1.0"},
            },
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"reachable": True, "status": response.status, "guarded": False, "detail": "未鉴权即成功"}
    except urllib.error.HTTPError as exc:
        body = redact(exc.read().decode("utf-8", errors="replace")[:200])
        return {
            "reachable": True,
            "status": exc.code,
            "guarded": exc.code in (401, 403),
            "detail": body,
        }
    except urllib.error.URLError as exc:
        return {"reachable": False, "status": None, "guarded": False, "detail": redact(str(exc.reason))}
    except Exception as exc:  # pragma: no cover - 环境相关
        return {"reachable": False, "status": None, "guarded": False, "detail": redact(str(exc))}


def diff_tools(actual: list[str], expected: dict[str, str]) -> dict:
    expected_set = set(expected)
    actual_set = set(actual)
    return {
        "missing": sorted(expected_set - actual_set),
        "extra": sorted(actual_set - expected_set),
        "matched": sorted(expected_set & actual_set),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证麦当劳 MCP 端点与工具清单")
    parser.add_argument("--url", default=os.environ.get("MCD_MCP_URL", DEFAULT_URL))
    parser.add_argument("--real", action="store_true", help="使用 Token 与真实服务器比对工具清单")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    report: dict = {"url": args.url, "checks": []}
    failures = 0

    # --- 检查 1：端点可达且受鉴权保护 -------------------------------------- #
    probe = probe_endpoint(args.url)
    ok1 = probe["reachable"] and probe["guarded"]
    report["checks"].append(
        {
            "name": "端点可达性与鉴权保护",
            "pass": ok1,
            "status": probe["status"],
            "guarded": probe["guarded"],
            "detail": probe["detail"],
        }
    )
    if probe["reachable"] and not probe["guarded"]:
        # 这可能只是网关行为差异，标记为需人工确认而非硬失败
        report["checks"][-1]["detail"] += "（未返回 401/403，请人工确认是否为企业网络代理返回）"
        failures += 1
    elif not probe["reachable"]:
        failures += 1

    # --- 检查 2：只读白名单自洽 -------------------------------------------- #
    leaked = sorted(set(OFFICIAL_TOOLS) - READ_ONLY_TOOLS)
    ok2 = not leaked
    report["checks"].append(
        {"name": "只读白名单包含全部官方查询工具", "pass": ok2, "missing": leaked}
    )
    failures += 0 if ok2 else 1

    # --- 检查 3：mock 清单与官方实现一致 ----------------------------------- #
    try:
        mock_client = MCDClient(mode="mock")
        mock_tools = mock_client.list_tools()
        d3 = diff_tools(mock_tools, OFFICIAL_TOOLS)
        ok3 = not d3["missing"] and not d3["extra"]
        report["checks"].append({"name": "mock 工具清单 == 官方清单", "pass": ok3, **d3})
        failures += 0 if ok3 else 1
    except Exception as exc:
        report["checks"].append({"name": "mock 工具清单 == 官方清单", "pass": False, "detail": str(exc)})
        failures += 1

    # --- 检查 4（可选）：真实服务器工具清单 -------------------------------- #
    if args.real:
        try:
            client = MCDClient(mode="real")
            info = client.initialize()
            real_tools = client.list_tools()
            d4 = diff_tools(real_tools, OFFICIAL_TOOLS)
            report["checks"].append(
                {
                    "name": "真实服务器工具清单 vs 官方清单",
                    "pass": not d4["missing"],
                    "serverInfo": info.get("serverInfo"),
                    "protocolVersion": info.get("protocolVersion"),
                    **d4,
                }
            )
            if d4["missing"]:
                failures += 1
        except Exception as exc:
            report["checks"].append(
                {"name": "真实服务器工具清单 vs 官方清单", "pass": False, "detail": redact(str(exc))}
            )
            failures += 1
    else:
        report["checks"].append(
            {
                "name": "真实服务器工具清单 vs 官方清单",
                "pass": None,
                "detail": "已跳过（未加 --real 或未配置 MCD_MCP_TOKEN）",
            }
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print(f"麦当劳 MCP 连通性验证  —  {report['url']}")
        print("=" * 62)
        for check in report["checks"]:
            flag = {True: "PASS", False: "FAIL", None: "SKIP"}[check["pass"]]
            print(f"[{flag}] {check['name']}")
            for key, value in check.items():
                if key in ("name", "pass"):
                    continue
                if value in ([], None, ""):
                    continue
                print(f"       {key}: {value}")
        print("-" * 62)
        print(f"结论：{'全部通过' if failures == 0 else f'{failures} 项需要关注'}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
