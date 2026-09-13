"""
报告导出模块 — 生成 HTML / Excel 格式的数据报告
"""

import os
import html
import logging
from datetime import datetime
from typing import List, Dict, Optional
from utils import project_path

logger = logging.getLogger(__name__)


_OUTPUT_DIR = project_path("reports")


def _fmt(n):
    """格式化大数字为易读的中文单位"""
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


def _csv_safe(value) -> str:
    """CSV/Excel 公式注入防护: 以 = + - @ 制表符 开头的单元格前置单引号"""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


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


def export_html(
    videos: List[Dict],
    output_path: Optional[str] = None,
    title: str = "B站监控数据报告",
    ai_insight: Optional[str] = None,
) -> str:
    """生成 HTML 格式报告。ai_insight 为可选的 AI 解读文本段。"""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    summary = generate_summary(videos)

    video_rows = ""
    for i, v in enumerate(videos, 1):
        video_rows += f"""
        <tr>
            <td>{i}</td>
            <td>{v.get('bvid', '')}</td>
            <td title="{html.escape(v.get('title', ''))}">{html.escape(v.get('title', '')[:30])}</td>
            <td>{html.escape(str(v.get('author', '')))}</td>
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
            grade_color = {"S": "#fb7299", "A": "#23ade5", "B": "#42b983", "C": "#f5a623", "D": "#e74c3c"}
            gc = grade_color.get(r.health_grade, "#666")
            health_rows += f"""
            <tr>
                <td>{v.get('bvid', '')[:14]}</td>
                <td>{html.escape(v.get('title', '')[:25])}</td>
                <td class="num" style="color:{gc};font-weight:bold">{r.health_score:.0f} ({r.health_grade})</td>
                <td class="num">{r.like_rate:.2f}%</td>
                <td class="num">{r.coin_rate:.2f}%</td>
                <td class="num">{r.favorite_rate:.2f}%</td>
                <td class="num">{r.share_rate:.2f}%</td>
            </tr>"""
    except Exception as e:
        logger.debug("生成报告HTML行失败: %s", e)

    html_doc = f"""<!DOCTYPE html>
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
.ai-box {{ background:#f0f7ff; border:1px solid #bcd8f5; border-radius:8px; padding:12px 16px; font-size:13px; line-height:1.7; color:#2c3e50; white-space:pre-wrap; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
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
        html_doc += f"""
<div class="section-title">一键三连健康探针</div>
<table>
<tr><th>BV号</th><th>标题</th><th>健康分</th><th>点赞率</th><th>硬币率</th><th>收藏率</th><th>分享率</th></tr>
{health_rows}
</table>
"""

    # C3: 可选 AI 解读段（插入 </body> 前）
    if ai_insight and ai_insight.strip():
        html_doc += f"""
<div class="section-title">◈ AI 数据解读</div>
<div class="ai-box">{html.escape(ai_insight.strip())}</div>
"""
    html_doc += "\n</body></html>"

    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return output_path


def export_excel(videos: List[Dict], output_path: Optional[str] = None) -> str:
    """生成 Excel 格式报告（需要 openpyxl）"""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        # Fallback to CSV
        csv_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        import csv

        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["BV号", "标题", "UP主", "播放", "点赞", "硬币", "收藏", "弹幕", "评论", "分享"])
            for v in videos:
                w.writerow(
                    [
                        v.get("bvid", ""),
                        _csv_safe(v.get("title", "")),
                        _csv_safe(v.get("author", "")),
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

    df = pd.DataFrame(
        [
            {
                "BV号": v.get("bvid", ""),
                "标题": _csv_safe(v.get("title", "")),
                "UP主": _csv_safe(v.get("author", "")),
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
    """生成 CSV 格式报告"""
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
                    _csv_safe(v.get("title", "")),
                    _csv_safe(v.get("author", "")),
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
    """生成 JSON 格式报告"""
    import json

    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    output_path = output_path or os.path.join(_OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    summary = generate_summary(videos)
    data = {"summary": summary, "videos": videos}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("JSON 导出完成: %s", output_path)
    return output_path


def export_prediction_vs_actual(video_dbs: Dict, output_dir: Optional[str] = None) -> str:
    """导出预测值 vs 实际播放量对比表（CSV）"""
    import csv

    os.makedirs(output_dir or _OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(
        output_dir or _OUTPUT_DIR,
        f"pred_vs_actual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )
    rows = []
    for bvid, vdb in video_dbs.items():
        try:
            predictions = vdb.get_predictions(limit=2000)
        except Exception:
            continue
        for p in predictions:
            pred = p.get("predicted_views", 0) or p.get("predicted_view", 0) or p.get("current_views", 0)
            actual = p.get("current_views_at_eval", 0) or p.get("actual_views", 0)
            algo = p.get("algorithm", p.get("algorithm_name", "未知"))
            ts = p.get("created_at", p.get("timestamp", ""))
            if pred > 0 and actual > 0:
                rows.append(
                    {
                        "bvid": bvid,
                        "algorithm": algo,
                        "timestamp": str(ts),
                        "predicted": pred,
                        "actual": actual,
                        "error": pred - actual,
                        "error_pct": (pred - actual) / actual * 100,
                    }
                )
    if not rows:
        return ""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f, fieldnames=["bvid", "algorithm", "timestamp", "predicted", "actual", "error", "error_pct"]
        )
        w.writeheader()
        w.writerows(rows)
    logger.info("预测对比表导出完成: %s (%d 条)", output_path, len(rows))
    return output_path


def generate_ai_insight(videos: List[Dict]) -> str:
    """C3: 用 LLM 生成报告 AI 解读段（需已配置 AI 密钥；无密钥/失败返回空串）。

    输入为监控视频列表，输出一段自然语言"本周表现解读 + 下周期待"。
    纯规则模块失败时也返回空串，调用方自动跳过 AI 段。
    """
    if not videos:
        return ""
    try:
        from config import get_active_ai_profile

        profile = get_active_ai_profile()
        if not profile.get("api_key"):
            return ""

        from utils.ai_qa import AIQASession

        session = AIQASession(
            api_key=profile.get("api_key", ""),
            endpoint=profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions",
            model=profile.get("model", "gpt-4o-mini"),
        )

        summary = generate_summary(videos)
        lines = [
            "你是B站数据分析助手。请用中文为一份监控周报写一段 150 字以内的解读，包含：",
            "1) 整体表现一句话（播放/互动规模、赞播比）；",
            "2) 表现最突出或最值得关注的 1-2 个视频及原因；",
            "3) 对下周趋势的一句简短展望。",
            "不要输出标题，直接给正文。",
            "",
            "整体数据：",
            f"监控 {summary['total']} 个视频，总播放 {summary['total_views']}，"
            f"总赞 {summary['total_likes']}，总投币 {summary['total_coins']}，"
            f"平均赞播比 {summary['avg_like_rate']}%，"
            f"播放破万 {summary['achieved_10k']} 个。",
            "",
            "视频明细：",
        ]
        for v in videos[:12]:
            lines.append(
                f"- {v.get('bvid', '')}《{(v.get('title') or '')[:28]}》："
                f"播放 {v.get('view_count', 0):,} 赞 {v.get('like_count', 0):,} "
                f"币 {v.get('coin_count', 0):,} 藏 {v.get('favorite_count', 0):,} "
                f"弹幕 {v.get('danmaku_count', 0):,}"
            )
        if len(videos) > 12:
            lines.append(f"- … 等共 {len(videos)} 个")
        prompt = "\n".join(lines)

        # 直接调用底层 API（避免 ask() 的规则回退与历史污染）
        answer = session.ask(prompt)
        answer = (answer or "").strip()
        # 若走规则回退会返回非解读内容 → 通过简单启发丢弃
        if not answer or answer.startswith("天依") or "监控" not in answer and len(answer) < 20:
            return ""
        # 清理可能的 markdown 标题
        for prefix in ("#", "##", "###", "**"):
            if answer.startswith(prefix):
                answer = answer.lstrip("#* \n")
        return answer[:800]
    except Exception as e:
        logger.warning("生成 AI 解读失败: %s", e)
        return ""
