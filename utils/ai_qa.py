"""
AI智能问答模块 — 基于监控数据的自然语言问答
支持 OpenAI 兼容 API，也可纯规则回答
"""

import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class AIQASession:
    """AI问答会话，管理对话历史并生成回答"""

    def __init__(self, api_key: str = "", endpoint: str = "", model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.endpoint = endpoint or "https://api.openai.com/v1/chat/completions"
        self.model = model
        # 如果没传 api_key，尝试从配置文件加载
        if not self.api_key:
            self._load_config()
        self.history: List[Dict] = []  # [{"role": "user"/"assistant", "content": str}, ...]
        self._monitored_videos: List[Dict] = []
        self._history_data: Dict = {}
        self._video_dbs: Dict = {}

    def _load_config(self):
        try:
            from config import get_active_ai_profile

            profile = get_active_ai_profile()
            self.api_key = profile.get("api_key", "")
            self.endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
            self.model = profile.get("model", "gpt-4o-mini")
        except Exception as e:
            logger.debug("加载AI配置失败: %s", e)

    def set_context(self, monitored_videos: List[Dict], history_data: Dict = None, video_dbs: Dict = None):
        """设置监控上下文数据"""
        self._monitored_videos = monitored_videos or []
        self._history_data = history_data or {}
        self._video_dbs = video_dbs or {}

    def build_context(self) -> str:
        """构建包含监控数据的系统提示"""
        lines = ["你是一个B站视频监控助手，根据监控数据回答用户问题。", ""]

        videos = self._monitored_videos
        lines.append(f"当前监控 {len(videos)} 个视频：")

        for v in videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:30]
            views = v.get("view_count", 0)
            likes = v.get("like_count", 0)
            coins = v.get("coin_count", 0)
            favs = v.get("favorite_count", 0)
            danmaku = v.get("danmaku_count", 0)
            lines.append(f"  {bvid} {title}")
            lines.append(f"    播放:{views:,} 点赞:{likes:,} 硬币:{coins:,} 收藏:{favs:,} 弹幕:{danmaku:,}")

            # 附加历史播放量趋势（用于增长分析）
            if bvid in self._history_data:
                pts = self._history_data[bvid]
                if len(pts) >= 2:
                    try:
                        sorted_pts = sorted(pts, key=lambda p: p[0] if isinstance(p[0], datetime) else p[0])
                    except Exception:
                        sorted_pts = pts
                    earliest = sorted_pts[0][1]
                    latest = sorted_pts[-1][1]
                    span_h = (sorted_pts[-1][0] - sorted_pts[0][0]).total_seconds() / 3600
                    # 采样关键数据点：首、中、尾
                    lines.append(f"    历史趋势: {len(sorted_pts)}条记录, 跨度{span_h:.1f}h")
                    lines.append(f"      起始: {sorted_pts[0][1]:,} → 当前: {latest:,}")
                    if span_h > 0:
                        hourly = (latest - earliest) / span_h
                        lines.append(f"      时速: {hourly:.1f}/h")

        lines.append("")
        lines.append("请用中文简洁回答。")
        return "\n".join(lines)

    def ask(self, question: str) -> str:
        """向AI提问

        如果有 API key，使用 LLM API；
        否则使用内置规则回答。
        """
        self.history.append({"role": "user", "content": question})

        if not self.api_key:
            # 尝试从配置读取
            try:
                from config import get_active_ai_profile

                profile = get_active_ai_profile()
                self.api_key = profile.get("api_key", "")
                self.endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
                self.model = profile.get("model", "gpt-4o-mini")
            except Exception as e:
                logger.debug("从配置加载API密钥失败: %s", e)

        if self.api_key:
            answer = self._ask_llm(question)
        else:
            answer = self._ask_rule(question)

        self.history.append({"role": "assistant", "content": answer})
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return answer

    def _ask_llm(self, question: str) -> str:
        """调用 LLM API（支持 OpenAI 兼容 和 Claude 格式）"""
        try:
            import requests

            system_msg = self.build_context()
            messages = [
                {"role": "system", "content": system_msg},
            ]
            # 加入最近对话历史
            for h in self.history[-10:]:
                messages.append(h)

            is_claude = "anthropic.com" in self.endpoint

            if is_claude:
                # Claude Messages API
                claude_messages = []
                for m in messages:
                    if m["role"] == "system":
                        continue  # Claude 用 system 参数
                    claude_messages.append({"role": m["role"], "content": m["content"]})

                resp = requests.post(
                    self.endpoint,
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": self.model,
                        "system": system_msg,
                        "max_tokens": 1024,
                        "temperature": 0.7,
                        "messages": claude_messages,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_list = data.get("content", [])
                    return content_list[0].get("text", "") if content_list else ""
                else:
                    logger.warning(f"Claude API 错误: {resp.status_code} {resp.text[:200]}")
                    return self._ask_rule(question)
            else:
                # OpenAI 兼容格式
                resp = requests.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 1024,
                        "temperature": 0.7,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.warning(f"LLM API 错误: {resp.status_code}")
                    return self._ask_rule(question)
        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")
            return self._ask_rule(question)

    def _ask_rule(self, question: str) -> str:
        """基于规则的简单回答"""
        q = question.lower()
        videos = self._monitored_videos

        if not videos:
            return "当前未监控任何视频。请先在主界面添加视频到监控列表，" "或使用「视频搜索」功能查找并添加视频后，再来向我提问。"

        handlers = [
            (["多少", "视频"], lambda: f"当前共监控 {len(videos)} 个视频。"),
            (["最快", "增长", "增速"], self._answer_fastest_growth),
            (["top", "top3", "排行", "最多"], self._answer_top_views),
            (["达标", "完成", "阈值"], self._answer_threshold),
            (["异常", "预警"], self._answer_anomaly),
            (["健康", "探针"], self._answer_health),
        ]
        for keywords, handler in handlers:
            if any(kw in q for kw in keywords):
                return handler()

        return f"我是监控助手，当前共监控 {len(videos)} 个视频。" f"你可以问我：当前监控多少视频？哪个增长最快？播放量排行？" f"有无异常预警？健康探针情况？"

    def _answer_anomaly(self) -> str:
        from core.smart_alert import AnomalyDetector

        alert_count = 0
        details = []
        for v in self._monitored_videos:
            bvid = v.get("bvid", "")
            if bvid in self._video_dbs:
                try:
                    records = self._video_dbs[bvid].get_all_records(limit=10)
                    alerts = AnomalyDetector.detect_all(records, bvid=bvid)
                    if alerts:
                        alert_count += len(alerts)
                        details.extend(alerts[:2])
                except Exception as e:
                    logger.debug("生成AI预警报告失败: %s", e)
        if alert_count > 0:
            return f"发现 {alert_count} 条异常预警：\n" + "\n".join(details[:5])
        return "当前无异常预警。"

    def _answer_fastest_growth(self) -> str:
        videos = self._monitored_videos
        if not videos:
            return "暂无监控视频。"
        best_v, best_rate = None, -1
        for v in videos:
            bvid = v.get("bvid", "")
            if bvid in self._history_data:
                pts = self._history_data[bvid]
                if len(pts) >= 2:
                    try:
                        sorted_pts = sorted(
                            pts,
                            key=lambda p: (
                                p[0]
                                if isinstance(p[0], datetime)
                                else (
                                    datetime.strptime(str(p[0])[:19], "%Y-%m-%d %H:%M:%S")
                                    if isinstance(p[0], str)
                                    else p[0]
                                )
                            ),
                        )
                    except Exception:
                        sorted_pts = pts
                    span = (sorted_pts[-1][0] - sorted_pts[0][0]).total_seconds()
                    if span > 0:
                        growth = sorted_pts[-1][1] - sorted_pts[0][1]
                        rate = growth / span * 3600
                        if rate > best_rate:
                            best_rate = rate
                            best_v = v
        if best_v:
            return (
                f"增长最快：{best_v.get('title', '')[:20]} " f"(时速 {best_rate:.0f}/h，" f"当前 {best_v.get('view_count', 0):,})"
            )
        return "暂无足够数据计算增速。"

    def _answer_top_views(self) -> str:
        sorted_v = sorted(self._monitored_videos, key=lambda v: v.get("view_count", 0), reverse=True)
        if not sorted_v:
            return "暂无监控视频。"
        lines = ["播放量排行："]
        for i, v in enumerate(sorted_v[:5], 1):
            lines.append(f"  {i}. {v.get('title', '')[:20]} — {v.get('view_count', 0):,}")
        return "\n".join(lines)

    def _answer_threshold(self) -> str:
        from config import load_config

        cfg = load_config().get("prediction", {})
        thresholds_raw = cfg.get("thresholds", [[100000, "10万"], [1000000, "100万"], [10000000, "1000万"]])
        thresholds = [t for t, _ in thresholds_raw]
        threshold_names = [n for _, n in thresholds_raw]

        achieved = 0
        nearing = []
        for v in self._monitored_videos:
            views = v.get("view_count", 0)
            for t, name in zip(thresholds, threshold_names):
                if views >= t:
                    achieved += 1
                elif views >= t * 0.8:
                    nearing.append(f"{v.get('title', '')[:20]} 距{name}还差{t - views:,}")

        result = f"已达标 {achieved} 个阈值。"
        if nearing:
            result += "\n即将达标：\n" + "\n".join(nearing[:5])
        return result

    def _answer_health(self) -> str:
        try:
            from utils.interaction_quality import calculate_probe_from_dict

            results = []
            for v in self._monitored_videos[:5]:
                r = calculate_probe_from_dict(v)
                results.append(f"{v.get('title', '')[:16]}: {r.health_score:.0f}分({r.health_grade})")
            if results:
                return "健康探针：\n" + "\n".join(results)
            return "暂无数据。"
        except Exception:
            return "健康探针暂时不可用。"
