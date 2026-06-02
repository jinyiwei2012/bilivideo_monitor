"""
AI 智能问答模块 — 基于监控数据的自然语言问答

支持两种回答模式：
1. LLM 模式（有 API Key）：调用 OpenAI 兼容 API（或 Claude API）生成回答
2. 规则模式（无 API Key）：通过关键词匹配 + 数据分析执行内置规则回答

功能特点：
- 自动从配置文件加载 AI 设置（API Key、Endpoint、Model）
- 构建包含当前监控视频数据的系统提示上下文
- 支持 API 限速（每秒最多 1 次调用，Token Bucket 策略）
- 对话历史管理（最近 20 条）
- 支持 OpenAI 兼容格式 和 Claude Messages API 两种 API 协议
- 会话结束后可清除 API Key（内存安全）

使用方式：
    from utils.ai_qa import AIQASession

    session = AIQASession()
    session.set_context(monitored_videos, history_data, video_dbs)
    answer = session.ask("当前监控了多少个视频？")
    print(answer)
"""

import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class AIQASession:
    """AI 问答会话管理器，维护对话历史并根据监控数据生成回答。

    本类封装了与 LLM API 的完整交互流程：
    1. 初始化时加载 API 配置
    2. set_context() 设置监控上下文数据
    3. ask() 方法处理用户问题（自动选择 LLM 或规则模式）
    4. build_context() 构建包含监控数据的系统提示
    """

    def __init__(self, api_key: str = "", endpoint: str = "", model: str = "gpt-4o-mini"):
        """初始化 AI 问答会话。

        如果未传入 api_key，自动尝试从配置文件加载 AI 设置。
        配置文件路径由 config.get_active_ai_profile() 返回。

        Args:
            api_key: LLM API 密钥（OpenAI / Claude）。为空时从配置加载
            endpoint: API 端点地址。为空时使用 OpenAI 默认地址
            model: 模型名称，默认 "gpt-4o-mini"（性价比高）
        """
        self.api_key = api_key
        self.endpoint = endpoint or "https://api.openai.com/v1/chat/completions"
        self.model = model
        # 如果没传 api_key，尝试从配置文件加载
        if not self.api_key:
            self._load_config()
        # 对话历史：按时间顺序存储用户/助手消息
        self.history: List[Dict] = []  # [{"role": "user"/"assistant", "content": str}, ...]
        # 监控上下文数据
        self._monitored_videos: List[Dict] = []  # 当前监控的视频列表
        self._history_data: Dict = {}  # {bvid: [(datetime, view_count), ...]} 历史播放量趋势
        self._video_dbs: Dict = {}  # {bvid: VideoDatabase} 视频数据库对象
        # API 限速相关
        self._last_call_time = 0.0  # 上次调用 API 的时间戳
        self._min_call_interval = 1.0  # 最小调用间隔（秒）

    def _load_config(self):
        """从配置文件加载 AI 设置。

        通过 config.get_active_ai_profile() 获取当前激活的 AI 配置文件，
        提取 api_key、endpoint、model 三个字段。

        加载失败时不抛出异常，仅记录 debug 日志。
        """
        try:
            from config import get_active_ai_profile

            profile = get_active_ai_profile()
            self.api_key = profile.get("api_key", "")
            self.endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
            self.model = profile.get("model", "gpt-4o-mini")
        except Exception as e:
            logger.debug("加载 AI 配置失败: %s", e)

    def set_context(self, monitored_videos: List[Dict], history_data: Dict = None, video_dbs: Dict = None):
        """设置 AI 问答所需的监控上下文数据。

        此方法应该在每次监控数据更新后调用，确保 AI 获取到最新的数据。

        Args:
            monitored_videos: 当前监控的视频数据列表，每个元素为 B站 API 返回的完整视频数据字典
            history_data: {bvid: [(timestamp, view_count), ...]} 各视频的历史播放量趋势数据
            video_dbs: {bvid: VideoDatabase} 各视频的数据库对象（用于异常检测等高级查询）
        """
        self._monitored_videos = monitored_videos or []
        self._history_data = history_data or {}
        self._video_dbs = video_dbs or {}

    def build_context(self) -> str:
        """构建包含当前监控数据的系统提示（System Prompt）。

        会汇总所有监控视频的基本信息、互动数据、历史播放量趋势等，
        组织成一个完整的上下文文本，作为 LLM 的 system message。

        Returns:
            str: 格式化的系统提示文本

        示例构造内容：
            当前监控 3 个视频：
              BV1xx4y1w7zz Python教程
                播放:12,500 点赞:800 硬币:300 收藏:500 弹幕:120
                历史趋势: 45条记录, 跨度24.5h
                  起始: 8,000 → 当前: 12,500
                  时速: 183.7/h
            ...
            请用中文简洁回答。
        """
        lines = ["你是一个B站视频监控助手，根据监控数据回答用户问题。", ""]

        videos = self._monitored_videos
        lines.append(f"当前监控 {len(videos)} 个视频：")

        for v in videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:30]  # 标题截断到 30 字符
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
                    earliest = sorted_pts[0][1]  # 最早的播放量
                    latest = sorted_pts[-1][1]  # 最新的播放量
                    ts_to_dt = lambda t: t if isinstance(t, datetime) else datetime.fromtimestamp(t)
                    span_h = (ts_to_dt(sorted_pts[-1][0]) - ts_to_dt(sorted_pts[0][0])).total_seconds() / 3600
                    # 采样关键数据点：首、尾，提供简要趋势信息
                    lines.append(f"    历史趋势: {len(sorted_pts)}条记录, 跨度{span_h:.1f}h")
                    lines.append(f"      起始: {sorted_pts[0][1]:,} → 当前: {latest:,}")
                    if span_h > 0:
                        hourly = (latest - earliest) / span_h  # 计算平均时增速
                        lines.append(f"      时速: {hourly:.1f}/h")

        lines.append("")
        lines.append("请用中文简洁回答。")
        return "\n".join(lines)

    def ask(self, question: str) -> str:
        """向 AI 提问并获取回答。

        这是与 AI 交互的主入口方法。处理流程：
        1. 将用户问题添加至对话历史
        2. 尝试从配置加载 API Key（如果尚未设置）
        3. 根据是否有 API Key 选择 LLM 模式或规则模式
        4. 将回答添加至对话历史
        5. 维护对话历史不超过 20 条（滚动窗口）

        如果有 API key，使用 LLM API；
        否则使用内置规则回答。

        Args:
            question: 用户提问的问题文本

        Returns:
            str: AI 或规则生成的回答文本

        Example:
            >>> session = AIQASession()
            >>> session.set_context(videos)
            >>> answer = session.ask("哪个视频增长最快？")
            >>> print(answer)
            增长最快：Python教程 (时速 150/h，当前 12,500)
        """
        self.history.append({"role": "user", "content": question})

        if not self.api_key:
            # 尝试从配置读取（可能是首次调用或之前未加载成功）
            try:
                from config import get_active_ai_profile

                profile = get_active_ai_profile()
                self.api_key = profile.get("api_key", "")
                self.endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
                self.model = profile.get("model", "gpt-4o-mini")
            except Exception as e:
                logger.debug("从配置加载 API 密钥失败: %s", e)

        if self.api_key:
            self._rate_limit()  # API 限速控制
            answer = self._ask_llm(question)
        else:
            answer = self._ask_rule(question)

        self.history.append({"role": "assistant", "content": answer})
        # 维护对话历史窗口：最多保留最近 20 条
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return answer

    def _rate_limit(self):
        """Token Bucket 简单限速：确保 API 调用间隔不低于设定的最小间隔。

        当前设置：每秒最多 1 次 API 调用。
        如果上次调用距今不足 1 秒，则 sleep 等待至足够间隔。
        """
        import time

        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_call_interval:
            time.sleep(self._min_call_interval - elapsed)
        self._last_call_time = time.time()

    def clear_api_key(self):
        """使用后清除内存中的 API Key（安全最佳实践）。

        当会话结束或用户手动退出时调用，防止 API Key 在内存中残留过久。
        """
        self.api_key = ""
        self.model = ""
        self.endpoint = ""

    def _ask_llm(self, question: str) -> str:
        """调用 LLM API 生成回答。

        支持两种 API 协议：
        1. OpenAI 兼容格式：Authorization Bearer token + Chat Completions API
        2. Claude Messages API：x-api-key header + Messages API（通过 endpoint URL 中是否包含 "anthropic.com" 判断）

        API 调用失败时自动降级到规则模式。

        Args:
            question: 用户问题

        Returns:
            str: LLM 生成的回答或降级后的规则回答
        """
        try:
            import requests

            # 构建系统消息（包含监控数据上下文）
            system_msg = self.build_context()
            messages = [
                {"role": "system", "content": system_msg},
            ]
            # 加入最近 10 条对话历史作为上下文
            for h in self.history[-10:]:
                messages.append(h)

            # 根据 endpoint 判断是 Claude 还是 OpenAI 格式
            is_claude = "anthropic.com" in self.endpoint

            if is_claude:
                # ── Claude Messages API 格式 ──
                claude_messages = []
                for m in messages:
                    if m["role"] == "system":
                        continue  # Claude 使用单独的 system 参数而非 message 中的 system role
                    claude_messages.append({"role": m["role"], "content": m["content"]})

                resp = requests.post(
                    self.endpoint,
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",  # 指定 API 版本以确保兼容性
                    },
                    json={
                        "model": self.model,
                        "system": system_msg,  # Claude 的 system prompt 放在顶层字段
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
                    return self._ask_rule(question)  # API 失败降级到规则
            else:
                # ── OpenAI 兼容格式 ──
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
                    return self._ask_rule(question)  # API 失败降级到规则
        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")
            return self._ask_rule(question)

    def _ask_rule(self, question: str) -> str:
        """基于规则的简单问答（无 LLM API 时的降级方案）。

        通过检测问题中的关键词来确定用户意图，并调用对应的回答函数。
        支持的问题类型：
        - "多少" / "视频"     → 监控数量
        - "最快" / "增长"     → 增长最快分析
        - "top" / "排行"      → 播放量排行
        - "达标" / "阈值"     → 阈值达标检测
        - "异常" / "预警"     → 异常检测
        - "健康" / "探针"     → 健康探针

        Args:
            question: 用户问题

        Returns:
            str: 规则生成的回答文本
        """
        q = question.lower()
        videos = self._monitored_videos

        if not videos:
            return (
                "当前未监控任何视频。请先在主界面添加视频到监控列表，"
                "或使用「视频搜索」功能查找并添加视频后，再来向我提问。"
            )

        # 关键词 → 回答函数的映射（按顺序匹配，第一个命中即返回）
        handlers = [
            (["多少", "视频"], lambda: f"当前共监控 {len(videos)} 个视频。"),
            (["最快", "增长", "增速"], self._answer_fastest_growth),
            (["top", "top3", "排行", "最多"], self._answer_top_views),
            (["达标", "完成", "阈值"], self._answer_threshold),
            (["异常", "预警"], self._answer_anomaly),
            (["健康", "探针"], self._answer_health),
        ]
        for keywords, handler in handlers:
            # 只要问题中包含任意一个关键词即命中
            if any(kw in q for kw in keywords):
                return handler()

        # 未命中任何关键词时返回默认提示
        return (
            f"我是监控助手，当前共监控 {len(videos)} 个视频。"
            f"你可以问我：当前监控多少视频？哪个增长最快？播放量排行？"
            f"有无异常预警？健康探针情况？"
        )

    def _answer_anomaly(self) -> str:
        """回答异常预警相关问题。

        通过 AnomalyDetector 对每个视频的最近 10 条记录做异常检测，
        汇总所有发现异常的视频。

        Returns:
            str: 异常预警汇总报告
        """
        from core.smart_alert import AnomalyDetector

        alert_count = 0
        details = []
        for v in self._monitored_videos:
            bvid = v.get("bvid", "")
            if bvid in self._video_dbs:
                try:
                    records = self._video_dbs[bvid].get_all_records(limit=10)  # 取最近 10 条
                    alerts = AnomalyDetector.detect_all(records, bvid=bvid)
                    if alerts:
                        alert_count += len(alerts)
                        details.extend(alerts[:2])  # 每个视频最多取 2 条异常
                except Exception as e:
                    logger.debug("生成 AI 预警报告失败: %s", e)
        if alert_count > 0:
            return f"发现 {alert_count} 条异常预警：\n" + "\n".join(details[:5])
        return "当前无异常预警。"

    def _answer_fastest_growth(self) -> str:
        """回答增长最快的问题。

        遍历所有视频的历史数据，计算平均时增速（播放量增长 / 时间跨度），
        返回增速最高的视频信息。

        Returns:
            str: 增长最快的视频信息
        """
        videos = self._monitored_videos
        if not videos:
            return "暂无监控视频。"
        best_v, best_rate = None, -1  # 最佳视频和最高增速
        for v in videos:
            bvid = v.get("bvid", "")
            if bvid in self._history_data:
                pts = self._history_data[bvid]
                if len(pts) >= 2:
                    # 按时间排序（兼容 datetime 和 str 两种格式）
                    try:
                        sorted_pts = sorted(
                            pts,
                            key=lambda p: (
                                p[0]
                                if isinstance(p[0], datetime)
                                else (
                                    datetime.fromisoformat(str(p[0])[:19])
                                    if isinstance(p[0], str)
                                    else p[0]
                                )
                            ),
                        )
                    except Exception:
                        sorted_pts = pts
                    ts_to_dt2 = lambda t: t if isinstance(t, datetime) else datetime.fromtimestamp(t)
                    span = (ts_to_dt2(sorted_pts[-1][0]) - ts_to_dt2(sorted_pts[0][0])).total_seconds()
                    if span > 0:
                        growth = sorted_pts[-1][1] - sorted_pts[0][1]  # 总增长量
                        rate = growth / span * 3600  # 换算为时速（播放量/小时）
                        if rate > best_rate:
                            best_rate = rate
                            best_v = v
        if best_v:
            return (
                f"增长最快：{best_v.get('title', '')[:20]} "
                f"(时速 {best_rate:.0f}/h，"
                f"当前 {best_v.get('view_count', 0):,})"
            )
        return "暂无足够数据计算增速。"

    def _answer_top_views(self) -> str:
        """回答播放量排行问题。

        按播放量降序排列视频，返回 Top 5 排行。

        Returns:
            str: 播放量排行 Top 5 列表
        """
        sorted_v = sorted(self._monitored_videos, key=lambda v: v.get("view_count", 0), reverse=True)
        if not sorted_v:
            return "暂无监控视频。"
        lines = ["播放量排行："]
        for i, v in enumerate(sorted_v[:5], 1):
            lines.append(f"  {i}. {v.get('title', '')[:20]} — {v.get('view_count', 0):,}")
        return "\n".join(lines)

    def _answer_threshold(self) -> str:
        """回答阈值达标相关问题。

        从配置文件读取阈值列表（如 10万/100万/1000万），
        检查每个视频的播放量是否达到或接近某阈值。

        Returns:
            str: 阈值达标状态报告
        """
        from config import load_config

        cfg = load_config().get("prediction", {})
        thresholds_raw = cfg.get("thresholds", [[100000, "10万"], [1000000, "100万"], [10000000, "1000万"]])
        thresholds = [t for t, _ in thresholds_raw]  # 提取阈值数值
        threshold_names = [n for _, n in thresholds_raw]  # 提取阈值名称

        achieved = 0
        nearing = []  # 接近达标（>= 80%）的视频
        for v in self._monitored_videos:
            views = v.get("view_count", 0)
            for t, name in zip(thresholds, threshold_names):
                if views >= t:
                    achieved += 1  # 已达标的阈值计数
                elif views >= t * 0.8:  # 播放量达到阈值的 80% 视为"即将达标"
                    nearing.append(f"{v.get('title', '')[:20]} 距{name}还差{t - views:,}")

        result = f"已达标 {achieved} 个阈值。"
        if nearing:
            result += "\n即将达标：\n" + "\n".join(nearing[:5])
        return result

    def _answer_health(self) -> str:
        """回答健康探针相关问题。

        对每个监控视频调用 calculate_probe_from_dict 计算健康分，
        返回 Top 5 视频的健康分和评级。

        Returns:
            str: 健康探针报告
        """
        try:
            from utils.interaction_quality import calculate_probe_from_dict

            results = []
            for v in self._monitored_videos[:5]:  # 最多展示 5 个视频
                r = calculate_probe_from_dict(v)
                results.append(f"{v.get('title', '')[:16]}: {r.health_score:.0f}分({r.health_grade})")
            if results:
                return "健康探针：\n" + "\n".join(results)
            return "暂无数据。"
        except Exception:
            return "健康探针暂时不可用。"
