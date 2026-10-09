"""一条命令跑完全部测试。

用法::

    python run_tests.py          # 全部测试
    python run_tests.py -v       # 详细输出
    python run_tests.py radar    # 只跑名字含 "radar" 的测试

等价于 ``python -m unittest discover -s tests -t tests``，
但额外做了 --help 友好参数与结果汇总。
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"


def flatten(suite: unittest.TestSuite):
    """递归展开嵌套的 TestSuite，产出叶节点 TestCase。"""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main() -> int:
    parser = argparse.ArgumentParser(description="运行超麦权益雷达测试套件")
    parser.add_argument("pattern", nargs="?", default=None, help="只运行匹配的测试（子串匹配）")
    parser.add_argument("-v", "--verbose", action="store_true", help="逐条输出")
    parser.add_argument("-f", "--failfast", action="store_true", help="首个失败即停止")
    args = parser.parse_args()

    sys.path.insert(0, str(TESTS))
    loader = unittest.TestLoader()
    discovered = loader.discover(start_dir=str(TESTS), top_level_dir=str(TESTS))

    if args.pattern:
        suite = unittest.TestSuite()
        for case in flatten(discovered):
            if args.pattern.lower() in case.id().lower():
                suite.addTest(case)
        if suite.countTestCases() == 0:
            print(f"没有匹配 {args.pattern!r} 的测试")
            return 1
    else:
        suite = discovered

    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, failfast=args.failfast)
    result = runner.run(suite)

    print("-" * 60)
    print(f"共 {result.testsRun} 项 | 失败 {len(result.failures)} | 错误 {len(result.errors)} "
          f"| 跳过 {len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
