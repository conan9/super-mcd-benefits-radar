"""取数状态分类 —— 锁定"解析失败不得伪装成没有数据"。

背景（真实事故）：``campaign-calendar`` 实际返回 Markdown 正文，
早期实现解析不出记录就直接产出零条活动，报告写"本月没有活动"，
却没有任何异常提示。**误报比报错危险，因为用户无从察觉。**

本文件逐条锁死四种状态的区分与呈现。
"""

from __future__ import annotations

import unittest
from datetime import date

import support
from normalize import (
    PayloadState,
    build_bundle,
    classify_state,
    has_payload_content,
    payload_text,
)
from normalize import MISSING_MARK  # noqa: F401  (与其它测试保持一致的导入习惯)
from radar import build_radar
from report import render_report

TODAY = date(2026, 10, 9)


def make_result(tool: str, ok: bool, data=None, error: str | None = None):
    from mcd_client import ToolResult

    return ToolResult(tool=tool, ok=ok, data=data, error=error, mode="real")


def render(results: dict) -> tuple[object, str]:
    bundle = build_bundle(results, mode="real", today=TODAY)
    radar = build_radar(
        bundle.my_coupons, bundle.available_coupons, bundle.campaigns, bundle.account, TODAY
    )
    return bundle, render_report(bundle, radar)


#: 一段真实形态但"当前解析器读不懂"的文本（模拟未来格式变更）
UNPARSEABLE_TEXT = "<xml><campaigns><item id='1'/></campaigns></xml>"


class TestHasPayloadContent(unittest.TestCase):
    """区分"真空白"与"有内容但读不懂"——这是整个机制的地基。"""

    def test_none_and_blank_are_empty(self) -> None:
        for value in (None, "", "   ", "\n\t"):
            with self.subTest(value=value):
                self.assertFalse(has_payload_content(value))

    def test_empty_containers_are_empty(self) -> None:
        for value in ([], {}, {"data": {}}, {"data": []}, {"data": {"campaignList": []}}):
            with self.subTest(value=value):
                self.assertFalse(has_payload_content(value))

    def test_envelope_only_response_is_empty(self) -> None:
        """``{"code":0,"msg":"ok"}`` 是"成功但没数据"，不是"收到了数据"。"""
        self.assertFalse(has_payload_content({"code": 0, "msg": "ok", "success": True}))
        self.assertFalse(has_payload_content({"code": 0, "data": {"couponList": []}, "total": 0}))

    def test_free_text_counts_as_content(self) -> None:
        """非 JSON 的自由文本 → 有内容（能否解析是另一回事）。"""
        self.assertTrue(has_payload_content(UNPARSEABLE_TEXT))
        self.assertTrue(has_payload_content("### 活动列表：\n\n#### 2026年10月9日 今日\n"))

    def test_json_string_is_unwrapped(self) -> None:
        self.assertFalse(has_payload_content('{"data": {"campaignList": []}}'))
        self.assertTrue(has_payload_content('{"data": {"campaignList": [{"a": 1}]}}'))

    def test_real_records_count_as_content(self) -> None:
        self.assertTrue(has_payload_content({"data": {"campaignList": [{"campaignId": "X"}]}}))


class TestClassifyState(unittest.TestCase):
    def test_failure_wins_over_everything(self) -> None:
        """调用失败时，其余信息没有意义。"""
        self.assertIs(classify_state(False, {"data": {"list": [{"a": 1}]}}, 5), PayloadState.FAILED)
        self.assertIs(classify_state(False, None, 0), PayloadState.FAILED)

    def test_records_mean_parsed(self) -> None:
        self.assertIs(classify_state(True, {"x": 1}, 3), PayloadState.PARSED)

    def test_content_without_records_is_unrecognized(self) -> None:
        self.assertIs(classify_state(True, UNPARSEABLE_TEXT, 0), PayloadState.UNRECOGNIZED)

    def test_blank_is_empty(self) -> None:
        self.assertIs(classify_state(True, {"code": 0, "data": {}}, 0), PayloadState.EMPTY)


