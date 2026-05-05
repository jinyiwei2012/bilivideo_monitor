"""
报告导出模块 — 生成 HTML / Excel 格式的数据报告
"""
import os
import io
from datetime import datetime
from typing import List, Dict, Optional


_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


def _fmt(n):
    if n >= 1_0000_0000:
        return f"{n/1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n/1_0000:.1f}万"
    return str(n)


def generate_summary(videos: List[Dict]) -> Dict:
    """生成摘要数据"""
    total = len(videos)
    total_views = sum(v.get("view_count", 0) for v in videos)
    total_likes = sum(v.get("like_count", 0) for v in videos)
    total_coins = sum(v.get("coin_count", 0) for v in videos)
    total_favs = sum(v.get("favorite_count", 0) for v in videos)
    achieved = sum(1 for v in videos if v.get("view_count", 0) >= 10000)
    avg_like_rate = (total_likes / total_views * 100) if total_views > 0 else 0

    return {
        "total": total,
        "total_views": total_views,
        "total_likes": total_likes,
        "total_coins": total_coins,
        "total_favs": total_favs,
        "achieved_10k": achieved,
        "avg_like_rate": round(avg_like_rate, 2),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def export_html(videos: List[Dict], output_path: Optional[str] = None,
                title: str = "B站监控数据报告") -> str:
    """生成 HTML 格式报告"""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    summary = generate_summary(videos)

    video_rows = ""
    for i, v in enumerate(videos, 1):
        video_rows += f"""
        <tr>
            <td>{i}</td>
            <td>{v.get('bvid', '')}</td>
            <td title="{v.get('title', '')}">{v.get('title', '')[:30]}</td>
            <td>{v.get('author', '')}</td>
            <td class="num">{_fmt(v.get('view_count', 0))}</td>
            <td class="num">{_fmt(v.get('like_count', 0))}</td>
            <td class="num">{_fmt(v.get('coin_count', 0))}</td>
            <td class="num">{_fmt(v.get('favorite_count', 0))}</td>
            <td class="num">{_fmt(v.get('danmaku_count', 0))}</td>
        </tr>"""

    # 健康探针
    health_rows = ""
    try:
        from utils.interaction_quality import calculate_probe_from_dict
        for v in videos:
            r = calculate_probe_from_dict(v)
            grade_color = {"S":"#fb7299","A":"#23ade5","B":"#42b983","C":"#f5a623","D":"#e74c3c"}
            gc = grade_color.get(r.health_grade, "#666")
            health_rows += f"""
            <tr>
                <td>{v.get('bvid', '')[:14]}</td>
                <td>{v.get('title', '')[:25]}</td>
                <td class="num" style="color:{gc};font-weight:bold">{r.health_score:.0f} ({r.health_grade})</td>
                <td class="num">{r.like_rate:.2f}%</td>
                <td class="num">{r.coin_rate:.2f}%</td>
                <td class="num">{r.favorite_rate:.2f}%</td>
                <td class="num">{r.share_rate:.2f}%</td>
            </tr>"""
    except Exception:
        pass

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,'Microsoft YaHei UI',sans-serif; background:#f5f6f8; color:#333; padding:20px; }}
h1 {{ font-size:22px; margin-bottom:6px; }}
.report-date {{ color:#888; font-size:13px; margin-bottom:20px; }}
.cards {{ display:flex; gap:12px; margin-bottom:20px; }}
.card {{ flex:1; background:white; border-radius:8px; padding:16px 20px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.card .label {{ color:#888; font-size:12px; }}
.card .value {{ font-size:24px; font-weight:bold; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:20px; }}
th {{ background:#f0f2f5; text-align:left; padding:10px 12px; font-size:12px; color:#666; }}
td {{ padding:8px 12px; border-top:1px solid #eee; font-size:13px; }}
.num {{ text-align:right; font-family:Consolas,monospace; }}
.section-title {{ font-size:15px; font-weight:bold; margin:16px 0 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="report-date">生成时间: {summary['generated_at']}</div>

<div class="cards">
    <div class="card"><div class="label">监控视频</div><div class="value">{summary['total']}</div></div>
    <div class="card"><div class="label">总播放</div><div class="value">{_fmt(summary['total_views'])}</div></div>
    <div class="card"><div class="label">总点赞</div><div class="value">{_fmt(summary['total_likes'])}</div></div>
    <div class="card"><div class="label">已达标(万)</div><div class="value">{summary['achieved_10k']}</div></div>
    <div class="card"><div class="label">赞播比</div><div class="value">{summary['avg_like_rate']}%</div></div>
</div>

<div class="section-title">视频数据详情</div>
<table>
<tr><th>#</th><th>BV号</th><th>标题</th><th>UP主</th><th>播放</th><th>点赞</th><th>硬币</th><th>收藏</th><th>弹幕</th></tr>
{video_rows}
</table>
"""
    if health_rows:
        html += f"""
<div class="section-title">一键三连健康探针</div>
<table>
<tr><th>BV号</th><th>标题</th><th>健康分</th><th>点赞率</th><th>硬币率</th><th>收藏率</th><th>分享率</th></tr>
{health_rows}
</table>
"""

    html += "\n</body></html>"

    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def export_excel(videos: List[Dict], output_path: Optional[str] = None) -> str:
    """生成 Excel 格式报告（需要 openpyxl）"""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        # Fallback to CSV
        csv_path = output_path or os.path.join(
            _OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        import csv
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["BV号", "标题", "UP主", "播放", "点赞", "硬币", "收藏", "弹幕", "评论", "分享"])
            for v in videos:
                w.writerow([
                    v.get("bvid", ""), v.get("title", ""), v.get("author", ""),
                    v.get("view_count", 0), v.get("like_count", 0),
                    v.get("coin_count", 0), v.get("favorite_count", 0),
                    v.get("danmaku_count", 0), v.get("reply_count", 0),
                    v.get("share_count", 0),
                ])
        return csv_path

    df = pd.DataFrame([{
        "BV号": v.get("bvid", ""),
        "标题": v.get("title", ""),
        "UP主": v.get("author", ""),
        "播放": v.get("view_count", 0),
        "点赞": v.get("like_count", 0),
        "硬币": v.get("coin_count", 0),
        "收藏": v.get("favorite_count", 0),
        "弹幕": v.get("danmaku_count", 0),
        "评论": v.get("reply_count", 0),
        "分享": v.get("share_count", 0),
    } for v in videos])

    output_path = output_path or os.path.join(
        _OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

    with pd.ExcelWriter(output_path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="视频数据", index=False)
        summary = generate_summary(videos)
        sdf = pd.DataFrame([summary])
        sdf.to_excel(w, sheet_name="摘要", index=False)

    return output_path
