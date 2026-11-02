#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_honesty_scan.py — honesty_scan.py 的测试套件

不依赖 pytest（避免 CI 额外依赖），用标准库 unittest 即可运行：
    python test_honesty_scan.py
    python -m unittest test_honesty_scan

覆盖四条规则 + 关键边界情况：
  ① 只拦已知回潮（拒绝列表命中）
  ② 提及≠使用（内联代码 / 代码块 / 引用块里的坏模式应豁免）
  ③ 推翻不删除（[SUPERSEDED] 等作废标记行豁免）
  ④ 数字先进登记簿（--registry 启用后，未登记裸数字报错）
  边界：空文件、退出码 0/1、Windows GBK 不崩
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = str(HERE / "honesty_scan.py")


def run_scan(args):
    """以 UTF-8 环境运行扫描器，返回 (returncode, stdout+stderr)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, SCAN] + args,
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def write(dirpath, name, content):
    p = Path(dirpath) / name
    p.write_text(content, encoding="utf-8")
    return str(p)


class Rule1Forbidden(unittest.TestCase):
    """规则①：已知回潮拒绝列表命中 → exit 1。"""

    def test_hits_approximately_and_todo(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "准确率 approximately 42%，TODO 补充。\n")
            rc, out = run_scan([f])
            self.assertEqual(rc, 1, "应命中 approximately / TODO 并 exit 1")
            self.assertIn("FORBIDDEN", out)

    def test_clean_document_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "# 干净\n合作率提升 1.95%，已登记。\n")
            rc, out = run_scan([f])
            self.assertEqual(rc, 0, "干净文档应全绿")
            self.assertIn("全绿", out)


class Rule2MentionNotUse(unittest.TestCase):
    """规则②：提及≠使用——引用里的坏模式不应触发。"""

    def test_inline_code_todo_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            # 反引号里的 TODO 是"说明性提及"，应豁免
            f = write(d, "a.md", "不要在正文写 `TODO`，会触发门禁。\n")
            rc, _ = run_scan([f])
            self.assertEqual(rc, 0, "内联代码里的 TODO 应豁免（提及≠使用）")

    def test_fenced_code_block_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "示例：\n```text\napproximately 42%\n```\n以上为代码块示例。\n")
            rc, _ = run_scan([f])
            # 代码块整块被 _QUOTE_RE 剥除；但"示例：" 行本身无坏词 → 应全绿
            self.assertEqual(rc, 0, "fenced code block 内容应豁免")

    def test_bare_todo_still_caught(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "这里 TODO 待办。\n")  # 裸 TODO，无引用包裹
            rc, _ = run_scan([f])
            self.assertEqual(rc, 1, "裸 TODO 仍应被拦")


class Rule3ExemptMarkers(unittest.TestCase):
    """规则③：推翻不删除——作废标记行豁免。"""

    def test_superseded_line_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "[SUPERSEDED:2026-10-15] 旧口径 approximately 99%。\n")
            rc, _ = run_scan([f])
            self.assertEqual(rc, 0, "命中 [SUPERSEDED] 的行应豁免")

    def test_voided_line_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "[VOIDED:regression#441] 误报 approximately 50%。\n")
            rc, _ = run_scan([f])
            self.assertEqual(rc, 0, "命中 [VOIDED] 的行应豁免")


class Rule4Registry(unittest.TestCase):
    """规则④：--registry 启用后，未登记裸数字报错。"""

    def _registry(self, d, nums):
        return write(d, "reg.json",
                     '{"entries": [' + ",".join(f'{{"v":"{n}"}}' for n in nums) + ']}')

    def test_unregistered_number_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            reg = self._registry(d, ["1.95"])  # 只登记 1.95
            f = write(d, "a.md", "合作率提升 2.31%。\n")  # 2.31 未登记
            rc, out = run_scan([f, "--registry", reg])
            self.assertEqual(rc, 1, "未登记数字应报错")
            self.assertIn("UNREGISTERED", out)

    def test_registered_number_passes(self):
        with tempfile.TemporaryDirectory() as d:
            reg = self._registry(d, ["1.95"])
            f = write(d, "a.md", "合作率提升 1.95%。\n")
            rc, _ = run_scan([f, "--registry", reg])
            self.assertEqual(rc, 0, "已登记数字应通过")


class Boundary(unittest.TestCase):
    """边界情况：空文件 / 目录扫描 / 输出编码。"""

    def test_empty_file_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "empty.md", "")
            rc, _ = run_scan([f])
            self.assertEqual(rc, 0, "空文件应全绿")

    def test_directory_scan(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "bad.md", "approximately 1%\n")
            write(d, "good.md", "已登记 1.95%。\n")
            rc, out = run_scan([d])
            self.assertEqual(rc, 1, "目录内含违规应 exit 1")
            self.assertIn("bad.md", out)

    def test_output_is_decodable_utf8(self):
        """Windows GBK 控制台不应打崩（脚本已 reconfigure 为 UTF-8）。"""
        with tempfile.TemporaryDirectory() as d:
            f = write(d, "a.md", "approximately 42%\n")
            rc, out = run_scan([f])
            self.assertIn("✗", out, "违规符号应正常输出且可解码")


if __name__ == "__main__":
    unittest.main(verbosity=2)
