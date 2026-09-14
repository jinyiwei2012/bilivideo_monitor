"""发版变更日志生成器（发版流水线专用）。

产出两份内容：
1. ``--out-body``：**省流版**，写入 GitHub Release 正文。客户端（utils/update_checker）
   读取 Release body 展示给用户，所以这里只保留用户可感知的「新功能 / 修复 / 性能」，
   并附上完整版链接。
2. ``--out-entry``：**完整版**，由 ``--append-to CHANGELOG.md`` 追加到仓库变更日志，
   含全部改动分类与提交短哈希，供在 GitHub 上查阅。

用法::

    python scripts/changelog_release.py --version 3.2.1 --channel pre \
        --out-body release_body.md --out-entry changelog_entry.md
    python scripts/changelog_release.py --append-to CHANGELOG.md --entry changelog_entry.md

    --prev-tag 可显式指定变更起点；默认取 ``git describe --tags --abbrev=0``（无 tag 则从首个提交起）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import subprocess

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# 提交类型 -> (分类标题, 表情, 是否进省流版)
CATEGORIES: dict[str, tuple[str, str, bool]] = {
    "feat": ("新功能", "🚀", True),
    "fix": ("修复", "🐛", True),
    "perf": ("性能优化", "⚡", True),
    "refactor": ("重构", "🧩", False),
    "test": ("测试", "🧪", False),
    "ci": ("CI / 构建", "🔧", False),
    "build": ("CI / 构建", "🔧", False),
    "docs": ("文档", "📝", False),
    "chore": ("维护", "🧰", False),
    "style": ("代码风格", "🎨", False),
    "revert": ("回滚", "⏪", False),
}
DEFAULT_CATEGORY = ("其他", "🧰", False)

_SUBJECT_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$")
_REPO_RE = re.compile(r"github\.com[:/](?P<slug>[^/]+/[^/.\s]+)")


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc.stdout.strip()


def resolve_prev_tag(explicit: str | None) -> str | None:
    """变更起点：显式指定优先，其次最近可达 tag，最后回退首个提交。"""
    if explicit:
        return explicit
    try:
        return _git("describe", "--tags", "--abbrev=0") or None
    except RuntimeError:
        pass
    try:
        return _git("rev-list", "--max-parents=0", "HEAD").splitlines()[-1]
    except RuntimeError:
        return None


def collect_commits(prev_tag: str | None) -> list[tuple[str, str]]:
    """返回 [(短哈希, 提交标题)]，**最新优先**（省流版要展示最近的改动），忽略合并提交。"""
    rng = f"{prev_tag}..HEAD" if prev_tag else "HEAD"
    out = _git("log", "--no-merges", "--pretty=format:%h\x1f%s", rng)
    commits: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "\x1f" in line:
            sha, subject = line.split("\x1f", 1)
            commits.append((sha.strip(), subject.strip()))
    return commits


def categorize(commits: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """按约定式提交前缀分组：标题 -> [(描述, 短哈希)]。"""
    groups: dict[str, list[tuple[str, str]]] = {}
    for sha, subject in commits:
        m = _SUBJECT_RE.match(subject)
        if m:
            key = m.group("type").lower()
            desc = m.group("desc").strip()
            if m.group("breaking"):
                desc = f"⚠️（不兼容变更）{desc}"
        else:
            key, desc = "", subject
        title = CATEGORIES.get(key, DEFAULT_CATEGORY)[0]
        groups.setdefault(title, []).append((desc, sha))
    return groups


def summary_lines(groups: dict[str, list[tuple[str, str]]], limit: int) -> tuple[list[str], int]:
    """省流版条目：只取用户可感知类别，截断到 limit，返回 (条目, 被省略数)。"""
    picked: list[str] = []
    for title in ("新功能", "修复", "性能优化"):
        emoji = next((e for t, e, _ in CATEGORIES.values() if t == title), "•")
        for desc, _sha in groups.get(title, []):
            picked.append(f"- {emoji} {desc}")
    omitted = max(0, len(picked) - limit)
    return picked[:limit], omitted


def repo_url() -> str:
    try:
        remote = _git("remote", "get-url", "origin")
    except RuntimeError:
        return ""
    m = _REPO_RE.search(remote)
    return f"https://github.com/{m.group('slug')}" if m else ""


def build_body(version: str, channel: str, groups: dict[str, list[tuple[str, str]]], limit: int) -> str:
    """GitHub Release 正文 = 客户端可见的省流版。"""
    lines, omitted = summary_lines(groups, limit)
    total = sum(len(v) for v in groups.values())
    if not lines:
        lines = ["- 本次发布以内部维护与稳定性改进为主"]

    channel_note = (
        "> ⚠️ **预发布版本**：仅「beta 更新通道」会收到推送，stable 通道用户不受影响。"
        if channel == "pre"
        else "> ✅ **稳定版本**：stable 更新通道用户会收到自动更新提示。"
    )
    full_link = ""
    if repo_url():
        full_link = f"**完整变更日志**：{repo_url()}/blob/HEAD/CHANGELOG.md\n"

    head = [
        f"**版本**: {version}",
        f"**通道**: {channel}",
        f"**日期**: {_dt.date.today().isoformat()}",
        "",
        channel_note,
        "",
        "### 本次更新（省流）",
        *lines,
    ]
    if omitted or total > len(lines):
        head.append(f"- 其余 {omitted if omitted else total - len(lines)} 项改动见完整变更日志")
    head += [
        "",
        full_link.rstrip("\n"),
        f"**提交**: `{_git('rev-parse', '--short', 'HEAD')}`",
        "",
        "**安装 / 升级**：下载下方 `BiliMonitor.exe` 覆盖旧文件即可（程序内也会提示自动更新）。",
    ]
    return "\n".join(x for x in head if x != "") + "\n"


def build_entry(version: str, channel: str, groups: dict[str, list[tuple[str, str]]], prev_tag: str | None) -> str:
    """仓库 CHANGELOG.md 条目 = 完整版（分类 + 短哈希，便于在 GitHub 查阅）。"""
    today = _dt.date.today().isoformat()
    lines, omitted = summary_lines(groups, 8)
    out = [f"## Release {today} (v{version})", ""]
    if channel == "pre":
        out += ["> 预发布（beta 通道）", ""]
    if prev_tag:
        out += [f"> 变更区间：`{prev_tag}..HEAD`", ""]

    out += ["### 省流", "", *(lines or ["- 以内部维护与稳定性改进为主"])]
    if omitted:
        out.append(f"- 其余 {omitted} 项见下方完整分类")
    out.append("")

    for title in (
        "新功能",
        "修复",
        "性能优化",
        "重构",
        "测试",
        "CI / 构建",
        "文档",
        "维护",
        "代码风格",
        "回滚",
        "其他",
    ):
        items = groups.get(title)
        if not items:
            continue
        emoji = next((e for t, e, _ in CATEGORIES.values() if t == title), "•")
        out += [f"### {emoji} {title}", ""]
        out += [f"- {desc} (`{sha}`)" for desc, sha in items]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def append_to_changelog(changelog: pathlib.Path, entry: pathlib.Path) -> bool:
    """把完整版条目插到首个 ``## `` 段之前（保持「最新在最上」）。返回是否有变化。"""
    text = changelog.read_text(encoding="utf-8")
    new_entry = entry.read_text(encoding="utf-8").strip() + "\n\n"
    if new_entry.strip() in text:
        return False

    lines = text.splitlines()
    insert_at = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    merged = lines[:insert_at] + new_entry.splitlines() + lines[insert_at:]
    changelog.write_text("\n".join(merged).rstrip() + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="生成发版变更日志（省流版 + 完整版）")
    parser.add_argument("--version", help="版本号，如 3.2.1")
    parser.add_argument("--channel", choices=["pre", "stable"], default="pre")
    parser.add_argument("--prev-tag", help="变更起点（默认最近可达 tag）")
    parser.add_argument("--out-body", help="省流版输出路径（Release 正文）")
    parser.add_argument("--out-entry", help="完整版输出路径（CHANGELOG 条目）")
    parser.add_argument("--summary-limit", type=int, default=8, help="省流版最多条数")
    parser.add_argument("--append-to", help="把 --entry 指定的完整版条目追加进该 CHANGELOG 文件")
    parser.add_argument("--entry", help="要追加的完整版条目文件（配合 --append-to）")
    args = parser.parse_args()

    if args.append_to:
        if not args.entry:
            parser.error("--append-to 需要同时指定 --entry")
        changed = append_to_changelog(pathlib.Path(args.append_to), pathlib.Path(args.entry))
        print("[OK] CHANGELOG 已更新" if changed else "[OK] CHANGELOG 已是最新（无变化）")
        return 0

    if not args.version:
        parser.error("生成日志需要 --version")

    prev = resolve_prev_tag(args.prev_tag)
    commits = collect_commits(prev)
    groups = categorize(commits)
    print(f"变更区间: {prev or '(首个提交)'}..HEAD，共 {len(commits)} 条提交")
    for title, items in groups.items():
        print(f"  {title}: {len(items)} 条")

    if args.out_body:
        pathlib.Path(args.out_body).write_text(
            build_body(args.version, args.channel, groups, args.summary_limit), encoding="utf-8"
        )
        print(f"[OK] 省流版（客户端可见）-> {args.out_body}")
    if args.out_entry:
        pathlib.Path(args.out_entry).write_text(build_entry(args.version, args.channel, groups, prev), encoding="utf-8")
        print(f"[OK] 完整版（仓库变更日志）-> {args.out_entry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
