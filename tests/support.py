"""测试公共支撑：路径注册与确定性样例数据。"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "fixtures"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

#: 测试统一使用的基准日，保证与 fixtures 中的相对日期对齐
TODAY = date(2026, 10, 9)

#: 用于泄露检测的哨兵 Token
SENTINEL_TOKEN = "SENTINEL-TOKEN-abcdefghijklmnop0123456789"


def mock_client():
    """构造 mock 模式客户端。

    ``MockTransport`` 必须带上 ``today=TODAY``：JSON 样例里的有效期写作
    ``${TODAY}`` / ``${TODAY+3}`` 这类**相对日期**，默认按真实当天解析。
    若不钉住基准日，样例的"今天到期"会随运行日期漂移，
    ``P0`` 会在第二天变成 ``P1``，断言随即失效（这是真实发生过的缺陷）。
    """
    from mcd_client import MCDClient, MockTransport

    return MCDClient(mode="mock", transport=MockTransport(today=TODAY))


def mock_results(tools: tuple[str, ...] | None = None):
    """抓取 fixtures 得到 ``{tool: ToolResult}``。"""
    tools = tools or (
        "query-my-coupons",
        "query-my-account",
        "available-coupons",
        "campaign-calendar",
    )
    client = mock_client()
    return {tool: client.call_tool(tool) for tool in tools}


def mock_bundle(today: date = TODAY):
    """构造归一化数据集。"""
    from normalize import build_bundle

    return build_bundle(mock_results(), mode="mock", today=today)


def mock_radar(today: date = TODAY):
    """构造体检结论。"""
    from radar import build_radar

    bundle = mock_bundle(today)
    return bundle, build_radar(
        bundle.my_coupons, bundle.available_coupons, bundle.campaigns, bundle.account, today
    )


def clean_env() -> dict:
    """返回一个不含 MCD_* 变量的环境副本。"""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MCD_")
    }


def env_with(**overrides: str) -> dict:
    """构造用于 ``mock.patch.dict(os.environ, ..., clear=True)`` 的环境字典。

    注意：必须直接 patch ``os.environ`` 本身，patch 一个临时字典是无效的
    （曾因此产生一个假通过的用例）。
    """
    env = clean_env()
    env.update(overrides)
    return env


#: 四个工具的**官方响应格式**样例（2026-10-09 实测）。
#: 样例为**结构逐行对标真实响应、取值全部合成**（真实响应含账户数据，未随仓库分发）。
#: 这是本套件区别于 mock JSON 样例的关键：它锁住的是**线上真实格式**
#: （Markdown / 说明文本包裹的 JSON），而不是结构化 JSON 解析路径。
#: 因此这四个样例的日期是**绝对日期**，与下面 ``TODAY`` 绑定。
REAL_FIXTURES: dict[str, str] = {
    "query-my-coupons": "query_my_coupons.md",
    "query-my-account": "query_my_account.txt",
    "available-coupons": "available_coupons.md",
    "campaign-calendar": "campaign_calendar.md",
}


def read_fixture(name: str) -> str:
    """读取 ``fixtures/`` 下的样例文本。"""
    return (FIXTURES / name).read_text(encoding="utf-8")


def real_results(tools: tuple[str, ...] | None = None) -> dict:
    """用真实响应副本构造 ``{tool: ToolResult}``。

    与 :func:`mock_results` 的区别：那个读的是**合成 JSON**（走结构化解析路径），
    这个读的是**线上真实格式**（走文本解析 / 内嵌 JSON 路径）。
    """
    from mcd_client import ToolResult

    names = tools or tuple(REAL_FIXTURES)
    return {
        tool: ToolResult(tool=tool, ok=True, data=read_fixture(REAL_FIXTURES[tool]), mode="replay")
        for tool in names
    }


def real_bundle(today: date = TODAY):
    """用真实响应副本构造归一化数据集。"""
    from normalize import build_bundle

    return build_bundle(real_results(), mode="replay", today=today)


__all__ = [
    "FIXTURES",
    "REAL_FIXTURES",
    "ROOT",
    "SCRIPTS",
    "SENTINEL_TOKEN",
    "TODAY",
    "clean_env",
    "env_with",
    "mock_bundle",
    "mock_client",
    "mock_radar",
    "mock_results",
    "read_fixture",
    "real_bundle",
    "real_results",
]
