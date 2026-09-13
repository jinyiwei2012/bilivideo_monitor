"""Lint 门禁 — flake8 全量 + 复杂度基线棘轮（M3.1）。

规则：
- 任何**非 C901** 违规 → 直接失败（新代码必须干净）
- C901（圈复杂度超限）与基线比对：基线内的「已知高复杂度函数」放行，**新增者失败**
- 基线按**函数名**而非行号记录，代码移动不会误报；
  M3.4 重构掉一批后重跑 ``--update-baseline`` 即可收紧棘轮

用法::

    python scripts/lint_gate.py                   # 门禁检查（CI 用）
    python scripts/lint_gate.py --update-baseline # 用当前结果重写基线
"""

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE = PROJECT_ROOT / ".lint-baseline.json"
COMPLEX_RE = re.compile(r"'([^']+)' is too complex")


def run_flake8():
    """执行 flake8，返回 [(code, path, row, text), ...]。"""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "flake8",
            ".",
            "--no-show-source",
            "--format=%(code)s|%(path)s|%(row)d|%(text)s",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    items = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        code, path, row, text = parts
        items.append((code.strip(), path.replace(".\\", "").replace("\\", "/"), row, text))
    return items


def main() -> int:
    items = run_flake8()
    complex_names = sorted(
        {match.group(1) for code, _path, _row, text in items if code == "C901" and (match := COMPLEX_RE.search(text))}
    )
    others = [item for item in items if item[0] != "C901"]

    if "--update-baseline" in sys.argv:
        payload = {"complex_functions": complex_names}
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"基线已更新: {len(complex_names)} 个已知高复杂度函数 → {BASELINE.name}")
        return 0

    baseline = set()
    if BASELINE.exists():
        baseline = set(json.loads(BASELINE.read_text(encoding="utf-8")).get("complex_functions", []))

    failed = False
    if others:
        failed = True
        print(f"[FAIL] flake8 非复杂度违规 {len(others)} 项：")
        for code, path, row, text in others[:60]:
            print(f"  {path}:{row}: {code} {text}")

    new_complex = [name for name in complex_names if name not in baseline]
    if new_complex:
        failed = True
        print(f"[FAIL] 新增高复杂度函数 {len(new_complex)} 个（请重构，或确属既有债务才更新基线）：")
        for name in new_complex:
            print(f"  {name}")

    resolved = sorted(baseline - set(complex_names))
    if resolved:
        print(f"[INFO] 基线中已有 {len(resolved)} 项不再超标，建议重跑 --update-baseline 收紧：")
        for name in resolved[:20]:
            print(f"  {name}")

    if failed:
        return 1
    print(f"[OK] lint 门禁通过（复杂度基线内 {len(complex_names)} 项，非复杂度违规 0）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
