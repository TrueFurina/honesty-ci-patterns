#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""honesty_scan.py — 把「诚实」做成能 exit 1 的 CI 门禁（可运行示例）

从 marl-ecdsa 源码研究提炼的四条规则的可运行骨架：
  1. 放弃语义理解，只拦已知回潮（FORBIDDEN_PHRASES）
  2. 提及≠使用：先剥引用/代码块再匹配（_QUOTE_RE）
  3. 推翻不删除，打「已作废」标记（EXEMPT_MARKERS）
  4. 数字先进登记簿后进文档（registry 预写日志）

用法:
    python honesty_scan.py <目录或文件>... [--registry number_registry.json]

退出码: 0 = 全绿；1 = 命中违规（门禁阻断）
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Windows GBK 控制台会把 ✓/✗ 等符号打崩，强制 UTF-8 输出（CI 在 Win 上必踩的坑）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 规则 1：已知回潮拒绝列表（按需扩充，确定性无歧义，不靠 LLM）──────────────
FORBIDDEN_PHRASES = [
    r"approximately\s+\d",      # approximately 42
    r"roughly\s+\d",            # roughly 42
    r"\bTODO\b",                # 未完成占位
    r"\bXX%",                   # 占位百分比
    r"\?\?\s*%",                # ?? %
    r"comparable to [A-Za-z]",  # 无来源对照（应登记后引用）
]

# ── 规则 2：提及≠使用。剥掉内联代码 / 代码块 / 引用标记后再匹配 ────────────
_QUOTE_RE = re.compile(
    r"```.*?```"      # fenced code block
    r"|`[^`]*`"       # inline code
    r"|^\s*>\s.*$",   # blockquote line
    re.DOTALL | re.MULTILINE,
)

# ── 规则 3：推翻留痕标记。命中则该行豁免违规判定 ───────────────────────────
EXEMPT_MARKERS = [
    r"\[SUPERSEDED[:\]]",
    r"\[VOIDED[:\]]",
    r"\[RETIRED[:\]]",
    r"<!--\s*retired",
    r"<!--\s*superseded",
]
_EXEMPT_RE = re.compile("|".join(EXEMPT_MARKERS))

# 文档扫描范围
DOC_GLOBS = ("*.md", "*.html", "*.rst")
SCAN_FILE_LIMIT = 2 * 1024 * 1024  # 单文件上限 2MB，避免误扫大二进制


def load_registered_numbers(registry_path):
    """规则 4：读登记簿，返回已登记数字字符串集合。无登记簿则返回 None（跳过规则 4）。"""
    if not registry_path or not Path(registry_path).is_file():
        return None
    data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    # 登记簿格式由项目自定；这里做宽容提取：递归收集所有字符串里看起来像数字的 token
    nums = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for m in re.findall(r"\d+(?:\.\d+)?%?", o):
                nums.add(m)

    walk(data)
    return nums


def scan_text(text, registered):
    """返回违规列表 [(规则, 行号, 片段)]。"""
    violations = []
    stripped = _QUOTE_RE.sub("", text)  # 规则 2：先剥引用，避免误伤"说明性引用"

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        # 规则 3：命中作废标记的行豁免
        if _EXEMPT_RE.search(raw_line):
            continue
        # 只在"未被剥引用"的对应区域判定；简化：对剥引用后的整文做逐行重算行号不现实，
        # 实践中按行判断该行是否处于被剥区域外。这里用保守做法：对每行单独剥引用后判定。
        line_clean = _QUOTE_RE.sub("", raw_line)
        for pat in FORBIDDEN_PHRASES:
            if re.search(pat, line_clean, re.IGNORECASE):
                violations.append(("FORBIDDEN", lineno, raw_line.strip()[:60]))

        # 规则 4：裸数字必须在登记簿（仅当提供了登记簿）
        if registered is not None:
            for m in re.findall(r"\d+(?:\.\d+)?%?", line_clean):
                # 形如数字且不在引用里的，要求已登记
                if m not in registered:
                    violations.append(("UNREGISTERED", lineno, f"{m} in {raw_line.strip()[:40]}"))

    return violations


def collect_files(paths):
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for g in DOC_GLOBS:
                files.extend(pp.rglob(g))
        elif pp.is_file():
            files.append(pp)
    # 去重 + 限大小
    seen, out = set(), []
    for f in files:
        rf = f.resolve()
        if rf in seen:
            continue
        seen.add(rf)
        try:
            if f.stat().st_size <= SCAN_FILE_LIMIT:
                out.append(f)
        except OSError:
            pass
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description="honesty CI gate (exit 1 on violation)")
    ap.add_argument("paths", nargs="+", help="要扫描的目录或文件")
    ap.add_argument("--registry", default=None, help="number_registry.json 路径（启用规则 4）")
    args = ap.parse_args()

    registered = load_registered_numbers(args.registry)
    files = collect_files(args.paths)

    total = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        vs = scan_text(text, registered)
        if vs:
            print(f"\n✗ {f}")
            for rule, lineno, frag in vs:
                print(f"    [{rule}] line {lineno}: {frag}")
            total += len(vs)

    print(f"\n扫描 {len(files)} 个文件，违规 {total} 处"
          f"（规则4：{'启用' if registered is not None else '未启用（无登记簿）'}）")
    if total:
        sys.exit(1)
    print("✓ 全绿")
    sys.exit(0)


if __name__ == "__main__":
    main()
