"""mypy 类型门禁（棘轮）。

设计目标（对应 OPTIMIZATION_PLAN M3.8）：
- 不再用 ``|| true`` 掩盖类型错误；
- 先「挂起」代码库现存的历史错误（写入 ``.mypy-baseline.json``），
  使 CI 立刻变成硬门禁；
- 之后按包逐步收紧：修好一批错误后，用 ``--update-baseline`` 收紧基线。

基线键为 ``文件|错误码|消息``（刻意不含行号），因此纯行号漂移（重构/插行）
不会造成基线失配，只有真正新增的类型错误才会让门禁失败。

用法::

    python scripts/type_gate.py                  # 门禁校验（CI）
    python scripts/type_gate.py --update-baseline # 收紧基线（仅在有改善时）
    python scripts/type_gate.py --report          # 仅打印统计
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_FILE = os.path.join(PROJECT_ROOT, ".mypy-baseline.json")

# 与 AGENTS.md 一致的类型检查目标（不传 ``.``：仓库根存在 __init__.py，
# 直接扫描根目录会触发 "__main__ 与 __init__ 同名" 的模块映射冲突）
TARGETS = ["core", "algorithms", "ui", "utils", "config"]

_ERROR_RE = re.compile(
    r"^(?P<file>[^:]+\.py):(?P<line>\d+): error: (?P<msg>.+?)\s+\[(?P<code>[a-zA-Z0-9_-]+)\](?:\s+.*)?$"
)


def _normalize(path: str) -> str:
    """统一为相对项目根的 posix 路径，保证跨平台一致。"""
    return os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")


def collect_errors() -> tuple[set[str], int]:
    """运行 mypy 并返回 (归一化错误键集合, 原始错误条数)。"""
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", *TARGETS, "--no-error-summary", "--show-error-codes"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    keys: set[str] = set()
    raw = 0
    for line in (proc.stdout or "").splitlines():
        m = _ERROR_RE.match(line.strip())
        if not m:
            continue
        raw += 1
        keys.add(f"{_normalize(m.group('file'))}|{m.group('code')}|{m.group('msg')}")
    return keys, raw


def load_baseline() -> set[str]:
    if not os.path.isfile(BASELINE_FILE):
        return set()
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("errors", []))


def save_baseline(keys: set[str]) -> None:
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump({"errors": sorted(keys)}, f, ensure_ascii=False, indent=1)
    print(f"[OK] 已写入 {len(keys)} 条类型错误基线 -> {os.path.basename(BASELINE_FILE)}")


def _by_file(keys: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in keys:
        f = k.split("|", 1)[0]
        out[f] = out.get(f, 0) + 1
    return out


def main() -> int:
    update = "--update-baseline" in sys.argv
    report_only = "--report" in sys.argv

    current, raw = collect_errors()
    baseline = load_baseline()
    new_errors = current - baseline
    fixed = baseline - current

    print(f"mypy 错误: {raw} 条（归一化后 {len(current)} 个唯一键），基线 {len(baseline)} 个")

    if report_only:
        for f, n in sorted(_by_file(current).items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {n:>4}  {f}")
        return 0

    if update:
        if os.path.isfile(BASELINE_FILE) and len(new_errors) > len(fixed):
            print(
                f"[FAIL] 新增 {len(new_errors)} 个 < 修复 {len(fixed)} 个，基线不会被放宽。"
                " 请先修好新增错误再收紧基线。"
            )
            for e in sorted(new_errors)[:10]:
                print("  +", e)
            return 1
        save_baseline(current)
        print(f"     收紧: 修复 {len(fixed)} 个，新增 {len(new_errors)} 个")
        return 0

    if new_errors:
        print(f"[FAIL] 出现 {len(new_errors)} 个新的类型错误:")
        for e in sorted(new_errors)[:20]:
            print("  +", e)
        if len(new_errors) > 20:
            print(f"  ... 另有 {len(new_errors) - 20} 个")
        return 1

    if fixed:
        print(f"[OK] 类型门禁通过；另有 {len(fixed)} 个历史错误已修复，可运行 --update-baseline 收紧基线")
    else:
        print("[OK] 类型门禁通过（无新增类型错误）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
