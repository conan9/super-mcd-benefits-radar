"""参赛就绪度检查 —— 锁定"必需文件齐全 + 官方声明未被改动 + 配置无真实凭据"。

对应官方仓库 M-China/mcd-developer-innovation-challenge 的《开发 Skill》一节：
必须提交 README.md、CONTEST_DECLARATION.md（**文件名与内容均不可改动**）、
MCP_INTEGRATION.md、源代码；workbuddy.md 为 WorkBuddy 专项奖励所需（文件名不可改动）。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import support  # noqa: F401
from support import ROOT, SCRIPTS

#: 官方 CONTEST_DECLARATION.md 的 MD5
#: 来源：https://raw.githubusercontent.com/M-China/mcd-developer-innovation-challenge/main/CONTEST_DECLARATION.md
#: 采集于 2026-10-09，1522 字节。原文变更时同步更新此常量。
OFFICIAL_DECLARATION_MD5 = "91a7b32ec28098b609ca3f215cdf7147"
OFFICIAL_DECLARATION_SIZE = 1522

#: 官方要求的必需文件（文件名不可改动）
REQUIRED_FILES = (
    "README.md",
    "CONTEST_DECLARATION.md",
    "MCP_INTEGRATION.md",
)


class TestRequiredFiles(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for name in REQUIRED_FILES:
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f"缺少必需文件 {name}")

    def test_workbuddy_md_exists(self) -> None:
        """参加 WorkBuddy 专项奖励时必须提交，且文件名不可改动。"""
        self.assertTrue((ROOT / "workbuddy.md").is_file())

    def test_skill_entry_exists(self) -> None:
        self.assertTrue((ROOT / "SKILL.md").is_file())

    def test_optional_example_config_exists(self) -> None:
        """非官方必需，但本项目的 README 承诺提供，故一并锁定。"""
        self.assertTrue((ROOT / "mcp-config.example.json").is_file())

    def test_source_code_present(self) -> None:
        scripts = sorted((SCRIPTS).glob("*.py"))
        self.assertGreaterEqual(len(scripts), 5, "源码文件过少")
        for name in ("mcd_client.py", "normalize.py", "radar.py", "report.py", "run_radar.py"):
            with self.subTest(script=name):
                self.assertTrue((SCRIPTS / name).is_file())

    def test_tests_present(self) -> None:
        tests = sorted((ROOT / "tests").glob("test_*.py"))
        self.assertGreaterEqual(len(tests), 5, "测试文件过少")


class TestContestDeclarationUnchanged(unittest.TestCase):
    """官方要求"文件名及内容均不可改动"——这里用哈希锁死。"""

    def test_md5_matches_official(self) -> None:
        path = ROOT / "CONTEST_DECLARATION.md"
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        self.assertEqual(
            digest,
            OFFICIAL_DECLARATION_MD5,
            "CONTEST_DECLARATION.md 已被修改！官方要求内容不可改动。",
        )

    def test_size_matches_official(self) -> None:
        size = (ROOT / "CONTEST_DECLARATION.md").stat().st_size
        self.assertEqual(size, OFFICIAL_DECLARATION_SIZE)

    def test_no_crlf_added(self) -> None:
        """在 Windows 上按文本模式写入会引入 CRLF，同样会改变 MD5。"""
        raw = (ROOT / "CONTEST_DECLARATION.md").read_bytes()
        self.assertNotIn(b"\r\n", raw, "官方原文为 LF 换行，不得被转成 CRLF")

    def test_required_sections_present(self) -> None:
        text = (ROOT / "CONTEST_DECLARATION.md").read_text(encoding="utf-8")
        for heading in ("原创性声明", "合规声明", "信息安全声明", "规则遵守声明"):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)


class TestNoCredentialsCommitted(unittest.TestCase):
    """信息安全声明要求：不得包含真实 Token、密钥、账号凭证。"""

    #: 形如 XXX_ 后接长串的高危模式
    #: 手机号规则带 ``\b`` 边界，避免把 13 位毫秒时间戳误判为手机号。
    SECRET_PATTERNS = (
        re.compile(r"(?i)bearer\s+(?!YOUR_MCP_TOKEN\b)[A-Za-z0-9._\-]{16,}"),
        re.compile(r"sk_live_[A-Za-z0-9]{16,}"),
        re.compile(r"\b[0-9a-fA-F]{32,}\b"),
        re.compile(r"\b1[3-9]\d{9}\b"),  # 中国大陆手机号
    )

    #: **资源文件名**形态的十六进制串：32 位以上十六进制后紧跟文件扩展名。
    #: 典型来源是官方 MCP 返回里的 CDN 图片地址，如
    #: ``https://<cdn-host>/img/short-content/<32位十六进制>.jpg``。
    #: 这类名字是公开资源名，任何人访问官网都能看到，无凭据价值；真实响应样例会源
    #: 源不断地带进这种串，逐个加白名单是治标。
    #:
    #: 判定收紧到**必须带文件扩展名**，因此下列情况**仍会被拦截**：
    #: * 独立出现的 32 位十六进制（真密钥的典型形态）；
    #: * 形如 ``https://x.io/<32位hex>`` 这种"密钥藏在 URL 路径里"的写法；
    #: * 任何不带扩展名的长十六进制串。
    ASSET_FILENAME_RE = re.compile(r"[0-9a-fA-F]{32,}\.\w{2,5}\b")

    #: 人工核实为伪造常量的白名单（见该文件头部的准入说明）
    ALLOWLIST_FILE = ROOT / "tests" / "credential-scan-allowlist.txt"

    @classmethod
    def allowed_values(cls) -> frozenset[str]:
        if not cls.ALLOWLIST_FILE.is_file():
            return frozenset({OFFICIAL_DECLARATION_MD5})
        values = set()
        for raw in cls.ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                values.add(line)
        values.add(OFFICIAL_DECLARATION_MD5)
        return frozenset(values)

    def iter_files(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix.lower() in {".md", ".json", ".py", ".txt", ".example"} or path.name.startswith("."):
                yield path

    @classmethod
    def scan_text(cls, text: str, allowed: frozenset[str]) -> list[str]:
        """扫描一段文本，返回疑似凭据列表（已排除资源文件名与白名单）。"""
        asset_spans = [m.span() for m in cls.ASSET_FILENAME_RE.finditer(text)]
        hits: list[str] = []
        for pattern in cls.SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group()
                if value in allowed:
                    continue
                if any(start <= match.start() and match.end() <= end for start, end in asset_spans):
                    continue  # 资源文件名（如 CDN 图片名）
                hits.append(value[:40])
        return hits

    def test_no_credentials_in_repo(self) -> None:
        allowed = self.allowed_values()
        hits = []
        for path in self.iter_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            hits.extend(f"{path.relative_to(ROOT)}: {hit}" for hit in self.scan_text(text, allowed))
        self.assertEqual(hits, [], "疑似真实凭据：\n" + "\n".join(hits))

    @staticmethod
    def fake_hex() -> str:
        """构造一个 32 位十六进制串。

        注意必须**拼接**而不能写字面量——否则扫描器会把这个测试文件自己抓出来，
        这正是它应该做的事（曾经真的发生过）。
        """
        return "0123456789abcdef" * 2

    def test_scanner_still_catches_standalone_hex(self) -> None:
        """资源名豁免不得变成盲区：独立出现的 32 位十六进制必须仍被拦截。"""
        self.assertEqual(len(self.scan_text(f"token = {self.fake_hex()}", frozenset())), 1)

    def test_scanner_still_catches_hex_in_backticks(self) -> None:
        """反引号里的裸十六进制同样是密钥的常见写法，必须拦截。"""
        self.assertEqual(len(self.scan_text(f"`{self.fake_hex()}`", frozenset())), 1)

    def test_scanner_still_catches_hex_inside_url_path(self) -> None:
        """密钥藏在 URL 路径里（没有资源扩展名）同样必须被拦截。"""
        self.assertEqual(
            len(self.scan_text(f"https://api.example.com/v1/{self.fake_hex()}", frozenset())), 1
        )

    def test_scanner_ignores_cdn_asset_filename(self) -> None:
        """CDN 图片名不应被误报，否则真实响应样例无法入库。"""
        url = f"https://cms-cdn.example.com/img/short-content/{self.fake_hex()}.jpg"
        self.assertEqual(self.scan_text(f'<img src="{url}">', frozenset()), [])

    def test_scanner_ignores_asset_filename_written_plainly(self) -> None:
        """不带 URL 前缀的资源名（Markdown 里以反引号引用）也应豁免。"""
        self.assertEqual(self.scan_text(f"`{self.fake_hex()}.jpg`", frozenset()), [])

    def test_allowlist_itself_has_no_real_secrets(self) -> None:
        """白名单文件不得成为提交真实凭据的后门：条目数应很少且都短于常见 Token 长度。"""
        values = {v for v in self.allowed_values() if v != OFFICIAL_DECLARATION_MD5}
        self.assertLessEqual(len(values), 6, "白名单条目过多，需复核是否混入真实凭据")

    def test_example_config_uses_placeholder(self) -> None:
        config = json.loads((ROOT / "mcp-config.example.json").read_text(encoding="utf-8"))
        headers = config["mcpServers"]["mcd-mcp"]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer YOUR_MCP_TOKEN")

    def test_example_config_points_at_official_endpoint(self) -> None:
        config = json.loads((ROOT / "mcp-config.example.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["mcd-mcp"]
        self.assertEqual(server["url"], "https://mcp.mcd.cn")
        self.assertEqual(server["type"], "streamablehttp")

    def test_gitignore_covers_secrets(self) -> None:
        gitignore = ROOT / ".gitignore"
        self.assertTrue(gitignore.is_file(), "缺少 .gitignore")
        content = gitignore.read_text(encoding="utf-8")
        for pattern in (".env", "raw/", "report.md"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, content)


class TestDocsMatchCode(unittest.TestCase):
    def test_data_schema_is_up_to_date(self) -> None:
        """数据字典由代码生成，必须与代码一致，否则文档会误导读者。"""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "dump_schema.py"), "--check"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_skill_md_lists_real_scripts(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name in ("run_radar.py", "mcd_client.py", "normalize.py", "radar.py", "report.py"):
            with self.subTest(script=name):
                self.assertIn(name, text)
                self.assertTrue((SCRIPTS / name).is_file())

    def test_skill_md_tool_names_match_code(self) -> None:
        from mcd_client import OFFICIAL_TOOLS

        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for tool in OFFICIAL_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(f"`{tool}`", text)

    def test_readme_mentions_readonly_guarantee(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("不下单", text)
        self.assertIn("不自动领券", text)

    def test_mcp_integration_names_all_used_tools(self) -> None:
        from mcd_client import OFFICIAL_TOOLS

        text = (ROOT / "MCP_INTEGRATION.md").read_text(encoding="utf-8")
        for tool in OFFICIAL_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(tool, text)

    def test_workbuddy_md_declares_provenance(self) -> None:
        """workbuddy.md 必须说明来源与脱敏方式，不得伪造。"""
        text = (ROOT / "workbuddy.md").read_text(encoding="utf-8")
        self.assertIn("脱敏", text)
        self.assertIn("WorkBuddy", text)

    def test_readme_has_target_users_and_usage(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for section in ("目标用户", "安装", "使用"):
            with self.subTest(section=section):
                self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
