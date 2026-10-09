"""SKILL.md frontmatter 校验（纯标准库，不依赖 PyYAML）。

WorkBuddy Skill 的 frontmatter 是受限 YAML 子集：
    ---
    name: xxx
    description: |
      多行文本
    ---
本模块用标准库实现该子集的解析与校验，以便测试可离线运行。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "super-mcd-benefits-radar"

#: 关于目录名：本套测试**刻意不**断言"检出目录名 == SKILL_NAME"。
#: GitHub 仓库会被克隆、下载、解压到任意目录名（``super-mcd-benefits-radar``、
#: ``super-mcd-benefits-radar-main``、``github-release``、``foo/bar/skill`` …），
#: 让测试随检出位置而失败是没有意义的噪声。
#: 「目录名必须等于 Skill ID」是**打包/安装环节**的约束，由构建脚本在生成安装包 ZIP 时
#: 强制校验（校验 SKILL.md 的 name == Skill ID、ZIP 根结构、嵌套包顶层目录名）。
#: 本文件只负责校验 SKILL.md 自身的清单内容。


def parse_frontmatter(text: str) -> dict:
    """解析受限 YAML frontmatter，返回 {key: value}。

    Raises:
        ValueError: 缺少 frontmatter 分隔符或存在无法解析的行。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("文件未以 '---' 起始，缺少 frontmatter")

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("frontmatter 未闭合，缺少结束的 '---'") from None

    data: dict[str, str] = {}
    current_key: str | None = None
    block: list[str] = []

    def flush() -> None:
        nonlocal current_key, block
        if current_key is not None:
            data[current_key] = "\n".join(block).strip()
        current_key, block = None, []

    for raw in lines[1:end]:
        if not raw.strip():
            # 空行属于块内容的一部分（保留段落感）
            if current_key is not None:
                block.append("")
            continue

        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            flush()
            key, value = m.group(1), m.group(2).strip()
            if value in ("|", ">", "|-", ">-", ""):
                current_key = key
                block = []
            else:
                data[key] = value.strip("'\"")
        else:
            if current_key is None:
                raise ValueError(f"无法解析的 frontmatter 行: {raw!r}")
            block.append(raw.strip())

    flush()
    return data


class TestSkillManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_md = ROOT / "SKILL.md"
        cls.text = cls.skill_md.read_text(encoding="utf-8")
        cls.meta = parse_frontmatter(cls.text)

    def test_skill_md_exists(self) -> None:
        self.assertTrue(self.skill_md.is_file(), "SKILL.md 不存在")

    def test_frontmatter_parses(self) -> None:
        self.assertIn("name", self.meta)
        self.assertIn("description", self.meta)

    def test_name_is_canonical_skill_id(self) -> None:
        """Skill ID 必须**严格等于**正式标识，且不受检出目录名影响。"""
        self.assertEqual(
            self.meta["name"],
            SKILL_NAME,
            f"SKILL.md 的 name 必须是 {SKILL_NAME!r}，实际为 {self.meta['name']!r}",
        )

    def test_name_matches_directory_when_run_in_place(self) -> None:
        """仅在检出目录名恰为仓库名时，才额外确认一次两者一致。

        这是**软校验**：目录名不匹配时直接跳过，不产生失败——
        见文件顶部关于「为何不把检出目录名当作断言条件」的说明。
        真正的硬校验在打包脚本里。
        """
        if ROOT.name != SKILL_NAME:
            self.skipTest(
                f"检出目录名为 {ROOT.name!r}（非仓库名），跳过目录名比对；"
                "打包环节会强制校验目录结构"
            )
        self.assertEqual(ROOT.name, self.meta["name"])

    def test_name_is_kebab_case(self) -> None:
        self.assertRegex(self.meta["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_description_is_substantive(self) -> None:
        desc = self.meta["description"]
        self.assertGreaterEqual(len(desc), 40, "description 过短，不利于技能检索")
        self.assertIn("只读", desc, "description 应声明只读定位")

    def test_body_declares_readonly_boundary(self) -> None:
        self.assertIn("WriteOperationBlocked", self.text)
        self.assertIn("auto-bind-coupons", self.text)

    def test_body_declares_no_fabrication_rule(self) -> None:
        self.assertIn("[字段缺失]", self.text)

    def test_token_only_from_env(self) -> None:
        self.assertIn("MCD_MCP_TOKEN", self.text)
        # 不得出现真实卡券类长十六进制密钥
        self.assertNotRegex(self.text, r"(?i)bearer\s+[0-9a-f]{32,}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
