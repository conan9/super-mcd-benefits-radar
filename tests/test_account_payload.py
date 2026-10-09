"""「我的积分账户」真实响应格式的解析测试。

格式取自 2026-10-09 对官方 MCP `query-my-account` 的真实调用。
``fixtures/query_my_account.txt`` 是**结构逐行对标真实响应、取值全部合成**的样例
（真实响应含账户数据，不随公开仓库分发）。

这个接口的返回是**"人话包裹的 JSON"**——前面一段字段说明，`## Original Response`
之后才是真正的 JSON。直接 `json.loads` 整段会失败，早期实现因此把它归为"读不懂"。
本组测试锁住两件事：

* 能从说明文本里把真 JSON 取出来；
* 会员标识 `accountId` **取值为隐私，识别到存在即止，绝不落库、不进报告**。
"""

from __future__ import annotations

import json
import unittest

import support  # noqa: F401  (注册 scripts/ 到 sys.path)

from mcd_client import MASK, mask_sensitive
from normalize import (
    ACCOUNT_ABSENT,
    coerce_payload,
    extract_embedded_json,
    normalize_account,
    observe_format,
)

PRIVACY_PROBE = "00000000-0000-0000-0000-000000000000"


def _narrative() -> str:
    return support.read_fixture("query_my_account.txt")


class TestEmbeddedJsonExtraction(unittest.TestCase):
    def test_extracts_json_from_narrative(self) -> None:
        parsed = extract_embedded_json(_narrative())
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["code"], 200)

    def test_extracted_payload_contains_the_real_account_object(self) -> None:
        parsed = extract_embedded_json(_narrative())
        self.assertIn("availablePoint", parsed["data"])

    def test_field_description_section_is_not_mistaken_for_payload(self) -> None:
        """`## Response Structure` 里的 `- **data.availablePoint**: …` 不是数据，不能被当成记录。"""
        parsed = extract_embedded_json(_narrative())
        self.assertNotIn("data.availablePoint", parsed)

    def test_coerce_payload_unwraps_narrative(self) -> None:
        coerced = coerce_payload(_narrative())
        self.assertIsInstance(coerced, dict)
        self.assertEqual(coerced["data"]["availablePoint"], "120.0")

    def test_coerce_payload_passes_through_plain_json(self) -> None:
        self.assertEqual(coerce_payload('{"a": 1}'), {"a": 1})

    def test_coerce_payload_keeps_markdown_as_text(self) -> None:
        text = "## 某券\n- **优惠**: ¥9.9\n"
        self.assertEqual(coerce_payload(text), text)

    def test_coerce_payload_empty(self) -> None:
        self.assertEqual(coerce_payload("   "), "")

    def test_format_is_detected(self) -> None:
        self.assertEqual(observe_format(_narrative()), "json（内嵌于说明文本）")


class TestAccountFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.account = normalize_account(coerce_payload(_narrative()))

    def test_present(self) -> None:
        self.assertTrue(self.account.present)

    def test_all_numeric_fields_mapped(self) -> None:
        self.assertEqual(self.account.available, 120.0)
        self.assertEqual(self.account.total, 3000.0)
        self.assertEqual(self.account.frozen, 0.0)
        self.assertEqual(self.account.expiring_points, 0.0)
        self.assertEqual(self.account.used, 900.0)
        self.assertEqual(self.account.expired, 2000.0)
        self.assertEqual(self.account.next_expiring_points, 0.0)
        self.assertEqual(self.account.last_expired, 0.0)

    def test_zero_is_kept_as_zero_not_treated_as_missing(self) -> None:
        """冻结积分真实值就是 0——**0 与"缺失"是两回事**，不得混淆。"""
        self.assertEqual(self.account.frozen, 0.0)
        self.assertNotIn("frozen", self.account.missing)

    def test_currency_mapped(self) -> None:
        self.assertEqual(self.account.currency, "麦享会积分")

    def test_absent_fields_are_reported_as_not_provided(self) -> None:
        for field in ACCOUNT_ABSENT:
            self.assertIn(field, self.account.missing)
        self.assertIsNone(self.account.expiring_date)
        self.assertIsNone(self.account.level)


class TestPrivacy(unittest.TestCase):
    """会员标识绝不能出现在任何可被打印/提交的地方。"""

    def test_account_id_presence_is_recorded(self) -> None:
        account = normalize_account(coerce_payload(_narrative()))
        self.assertTrue(account.account_id_excluded)

    def test_account_id_value_is_not_stored(self) -> None:
        account = normalize_account(coerce_payload(_narrative()))
        self.assertNotIn(PRIVACY_PROBE, json.dumps(account.raw, ensure_ascii=False))
        self.assertNotIn(PRIVACY_PROBE, repr(account.__dict__))

    def test_account_id_absent_when_not_returned(self) -> None:
        account = normalize_account({"data": {"availablePoint": "10"}})
        self.assertFalse(account.account_id_excluded)
        self.assertEqual(account.available, 10.0)

    def test_mask_sensitive_masks_known_keys_but_keeps_structure(self) -> None:
        payload = {"data": {"accountId": "SECRET-VALUE", "availablePoint": "1"}}
        masked = mask_sensitive(payload)
        self.assertEqual(masked["data"]["accountId"], MASK)
        self.assertEqual(masked["data"]["availablePoint"], "1", "非敏感字段必须原样保留")

    def test_mask_sensitive_strips_url_signature_params(self) -> None:
        url = "https://x.example/a/b.jpg?sign=abc%3D1&q-signature=deadbeef&x=1"
        masked = mask_sensitive({"image": url})
        self.assertIn("<已掩码>", masked["image"])
        self.assertNotIn("deadbeef", masked["image"])
        self.assertIn("/a/b.jpg", masked["image"], "路径要保留，否则无法核对结构")


class TestEdgeCases(unittest.TestCase):
    def test_empty_payload_is_not_present(self) -> None:
        account = normalize_account("")
        self.assertFalse(account.present)

    def test_envelope_only_payload_is_not_present(self) -> None:
        """`{"code":0,"msg":"ok"}` 里没有账户数据 → 不得被当成"有数据"。"""
        account = normalize_account({"code": 0, "message": "请求成功"})
        self.assertFalse(account.present)

    def test_malformed_text_narrative_yields_no_record(self) -> None:
        self.assertIsNone(extract_embedded_json("## Original Response\n{不是 JSON"))
        self.assertFalse(normalize_account(coerce_payload("## Original Response\n{不是 JSON")).present)

    def test_missing_single_field_is_flagged(self) -> None:
        """删掉 usedPoint —— 缺失必须落到 missing，而不是当成 0。"""
        data = json.loads(_narrative().split("## Original Response")[1].strip())
        del data["data"]["usedPoint"]
        account = normalize_account(data)
        self.assertIn("used", account.missing)
        self.assertIsNone(account.used)

    def test_non_numeric_point_value_is_treated_as_missing(self) -> None:
        account = normalize_account({"data": {"availablePoint": "暂无"}})
        self.assertIsNone(account.available)
        self.assertIn("available", account.missing)

    def test_nested_list_shaped_payload_still_resolved(self) -> None:
        account = normalize_account({"data": [{"availablePoint": "5"}]})
        self.assertEqual(account.available, 5.0)

    def test_recursive_trailing_json_preferred_after_marker(self) -> None:
        text = '前置说明 {"ignored": true}\n## Original Response\n{"code":200,"data":{"availablePoint":"7"}}'
        parsed = extract_embedded_json(text)
        self.assertEqual(parsed["data"]["availablePoint"], "7")


if __name__ == "__main__":
    unittest.main()
