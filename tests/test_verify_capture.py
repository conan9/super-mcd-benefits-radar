"""采集目录校验器测试 —— 锁定"转述载荷不得流入解析链路"。

``scripts/verify_capture.py`` 是解析链路的前置硬门槛：它要挡住两类危险输入——

1. **缺件**：四个工具的文件不全，报告会缺板块，而读者无从察觉；
2. **转述**：落盘的是模型摘要而不是逐字原始载荷。此时解析器读不懂，
   报告会出现空白，若无人拦截就会被误读成"确实没有权益"（静默假阴性）。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (注册 sys.path)
import verify_capture
from support import FIXTURES

#: 完整采集目录所需的四个文件名（与 ``fixtures/`` 中的序号样例同名）
CAPTURE_FILES = (
    "query_my_coupons.md",
    "query_my_account.txt",
    "available_coupons.md",
    "campaign_calendar.md",
)

#: 典型"转述腔"载荷：有内容、有数字，但完全不是官方结构
TRANSCRIBED_SAMPLE = (
    "我帮你查了一下你的优惠券，共查询到 3 张可用券：\n"
    "1. 麦辣鸡腿堡买一送一，今天到期；\n"
    "2. 满 30 减 8，3 天后到期；\n"
    "3. 甜品任选 9.9 元。\n"
    "总结如下：建议先处理第 1 张。\n"
)


def run_cli(argv: list[str]) -> tuple[int, str]:
    """跑一次 ``verify_capture.main``，返回 ``(退出码, 合并后的输出)``。

    正常结论走 stdout，错误提示走 stderr（"目录不存在"就在 stderr），
    这里合并捕获，断言不必关心具体流向。
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = verify_capture.main(argv)
    return code, buffer.getvalue()


def build_capture(
    root: Path,
    omit: tuple[str, ...] = (),
    overrides: dict[str, str] | None = None,
    rename: dict[str, str] | None = None,
) -> Path:
    """在 ``root`` 下搭一个采集目录。

    默认把 ``fixtures/`` 里的四个样例原样复制过去（它们结构上就是官方响应格式）。
    """
    directory = root / "capture"
    directory.mkdir()
    overrides = overrides or {}
    rename = rename or {}
    for name in CAPTURE_FILES:
        if name in omit:
            continue
        text = overrides.get(name, (FIXTURES / name).read_text(encoding="utf-8"))
        (directory / rename.get(name, name)).write_text(text, encoding="utf-8")
    return directory


class TestVerifyCapturePasses(unittest.TestCase):
    def test_complete_capture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp))
            code, out = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 0, out)
        for tool in ("query-my-coupons", "query-my-account", "available-coupons", "campaign-calendar"):
            with self.subTest(tool=tool):
                self.assertIn(tool, out)
        self.assertIn("可以进入解析与排序流程", out)

    def test_all_four_sources_are_reported_as_parsed(self) -> None:
        """四个样例都应被判为 ``PARSED``，不得出现 ``UNRECOGNIZED``。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp))
            code, out = run_cli(["--dir", str(directory), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["checks"]), 4)
        self.assertEqual([c["state"] for c in payload["checks"]], ["parsed"] * 4)

    def test_hyphen_and_underscore_filenames_accepted(self) -> None:
        """文件名写法的容错：连字符写法（``query-my-coupons.md``）也要被找到，
        不能因为大小写/连字符差异就报"未找到"。"""
        rename = {
            "query_my_coupons.md": "query-my-coupons.md",
            "campaign_calendar.md": "campaign-calendar.md",
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp), rename=rename)
            code, out = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 0, out)


class TestVerifyCaptureBlocksBadInput(unittest.TestCase):
    def test_missing_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp), omit=("campaign_calendar.md",))
            code, out = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 1)
        self.assertIn("文件缺失", out)

    def test_empty_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp), overrides={"available_coupons.md": ""})
            code, out = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 1)
        self.assertIn("文件为空", out)

    def test_transcribed_payload_fails(self) -> None:
        """核心用例：模型转述的摘要必须被拦下，并明确说清"空白不等于没有权益"。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp), overrides={"query_my_coupons.md": TRANSCRIBED_SAMPLE})
            code, out = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 1, out)
        self.assertIn("解析器读不懂", out)
        self.assertIn("我帮你查", out, "应提示疑似转述用语")
        self.assertIn("请勿", out)

    def test_nonexistent_directory_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_cli(["--dir", str(Path(tmp) / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("不存在", out)

    def test_json_report_marks_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp), omit=("query_my_coupons.md",))
            code, out = run_cli(["--dir", str(directory), "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        failed = [c for c in payload["checks"] if c["problems"]]
        self.assertEqual([c["tool"] for c in failed], ["query-my-coupons"])


class TestVerifyCaptureIsOffline(unittest.TestCase):
    def test_no_network_call(self) -> None:
        """校验器只做本地解析，绝不联网。"""
        import urllib.request
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            directory = build_capture(Path(tmp))
            with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("不应联网")):
                code, _ = run_cli(["--dir", str(directory)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
