"""
数据库查询 — CSV/Excel 导出辅助函数

从 database_query.py 提取的纯数据组装函数，无 GUI 依赖。
"""
from typing import Optional


_BASE_EXPORT_HEADERS = [
    "序号", "BV号", "时间", "播放量", "点赞", "投币", "分享", "收藏",
    "弹幕", "评论", "APP观看", "网页观看", "总观看", "播赞比",
    "周刊总分", "周刊播放", "周刊互动", "周刊收藏", "周刊硬币", "周刊点赞",
    "周刊修正A", "周刊修正B", "周刊修正C", "周刊修正D", "周刊基础播放",
    "年刊总分", "年刊播放", "年刊互动", "年刊收藏", "年刊硬币", "年刊点赞",
    "年刊修正A", "年刊修正B", "年刊修正C",
]


def build_export_headers(algo_names: list) -> list:
    """组装 CSV/Excel 导出表头（基础列 + 算法预测列）"""
    headers = list(_BASE_EXPORT_HEADERS)
    for name in algo_names:
        headers.append(f"{name}_预测时间")
        headers.append(f"{name}_预测秒数")
        headers.append(f"{name}_置信度")
    return headers


def build_export_row(index: int, row, extra: Optional[dict] = None, algo_names: Optional[list] = None) -> list:
    """组装 CSV/Excel 导出的单行数据"""
    e = extra or {}
    algo_names = algo_names or []
    if hasattr(row, "keys"):
        row = dict(row)
    algo_pred_map = {}
    for pred in e.get("_predictions", []):
        algo = pred.get("algorithm", "")
        if algo not in algo_pred_map:
            algo_pred_map[algo] = pred

    base_row = [
        index, row["bvid"], row["timestamp"],
        row["view_count"], row["like_count"], row["coin_count"],
        row["share_count"], row["favorite_count"],
        row["danmaku_count"], row["reply_count"],
        row.get("viewers_app", "") or "",
        row.get("viewers_web", "") or "",
        row.get("viewers_total", "") or "",
        row.get("like_view_ratio", "") or "",
        e.get("weekly_total", ""), e.get("weekly_view", ""),
        e.get("weekly_interaction", ""), e.get("weekly_favorite", ""),
        e.get("weekly_coin", ""), e.get("weekly_like", ""),
        e.get("weekly_corr_a", ""), e.get("weekly_corr_b", ""),
        e.get("weekly_corr_c", ""), e.get("weekly_corr_d", ""),
        e.get("weekly_base_view", ""),
        e.get("yearly_total", ""), e.get("yearly_view", ""),
        e.get("yearly_interaction", ""), e.get("yearly_favorite", ""),
        e.get("yearly_coin", ""), e.get("yearly_like", ""),
        e.get("yearly_corr_a", ""), e.get("yearly_corr_b", ""),
        e.get("yearly_corr_c", ""),
    ]
    for name in algo_names:
        pred = algo_pred_map.get(name, {})
        base_row.append(pred.get("predicted_time", ""))
        base_row.append(pred.get("predicted_seconds", ""))
        base_row.append(pred.get("confidence", ""))
    return base_row
