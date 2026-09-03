"""
弹幕情绪侧写 — A3

对每个监控视频最近拉取到的弹幕做情绪打分（复用 utils.sentiment_analyzer
纯规则词典），结果缓存在 gui._danmaku_sentiment[bvid]，供:
    - 异常告警通知附带情绪摘要（main_gui_tick.scan_alerts_background）
    - 日报 / AI 问答等扩展读取

注意:
    - 全规则实现, 不依赖外部 API / LLM, 离线可用
    - 弹幕量极小(新视频)时返回 None, 不误导
"""

import logging
import threading

logger = logging.getLogger(__name__)

_sentiment_lock = threading.Lock()

# 单次分析读取的最近弹幕条数上限
_MAX_SAMPLE = 200
# 至少需要多少条弹幕才产出情绪画像
_MIN_SAMPLE = 8


def analyze_recent(gui, bvid: str) -> dict | None:
    """读取 bvid 最近弹幕并分析情绪, 缓存到 gui._danmaku_sentiment。

    Returns:
        dict | None: {"positive":.., "neutral":.., "negative":.., "n": 样本数,
                       "label": "正向/中性/负向", "keywords": [..]}
                     数据不足时返回 None
    """
    if gui is None:
        return None
    try:
        vdb = gui.video_dbs.get(bvid) if hasattr(gui, "video_dbs") else None
        if vdb is None:
            return None
        rows = vdb.get_danmaku_records(limit=_MAX_SAMPLE)
        if not rows:
            return None
        texts = [r.get("content", "") for r in rows if r.get("content")]
        if len(texts) < _MIN_SAMPLE:
            return None

        from utils.sentiment_analyzer import analyze_sentiment, extract_keywords

        ratio = analyze_sentiment(texts)
        n = len(texts)
        # 主情绪标签（含"偏"倾向）
        if ratio["positive"] >= 0.5:
            label = "正向"
        elif ratio["negative"] >= 0.5:
            label = "负向"
        elif ratio["positive"] > ratio["negative"] + 0.1:
            label = "偏正向"
        elif ratio["negative"] > ratio["positive"] + 0.1:
            label = "偏负向"
        else:
            label = "中性"
        keywords = [w for w, _ in extract_keywords(texts, top_n=5)]

        result = {
            "positive": ratio["positive"],
            "neutral": ratio["neutral"],
            "negative": ratio["negative"],
            "n": n,
            "label": label,
            "keywords": keywords,
        }
        with _sentiment_lock:
            cache = getattr(gui, "_danmaku_sentiment", None)
            if cache is None:
                cache = {}
                gui._danmaku_sentiment = cache
            cache[bvid] = result
        return result
    except Exception as e:
        logger.debug("弹幕情绪分析失败 %s: %s", bvid, e)
        return None


def get_sentiment(gui, bvid: str) -> dict | None:
    """读取缓存的情绪画像（无则尝试现算一次）。"""
    if gui is None:
        return None
    cache = getattr(gui, "_danmaku_sentiment", None)
    if cache and bvid in cache:
        return cache.get(bvid)
    return analyze_recent(gui, bvid)


def format_summary(gui, bvid: str, fallback: str = "") -> str:
    """生成一行情绪摘要文案, 供告警/日报追加。"""
    info = get_sentiment(gui, bvid)
    if not info:
        return fallback
    line = (
        f"弹幕情绪: {info['label']} "
        f"(👍{info['positive'] * 100:.0f}% / 👎{info['negative'] * 100:.0f}% / "
        f"样本 {info['n']} 条)"
    )
    if info.get("keywords"):
        line += f" 热词: {'/'.join(info['keywords'][:4])}"
    return line


def remove_bvid(gui, bvid: str):
    """移除缓存（删除监控时清理）。"""
    if gui is None:
        return
    with _sentiment_lock:
        cache = getattr(gui, "_danmaku_sentiment", None)
        if cache:
            cache.pop(bvid, None)
