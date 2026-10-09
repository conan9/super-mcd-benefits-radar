"""Token 脱敏测试 —— 对应开发原则 5「严禁泄露 Token」。

包含一个**真实回归用例**：开发过程中 ``redact()`` 曾漏掉 ``sk_live_<40位十六进制>``，
原因是 ``\\b`` 词边界在 ``_`` 之后不成立。此用例锁定该缺陷不再复现。

注意：本文件中的全部密钥均为**伪造字符串**，仅用于测试脱敏逻辑。
"""

from __future__ import annotations

import unittest

import support  # noqa: F401
from mcd_client import MCPTransportError, MCDClient, redact

#: 伪造密钥（非真实凭据）
FAKE_BEARER = "Bearer abcd1234efgh5678ijkl9012mnop3456"
FAKE_SK_LIVE = "sk_live_" + "a" * 40
FAKE_HEX64 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
FAKE_B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuv0123456789-_zyx"


class TestRedactRegressions(unittest.TestCase):
    def assert_no_secret(self, rendered: str, secret: str) -> None:
        self.assertNotIn(secret, rendered, f"密钥泄漏：{secret[:12]}…")

    def test_bearer_header(self) -> None:
        out = redact(f"Authorization: {FAKE_BEARER}")
        self.assert_no_secret(out, "abcd1234efgh5678ijkl9012mnop3456")
        self.assertIn("Bearer ***", out)

    def test_sk_live_regression(self) -> None:
        """回归：``_`` 之后的 40 位十六进制串必须被脱敏。"""
        out = redact(FAKE_SK_LIVE)
        self.assert_no_secret(out, "a" * 40)

    def test_sha256_style_hex(self) -> None:
        out = redact(f"指纹：{FAKE_HEX64}")
        self.assert_no_secret(out, FAKE_HEX64)

    def test_base64url_long_string(self) -> None:
        out = redact(f"key={FAKE_B64URL}")
        self.assert_no_secret(out, FAKE_B64URL)

    def test_json_authorization_field(self) -> None:
        out = redact('{"authorization": "Bearer SECRETVALUE0123456789"}')
        self.assert_no_secret(out, "SECRETVALUE0123456789")

    def test_explicit_secret_list(self) -> None:
        """显式传入的密钥即使形态普通也要被替换。"""
        out = redact("错误：token 为 plainvalue 无效", ["plainvalue"])
        self.assert_no_secret(out, "plainvalue")

    def test_secret_in_nested_structure(self) -> None:
        payload = {"headers": {"Authorization": FAKE_BEARER}, "data": {"note": FAKE_SK_LIVE}}
        out = redact(payload)
        self.assert_no_secret(out, "abcd1234efgh5678ijkl9012mnop3456")
        self.assert_no_secret(out, "a" * 40)

    def test_non_ascii_payload_serializes(self) -> None:
        out = redact({"名称": "麦辣鸡腿堡", "数量": 2})
        self.assertIn("麦辣鸡腿堡", out)

    def test_does_not_mangle_normal_domain_text(self) -> None:
        """脱敏不得误伤正常业务内容，否则报告会失去可读性。"""
        text = "MOCK-C-1001 麦辣鸡腿堡买一送一 优惠 8 元 到店取餐 2026-10-09"
        self.assertEqual(redact(text), text)

    def test_short_hex_like_id_survives(self) -> None:
        """券 ID 通常是短串，不应被当作密钥抹掉。"""
        self.assertEqual(redact("券ID MOCK-C-1001"), "券ID MOCK-C-1001")


class TestNoLeakThroughErrorPaths(unittest.TestCase):
    """最危险的泄露路径：异常信息。"""

    def test_error_message_containing_token_is_scrubbed(self) -> None:
        client = MCDClient(mode="mock")
        client.secrets = [FAKE_SK_LIVE]

        class Exploding:
            mode = "mock"

            def rpc(self, method, params):
                raise MCPTransportError(f"上游拒绝，凭据 {FAKE_SK_LIVE} 无效")

        client.transport = Exploding()
        result = client.call_tool("query-my-coupons")
        self.assertFalse(result.ok)
        self.assertNotIn("a" * 40, result.error or "")

    def test_tool_result_serialization_keeps_token_out(self) -> None:
        client = MCDClient(mode="mock")

        class Leaky:
            mode = "mock"

            def rpc(self, method, params):
                return {"content": [{"type": "text", "text": '{"ok": true, "Authorization": "' + FAKE_BEARER + '"}'}]}

        client.transport = Leaky()
        result = client.call_tool("query-my-coupons")
        self.assertTrue(result.ok)
        # 返回值本身来自服务端，不做改写；但写入报告前必须经过 redact
        self.assertNotIn("abcd1234efgh5678ijkl9012mnop3456", redact(result.data))


if __name__ == "__main__":
    unittest.main(verbosity=2)
