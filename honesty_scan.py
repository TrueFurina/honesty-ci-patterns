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
DOC_GLOBS = ("*.md", "*.html", "*.rst", "*.ipynb")
SCAN_FILE_LIMIT = 2 * 1024 * 1024  # 单文件上限 2MB，避免误扫大二进制


def extract_ipynb_text(raw_text):
    """从 Jupyter notebook JSON 里抽取可读文本（markdown 单元 + code 单元源码）。
    返回 (文本, 行号偏移表)：notebook 无稳定行号，这里把每个单元源码按行拼接，
    并记录每个"虚拟行"对应哪个单元，方便报告定位。"""
    try:
        nb = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError):
        return raw_text, {}
    lines = []
    cell_map = {}  # 虚拟行号 -> 单元序号
    for ci, cell in enumerate(nb.get("cells", [])):
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        for ln in src.splitlines():
            lines.append(ln)
            cell_map[len(lines)] = ci
        lines.append("")  # 单元间空行分隔
    return "\n".join(lines), cell_map


def load_config(config_path):
    """读外部规则配置（JSON）。支持覆盖/追加 FORBIDDEN_PHRASES、EXEMPT_MARKERS、DOC_GLOBS。
    返回 dict，键缺省时用内置默认。"""
    cfg = {}
    if config_path and Path(config_path).is_file():
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        cfg["forbidden"] = data.get("forbidden_phrases")
        cfg["exempt"] = data.get("exempt_markers")
        cfg["globs"] = data.get("doc_globs")
    return cfg


def generate_ci_template(dest):
    """生成 GitHub Actions 门禁模板到 dest 目录。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    wf = dest / ".github" / "workflows" / "honesty-gate.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(
        "name: honesty-gate\n\n"
        "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n\n"
        "jobs:\n  gate:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n        with:\n          python-version: \"3.11\"\n"
        "      - name: Run honesty gate\n        run: python honesty_scan.py .\n",
        encoding="utf-8")
    print(f"✓ 已生成 CI 模板: {wf}")
    return wf


def generate_precommit(dest):
    """生成 pre-commit 钩子配置到 dest 目录。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    pc = dest / ".pre-commit-config.yaml"
    pc.write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: honesty-gate\n"
        "        name: honesty gate\n"
        "        entry: python honesty_scan.py\n"
        "        language: system\n"
        "        pass_filenames: false\n",
        encoding="utf-8")
    print(f"✓ 已生成 pre-commit 配置: {pc}")
    return pc


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
    # 归一化：登记簿里的 1.95 与文档里的 1.95% 视为同一数字（去尾 % 后比对）
    return {n.rstrip("%") for n in nums}


