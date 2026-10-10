"""只读门禁与模式切换测试 —— 对应开发原则 3、5。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import support  # noqa: F401  (注册 sys.path)
from mcd_client import (
    DENIED_TOOLS,
    OFFICIAL_TOOLS,
    READ_ONLY_TOOLS,
    MCPAuthError,
    MCDClient,
    WriteOperationBlocked,
    mode_from_env,
)


class TestReadOnlyGuardrail(unittest.TestCase):
    """白名单 + 默认拒绝必须真的生效，而不只是写在文档里。"""

    def setUp(self) -> None:
        self.client = MCDClient(mode="mock")

    def test_every_denied_tool_is_blocked(self) -> None:
        for tool in DENIED_TOOLS:
            with self.subTest(tool=tool):
                result = self.client.call_tool(tool)
                self.assertFalse(result.ok, f"{tool} 不应成功")
                self.assertTrue(result.blocked, f"{tool} 应被标记为 blocked")

    def test_unknown_tool_is_blocked_by_default(self) -> None:
        """"默认拒绝"：不在白名单里的工具哪怕是只读性质的也拒绝。"""
        result = self.client.call_tool("some-new-tool-we-never-heard-of")
        self.assertTrue(result.blocked)

    def test_ordering_tools_blocked(self) -> None:
        for tool in ("mcdelivery-order", "pickup-order", "group-meal-order", "mall-create-order"):
            with self.subTest(tool=tool):
                self.assertTrue(self.client.call_tool(tool).blocked)

    def test_point_consuming_tools_blocked(self) -> None:
        """积分抽奖与积分兑换会消耗资产，必须拒绝。"""
        for tool in ("draw-lottery", "point-redemption", "mall-create-order"):
            with self.subTest(tool=tool):
                self.assertTrue(self.client.call_tool(tool).blocked)

    def test_assert_read_only_raises(self) -> None:
        with self.assertRaises(WriteOperationBlocked):
            MCDClient.assert_read_only("auto-bind-coupons")

    def test_assert_read_only_allows_whitelist(self) -> None:
        for tool in READ_ONLY_TOOLS:
            with self.subTest(tool=tool):
                self.assertIsNone(MCDClient.assert_read_only(tool))

    def test_blocked_calls_are_not_recorded(self) -> None:
        """被拦截的调用不该出现在调用记录里。"""
        self.client.call_tool("auto-bind-coupons")
        self.assertEqual(self.client.calls, [])

    def test_allowed_calls_are_recorded(self) -> None:
        self.client.call_tool("query-my-coupons")
        self.assertEqual(self.client.calls, ["query-my-coupons"])

    def test_official_tools_are_all_readonly(self) -> None:
        self.assertTrue(set(OFFICIAL_TOOLS) <= READ_ONLY_TOOLS)

    def test_readonly_set_is_minimal(self) -> None:
        """白名单不应偷偷扩大——只多一个用于校准时间的 now-time-info。"""
        self.assertEqual(READ_ONLY_TOOLS - set(OFFICIAL_TOOLS), {"now-time-info"})


class TestModeSelection(unittest.TestCase):
    def test_explicit_argument_wins(self) -> None:
        with mock.patch.dict(os.environ, {"MCD_MODE": "mock", "MCD_MCP_TOKEN": "x"}):
            self.assertEqual(mode_from_env("real"), "real")

    def test_env_mode_used(self) -> None:
        with mock.patch.dict(os.environ, {"MCD_MODE": "real", "MCD_MCP_TOKEN": "x"}):
            self.assertEqual(mode_from_env(None), "real")

    def test_token_implies_real(self) -> None:
        with mock.patch.dict(os.environ, support.env_with(MCD_MCP_TOKEN="x"), clear=True):
            self.assertEqual(mode_from_env(None), "real")

    def test_no_token_defaults_to_real(self) -> None:
        """默认真实模式 —— 刻意**不**回落 mock。

        曾经的行为是"没 Token 就用合成样例"，它会让用户拿到一份看起来正常的
        假报告却误以为是自己账户的真实权益。宁可报错，也不要静默造假。
        """
        with mock.patch.dict(os.environ, support.env_with(), clear=True):
            self.assertEqual(mode_from_env(None), "real")

    def test_default_mode_constant_is_real(self) -> None:
        from mcd_client import DEFAULT_MODE

        self.assertEqual(DEFAULT_MODE, "real")

    def test_mock_never_engages_without_explicit_optin(self) -> None:
        """没有 Token、也没有显式指定时，绝不自动切到 mock。

        断言的是**端到端行为**：按默认模式建客户端会抛 ``MCPAuthError``，
        而不是悄悄拿到一个 mock 客户端。
        """
        with mock.patch.dict(os.environ, support.env_with(), clear=True):
            resolved = mode_from_env(None)
            self.assertNotEqual(resolved, "mock", "无 Token 时不得回退到 mock")
            with self.assertRaises(MCPAuthError):
                MCDClient(mode=resolved)

    def test_mock_requires_explicit_selection(self) -> None:
        """``mock`` 只能由用户显式选择（参数或环境变量），并且真的生效。"""
        with mock.patch.dict(os.environ, support.env_with(MCD_MODE="mock"), clear=True):
            self.assertEqual(mode_from_env(None), "mock")
            self.assertEqual(MCDClient(mode=mode_from_env(None)).mode, "mock")
        self.assertEqual(mode_from_env("mock"), "mock")

    def test_real_mode_without_token_raises_helpful_error(self) -> None:
        with mock.patch.dict(os.environ, support.env_with(), clear=True):
            with self.assertRaises(MCPAuthError) as ctx:
                MCDClient(mode="real")
        message = str(ctx.exception)
        self.assertIn("MCD_MCP_TOKEN", message)
        self.assertIn("open.mcd.cn", message, "错误信息应给出申请 Token 的入口")

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MCDClient(mode="production")


class TestMockTransportIsolation(unittest.TestCase):
    """mock 模式不得发起网络请求。"""

    def test_mock_never_touches_network(self) -> None:
        import urllib.request

        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("不应联网")):
            client = MCDClient(mode="mock")
            for tool in OFFICIAL_TOOLS:
                self.assertTrue(client.call_tool(tool).ok)

    def test_missing_fixture_degrades_gracefully(self) -> None:
        from mcd_client import MockTransport

        transport = MockTransport(fixture_dir=support.ROOT / "tests" / "does-not-exist")
        client = MCDClient(mode="mock", transport=transport)
        result = client.call_tool("query-my-coupons")
        self.assertFalse(result.ok)
        self.assertIn("缺少样例数据", result.error or "")

    def test_mock_failure_injection(self) -> None:
        with mock.patch.dict(os.environ, {"MCD_MOCK_FAIL": "query-my-account"}):
            client = MCDClient(mode="mock")
            self.assertFalse(client.call_tool("query-my-account").ok)
            self.assertTrue(client.call_tool("query-my-coupons").ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
