"""
报告导出模块 — 生成多种格式的视频数据报告

支持导出格式：
- HTML: 包含统计卡片、数据表格、健康探针分析的网页报告
- Excel: 使用 pandas + openpyxl 生成 .xlsx 文件（无 pandas 时自动降级为 CSV）
- CSV:  纯表格数据导出（UTF-8 BOM 编码，Excel 可直接打开）
- JSON: 结构化数据导出，包含摘要和完整视频数据

输出目录: reports/
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Optional

from utils import project_path

logger = logging.getLogger(__name__)

# 报告输出目录
_OUTPUT_DIR = project_path("reports")


def _fmt(n):
    """格式化大数字为易读的中文单位。

    规则：
    - >= 1亿：显示为 x.xx亿
    - >= 1万：显示为 x.x万
    - 小于 1万：原样显示

    Args:
        n: 数字

    Returns:
        str: 格式化后的字符串，如 "12.5万", "3.42亿", "800"
    """
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


def generate_summary(videos: List[Dict]) -> Dict:
    """从视频数据列表中生成摘要统计数据。

    计算的总览指标包括：视频总数、总播放量、总点赞数、总硬币数、
    总收藏数、已达标 1 万播放的视频数、平均赞播比。

    Args:
        videos: 视频数据字典列表，每个字典需包含 view_count 等字段

    Returns:
        dict: 摘要数据字典，包含 total/total_views/total_likes 等字段
    """
    total = len(videos)
    total_views = sum(v.get("view_count", 0) for v in videos)
    total_likes = sum(v.get("like_count", 0) for v in videos)
    total_coins = sum(v.get("coin_count", 0) for v in videos)
    total_favs = sum(v.get("favorite_count", 0) for v in videos)
    # 已达标 1 万播放：播放量 >= 10000 的视频数
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


def export_html(videos: List[Dict], output_path: Optional[str] = None, title: str = "B站监控数据报告") -> str:
    """生成 HTML 格式的可视化数据报告。

    报告包含：
    - 顶部统计卡片（监控视频数、总播放、总点赞、已达标数、赞播比）
    - 视频数据详情表格（BV号、标题、UP主、播放、点赞、硬币、收藏、弹幕）
    - 一键三连健康探针表格（如有数据）

    Args:
        videos: 视频数据字典列表
        output_path: 输出文件路径，为 None 时自动生成 reports/report_{timestamp}.html
        title: 报告标题

    Returns:
        str: 生成的 HTML 文件路径
    """
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    summary = generate_summary(videos)

    # 构建视频数据表格的 HTML 行
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

    # 构建健康探针表格的 HTML 行
    health_rows = ""
    try:
        from utils.interaction_quality import calculate_probe_from_dict

        for v in videos:
            r = calculate_probe_from_dict(v)
            # 评级颜色映射（B站主题色系）
            grade_color = {"S": "#fb7299", "A": "#23ade5", "B": "#42b983", "C": "#f5a623", "D": "#e74c3c"}
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
    except Exception as e:
        logger.debug("生成报告 HTML 行失败: %s", e)

    # 构建完整 HTML 文档
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
    """生成 Excel 格式报告（需要 pandas 和 openpyxl）。

    如果 pandas 不可用，自动降级为 CSV 格式导出。

    输出包含两个工作表：
    - 视频数据：BV号、标题、UP主、播放量、互动数据等
    - 摘要：统计数据概览

    Args:
        videos: 视频数据字典列表
        output_path: 输出文件路径，为 None 时自动生成

    Returns:
        str: 生成的文件路径（.xlsx 或 .csv）
    """
    os.makedirs(_OUTPUT_DIR, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        # pandas 不可用时自动降级为 CSV 格式
        csv_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        import csv

        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["BV号", "标题", "UP主", "播放", "点赞", "硬币", "收藏", "弹幕", "评论", "分享"])
            for v in videos:
                w.writerow(
                    [
                        v.get("bvid", ""),
                        v.get("title", ""),
                        v.get("author", ""),
                        v.get("view_count", 0),
                        v.get("like_count", 0),
                        v.get("coin_count", 0),
                        v.get("favorite_count", 0),
                        v.get("danmaku_count", 0),
                        v.get("reply_count", 0),
                        v.get("share_count", 0),
                    ]
                )
        return csv_path

    # 构建 DataFrame
    df = pd.DataFrame(
        [
            {
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
            }
            for v in videos
        ]
    )

    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

    with pd.ExcelWriter(output_path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="视频数据", index=False)
        summary = generate_summary(videos)
        sdf = pd.DataFrame([summary])
        sdf.to_excel(w, sheet_name="摘要", index=False)

    return output_path


def export_csv(videos: List[Dict], output_path: Optional[str] = None) -> str:
    """生成纯 CSV 格式报告（UTF-8 BOM 编码，Excel 可直接打开不乱码）。

    Args:
        videos: 视频数据字典列表
        output_path: 输出文件路径，为 None 时自动生成

    Returns:
        str: 生成的 CSV 文件路径
    """
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    import csv

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["BV号", "标题", "UP主", "播放", "点赞", "硬币", "收藏", "弹幕", "评论", "分享"])
        for v in videos:
            w.writerow(
                [
                    v.get("bvid", ""),
                    v.get("title", ""),
                    v.get("author", ""),
                    v.get("view_count", 0),
                    v.get("like_count", 0),
                    v.get("coin_count", 0),
                    v.get("favorite_count", 0),
                    v.get("danmaku_count", 0),
                    v.get("reply_count", 0),
                    v.get("share_count", 0),
                ]
            )
    logger.info("CSV 导出完成: %s", output_path)
    return output_path


def export_json(videos: List[Dict], output_path: Optional[str] = None) -> str:
    """生成 JSON 格式报告（包含摘要和完整视频数据）。

    适合程序化处理或与其他系统集成。

    Args:
        videos: 视频数据字典列表
        output_path: 输出文件路径，为 None 时自动生成

    Returns:
        str: 生成的 JSON 文件路径
    """
    import json

    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    summary = generate_summary(videos)
    data = {"summary": summary, "videos": videos}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)  # ensure_ascii=False 保留中文
    logger.info("JSON 导出完成: %s", output_path)
    return output_path


def export_prediction_vs_actual(video_dbs: Dict, output_dir: Optional[str] = None) -> str:
    """导出预测值 vs 实际播放量对比表（CSV 格式）。

    从各视频的数据库记录中提取预测数据和实际数据，计算误差和误差率，
    用于评估各预测算法的准确性。

    输出列: bvid, algorithm, timestamp, predicted, actual, error, error_pct

    Args:
        video_dbs: {bvid: VideoDatabase} 的映射字典
        output_dir: 输出目录，为 None 时使用默认 reports/ 目录

    Returns:
        str: 生成的 CSV 文件路径，无数据时返回空字符串
    """
    import csv

    os.makedirs(output_dir or _OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(
        output_dir or _OUTPUT_DIR,
        f"pred_vs_actual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )
    rows = []
    for bvid, vdb in video_dbs.items():
        try:
            predictions = vdb.get_predictions(limit=2000)  # 最多取 2000 条预测记录
        except Exception:
            continue
        for p in predictions:
            # 兼容多种字段名（不同版本的数据库 schema）
            pred = p.get("predicted_views", 0) or p.get("predicted_view", 0) or p.get("current_views", 0)
            actual = p.get("current_views_at_eval", 0) or p.get("actual_views", 0)
            algo = p.get("algorithm", p.get("algorithm_name", "未知"))
            ts = p.get("created_at", p.get("timestamp", ""))
            if pred > 0 and actual > 0:
                rows.append({
                    "bvid": bvid,
                    "algorithm": algo,
                    "timestamp": str(ts),
                    "predicted": pred,
                    "actual": actual,
                    "error": pred - actual,  # 绝对误差
                    "error_pct": (pred - actual) / actual * 100,  # 百分比误差
                })
    if not rows:
        return ""  # 无预测数据
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["bvid", "algorithm", "timestamp", "predicted", "actual", "error", "error_pct"])
        w.writeheader()
        w.writerows(rows)
    logger.info("预测对比表导出完成: %s (%d 条)", output_path, len(rows))
    return output_path
