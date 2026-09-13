"""异动复盘卡 — A2

smart_alert 检测到高确定度异常时，将触发上下文聚合成一张可读的 HTML 复盘卡，
保存到 reports/alerts/，便于用户打开查看"发生了什么、何时、确认度多高"。

触发入口：ui/main_gui_tick.scan_alerts_background → build_alert_review(gui, hits)
"""

import html
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from utils import project_path

    _ALERT_DIR = os.path.join(project_path("reports"), "alerts")
except Exception:  # 兜底：与 report_exporter 同目录策略
    _ALERT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "alerts")


def _fmt_count(n) -> str:
    """大数字中文缩写"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return f"{int(n):,}"


def _esc(t):
    return html.escape(str(t))


def _level_color(level: str) -> str:
    return {"high": "#e74c3c", "medium": "#f5a623", "low": "#8e8e8e"}.get(level, "#666")


def _recent_records(gui, bvid: str, limit: int = 24) -> list:
    """读取 bvid 最近记录做迷你趋势展示"""
    try:
        vdb = gui.video_dbs.get(bvid) if hasattr(gui, "video_dbs") else None
        if vdb is None:
            return []
        return vdb.get_all_records(limit=limit) or []
    except Exception:
        return []


def build_alert_review(
    gui: Any, hits: list[tuple[str, str, Any]], extra_video_ctx: dict[str, dict[str, Any]] | None = None
) -> str:
    """生成一次异动扫描的复盘卡 HTML。

    Args:
        gui: 主窗口
        hits: list[(bvid, title_short, AlertHit)]
        extra_video_ctx: 可选 {bvid: {extra fields}}

    Returns:
        str: 复盘卡绝对路径；失败返回 ""
    """
    try:
        os.makedirs(_ALERT_DIR, exist_ok=True)
    except Exception as e:
        logger.debug("创建复盘目录失败: %s", e)
        return ""

    now = datetime.now()
    fname = f"alert_review_{now.strftime('%Y%m%d_%H%M%S')}.html"
    out_path = os.path.join(_ALERT_DIR, fname)

    # 按视频聚合
    by_bvid: dict[str, dict[str, Any]] = {}
    for bvid, t, hit in hits:
        by_bvid.setdefault(bvid, {"title": t, "hits": []})["hits"].append(hit)

    blocks = []
    for bvid, info in by_bvid.items():
        rows = _recent_records(gui, bvid)
        # 最近 12 点迷你表格
        mini = ""
        if rows:
            head = "".join(f"<th>{_esc(r.get('timestamp', ''))[5:16]}</th>" for r in rows[-12:])
            view_cells = "".join(f"<td>{_fmt_count(r.get('view_count', 0))}</td>" for r in rows[-12:])
            online_cells = "".join(f"<td>{_fmt_count(r.get('viewers_total', 0))}</td>" for r in rows[-12:])
            mini = f"""
            <table class="mini">
              <tr><th></th>{head}</tr>
              <tr><td class="lbl">播放</td>{view_cells}</tr>
              <tr><td class="lbl">在线</td>{online_cells}</tr>
            </table>"""
        else:
            mini = '<div class="dim">暂无明细记录</div>'

        hit_rows = ""
        for hit in info["hits"]:
            color = _level_color(hit.level)
            hit_rows += f"""
            <div class="hit">
              <span class="lvl" style="background:{color}">{_esc(hit.level)} · {hit.confidence:.0%}</span>
              <span class="hmsg">{_esc(hit.message)}</span>
            </div>"""
        blocks.append(f"""
        <div class="card">
          <div class="vtitle">
            <span class="bvid">{_esc(bvid)}</span>
            {_esc(info['title'])}
          </div>
          {hit_rows}
          {mini}
        </div>""")

    video_ctx_block = ""
    if extra_video_ctx:
        rows_ctx = ""
        for bvid, ctx in extra_video_ctx.items():
            rows_ctx += (
                f"<tr><td>{_esc(bvid)}</td><td>{_fmt_count(ctx.get('view_count', 0))}</td>"
                f"<td>{_fmt_count(ctx.get('viewers_total', 0))}</td></tr>"
            )
        video_ctx_block = f"""
        <div class="section">扫描时刻全量视频快照</div>
        <table>
          <tr><th>BV号</th><th>播放</th><th>在线</th></tr>
          {rows_ctx}
        </table>"""

    total_hits = len(hits)
    high_n = sum(1 for _, _, h in hits if h.level == "high")

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>异动复盘卡</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Microsoft YaHei UI',sans-serif; background:#f5f6f8; color:#333; padding:20px; }}
h1 {{ font-size:20px; }}
.sub {{ color:#888; font-size:12px; margin:6px 0 16px; }}
.cards {{ display:flex; gap:12px; margin-bottom:18px; }}
.card-stat {{ flex:1; background:#fff; border-radius:8px; padding:14px 18px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.card-stat .label {{ color:#888; font-size:12px; }}
.card-stat .value {{ font-size:22px; font-weight:bold; margin-top:4px; }}
.card {{ background:#fff; border-radius:8px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:14px; }}
.vtitle {{ font-weight:bold; font-size:14px; margin-bottom:8px; }}
.bvid {{ color:#fb7299; font-family:Consolas; font-size:12px; margin-right:6px; }}
.hit {{ padding:6px 0; border-bottom:1px solid #f0f0f0; }}
.hit:last-child {{ border-bottom:none; }}
.lvl {{ display:inline-block; color:#fff; font-size:11px; border-radius:3px; padding:1px 6px; margin-right:6px; }}
.hmsg {{ font-size:13px; }}
.mini {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:11px; }}
.mini th, .mini td {{ border-top:1px solid #eee; padding:2px 6px; text-align:right; font-family:Consolas; }}
.mini .lbl {{ text-align:left; color:#888; }}
.mini th {{ color:#aaa; font-weight:normal; }}
.section {{ font-size:14px; font-weight:bold; margin:16px 0 8px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; }}
th {{ background:#f0f2f5; text-align:left; padding:8px 12px; font-size:12px; color:#666; }}
td {{ padding:6px 12px; border-top:1px solid #eee; font-size:13px; font-family:Consolas; }}
.dim {{ color:#bbb; font-size:12px; padding:8px 0; }}
</style>
</head><body>
<h1>异动复盘卡 ♪</h1>
<div class="sub">扫描时间: {now.strftime('%Y-%m-%d %H:%M:%S')} · 共 {total_hits} 条告警（高确定度 {high_n} 条）</div>
<div class="cards">
  <div class="card-stat"><div class="label">告警视频</div><div class="value">{len(by_bvid)}</div></div>
  <div class="card-stat"><div class="label">告警总数</div><div class="value">{total_hits}</div></div>
  <div class="card-stat"><div class="label">高确定度</div><div class="value">{high_n}</div></div>
</div>
{''.join(blocks)}
{video_ctx_block}
</body></html>"""

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(page)
        return out_path
    except Exception as e:
        logger.warning("写异动复盘卡失败: %s", e)
        return ""