def scan_text(text, registered):
    """返回违规列表 [(规则, 行号, 片段)]。"""
    violations = []

    # 规则 2 关键：fenced code block 跨多行，逐行剥引用无法覆盖块内内容。
    # 先预计算哪些行落在 ``` fence 内（或行内被剥空），这些行对规则 1/4 豁免。
    in_fence = set()
    fence_open = False
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence.add(lineno)
            fence_open = not fence_open
            continue
        if fence_open:
            in_fence.add(lineno)

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        # 规则 3：命中作废标记的行豁免
        if _EXEMPT_RE.search(raw_line):
            continue
        # 规则 2：落在 fenced code block 内的行豁免（提及≠使用）
        line_clean = _QUOTE_RE.sub("", raw_line)
        if lineno in in_fence or line_clean.strip() == "":
            continue

        for pat in FORBIDDEN_PHRASES:
            if re.search(pat, line_clean, re.IGNORECASE):
                violations.append(("FORBIDDEN", lineno, raw_line.strip()[:60]))

        # 规则 4：裸数字必须在登记簿（仅当提供了登记簿）
        if registered is not None:
            for m in re.findall(r"\d+(?:\.\d+)?%?", line_clean):
                # 去尾 % 后比对：登记簿 1.95 与文档 1.95% 视为同一数字
                if m.rstrip("%") not in registered:
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
    ap = argparse.ArgumentParser(
        description="honesty CI gate (exit 1 on violation) — 提及≠使用 / 推翻留痕 / 数字登记簿")
    ap.add_argument("paths", nargs="*", default=["."], help="要扫描的目录或文件（默认当前目录）")
    ap.add_argument("--registry", default=None, help="number_registry.json 路径（启用规则 4）")
    ap.add_argument("--config", default=None, help="规则配置 JSON（覆盖/追加 forbidden/exempt/globs）")
    ap.add_argument("--json", dest="json_out", action="store_true",
                    help="以 JSON 输出结果（便于机器消费 / 上报面板）")
    ap.add_argument("--init", choices=["ci", "precommit"], default=None,
                    help="在目标目录生成 CI / pre-commit 模板后退出")
    args = ap.parse_args()

    # --init：脚手架模式，生成模板后退出
    if args.init == "ci":
        generate_ci_template(args.paths[0] if args.paths else ".")
        sys.exit(0)
    if args.init == "precommit":
        generate_precommit(args.paths[0] if args.paths else ".")
        sys.exit(0)

    cfg = load_config(args.config)
    forbidden = cfg.get("forbidden") or FORBIDDEN_PHRASES
    exempt = cfg.get("exempt") or EXEMPT_MARKERS
    if cfg.get("globs"):
        globals()["DOC_GLOBS"] = tuple(cfg["globs"])
    _forbidden_re = [re.compile(p, re.IGNORECASE) for p in forbidden]
    _exempt_re = re.compile("|".join(exempt))

    registered = load_registered_numbers(args.registry)
    files = collect_files(args.paths)

    report = {"scanned": 0, "violations": 0, "files": [], "registry": registered is not None}
    total = 0
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # ipynb 需先抽文本
        cell_map = {}
        if f.suffix == ".ipynb":
            text, cell_map = extract_ipynb_text(raw)
        else:
            text = raw

        vs = []
        in_fence = set()
        fence_open = False
        lines = text.splitlines()
        for lineno, raw_line in enumerate(lines, 1):
            if raw_line.strip().startswith("```"):
                in_fence.add(lineno); fence_open = not fence_open; continue
            if fence_open:
                in_fence.add(lineno)
        for lineno, raw_line in enumerate(lines, 1):
            if _exempt_re.search(raw_line):
                continue
            line_clean = _QUOTE_RE.sub("", raw_line)
            if lineno in in_fence or line_clean.strip() == "":
                continue
            for pat in _forbidden_re:
                if pat.search(line_clean):
                    vs.append(("FORBIDDEN", lineno, raw_line.strip()[:60]))
            if registered is not None:
                for m in re.findall(r"\d+(?:\.\d+)?%?", line_clean):
                    if m.rstrip("%") not in registered:
                        vs.append(("UNREGISTERED", lineno, f"{m} in {raw_line.strip()[:40]}"))

        report["scanned"] += 1
        if vs:
            total += len(vs)
            report["violations"] += len(vs)
            report["files"].append({
                "path": str(f),
                "violations": [
                    {"rule": r, "line": ln,
                     "cell": cell_map.get(ln) if cell_map else None,
                     "snippet": frag}
                    for r, ln, frag in vs
                ],
            })

    if args.json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for entry in report["files"]:
            print(f"\n✗ {entry['path']}")
            for v in entry["violations"]:
                cellinfo = f" (cell {v['cell']})" if v["cell"] is not None else ""
                print(f"    [{v['rule']}] line {v['line']}{cellinfo}: {v['snippet']}")
        print(f"\n扫描 {report['scanned']} 个文件，违规 {total} 处"
              f"（规则4：{'启用' if registered is not None else '未启用（无登记簿）'}）")
        if not total:
            print("✓ 全绿")

    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