class TestCampaignSourceStates(unittest.TestCase):
    """端到端：三种异常/空状态在报告里的呈现必须有明确区别。"""

    def test_unparseable_content_is_reported_as_parse_failure(self) -> None:
        bundle, text = render({"campaign-calendar": make_result("campaign-calendar", True, UNPARSEABLE_TEXT)})
        status = bundle.source("campaign-calendar")
        self.assertIs(status.state, PayloadState.UNRECOGNIZED)
        self.assertEqual(status.record_count, 0)
        self.assertGreater(status.payload_chars, 0)
        # 必须明说"收到数据但解析失败"
        self.assertIn("收到数据，但解析失败", text)
        # 禁止把它渲染成"本月没有活动"
        self.assertNotIn("本月没有活动", text)
        self.assertNotIn("本月无活动", text)
        # 元信息里的活动条数不得显示 0
        self.assertIn("解析失败（原文", text)
        # 第 8 节要有醒目告警
        self.assertIn("有数据源返回了内容，但解析器未能读懂", text)

    def test_truly_empty_is_reported_as_no_data(self) -> None:
        payload = {"code": 0, "msg": "ok", "data": {"campaignList": []}}
        bundle, text = render({"campaign-calendar": make_result("campaign-calendar", True, payload)})
        status = bundle.source("campaign-calendar")
        self.assertIs(status.state, PayloadState.EMPTY)
        self.assertIn("本月无活动", text)
        self.assertNotIn("解析失败", text)

    def test_call_failure_is_reported_as_fetch_failure(self) -> None:
        bundle, text = render(
            {"campaign-calendar": make_result("campaign-calendar", False, error="HTTP 429：触发限流")}
        )
        status = bundle.source("campaign-calendar")
        self.assertIs(status.state, PayloadState.FAILED)
        self.assertFalse(status.ok)
        self.assertIn("活动数据取数失败", text)
        self.assertIn("HTTP 429", text)
        self.assertNotIn("解析失败", text)
        self.assertNotIn("本月无活动", text)

    def test_three_states_render_differently(self) -> None:
        """三种状态的活动板块文字必须两两不同，不允许混用同一句措辞。"""
        _, unrecognized = render(
            {"campaign-calendar": make_result("campaign-calendar", True, UNPARSEABLE_TEXT)}
        )
        _, empty = render(
            {"campaign-calendar": make_result("campaign-calendar", True, {"data": {"campaignList": []}})}
        )
        _, failed = render(
            {"campaign-calendar": make_result("campaign-calendar", False, error="boom")}
        )

        def campaign_section(text: str) -> str:
            return text.split("## 6. 活动日历")[1].split("## 7.")[0].strip()

        for label, text in (("unrecognized", unrecognized), ("empty", empty), ("failed", failed)):
            with self.subTest(state=label):
                self.assertTrue(campaign_section(text), "活动板块不应为空")

        sections = [campaign_section(t) for t in (unrecognized, empty, failed)]
        self.assertEqual(len(set(sections)), 3, "三种状态必须给出不同的说明文字")

    def test_other_tools_get_states_too(self) -> None:
        """状态分类不是活动专属——任何工具读不懂都要报警。"""
        results = support.mock_results() | {
            "available-coupons": make_result("available-coupons", True, UNPARSEABLE_TEXT)
        }
        bundle = build_bundle(results, mode="real", today=TODAY)
        self.assertIs(bundle.source("available-coupons").state, PayloadState.UNRECOGNIZED)
        notes = "\n".join(bundle.integrity_notes())
        self.assertIn("available-coupons", notes)
        self.assertIn("收到数据，但解析失败", notes)


class TestSummarySurfacesUnparsed(unittest.TestCase):
    def test_summary_distinguishes_failed_and_unparsed(self) -> None:
        from report import summarize

        results = support.mock_results() | {
            "campaign-calendar": make_result("campaign-calendar", True, UNPARSEABLE_TEXT)
        }
        bundle = build_bundle(results, mode="real", today=TODAY)
        radar = build_radar(
            bundle.my_coupons, bundle.available_coupons, bundle.campaigns, bundle.account, TODAY
        )
        text = summarize(bundle, radar)
        self.assertIn("解析失败 1", text)
        self.assertIn("取数失败 0", text)


class TestPayloadText(unittest.TestCase):
    def test_payload_text_handles_all_shapes(self) -> None:
        self.assertEqual(payload_text(None), "")
        self.assertEqual(payload_text("abc"), "abc")
        self.assertIn("campaignList", payload_text({"data": {"campaignList": []}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
