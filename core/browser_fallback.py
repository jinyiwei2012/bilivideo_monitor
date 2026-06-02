"""
无头浏览器兜底模块 (Browser Fallback)
======================================

当所有 API 方式（自有 API / bilibili-api-python / curl_cffi）均被 B站 412 限流时，
使用 Playwright 无头浏览器模拟真实用户访问作为最终兜底方案。

工作原理：
  1. 启动 Chromium 无头浏览器（带反检测参数）
  2. 访问 https://www.bilibili.com/video/{bvid}
  3. 等待页面渲染完成（domcontentloaded + 3s 额外等待）
  4. 从 HTML 中提取 window.__INITIAL_STATE__ JSON 数据
  5. 解析视频信息的标题和统计数据

前置条件：
  - 安装 Playwright：  pip install playwright
  - 安装 Chromium：    python -m playwright install chromium

注意事项：
  - 此模块作为最后兜底，性能开销较大（启动浏览器需要数秒）
  - 仅在正常 API 全部失败时才调用
  - 每次使用后立即关闭浏览器，避免资源泄漏
"""
import logging
import time
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# 检测 Playwright 是否可用
_HAS_PLAYWRIGHT = False
try:
    import playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    pass


def _parse_bilibili_page(html: str, bvid: str) -> Optional[Dict]:
    """从 B站 视频页面 HTML 中解析视频信息

    B站 视频页面在 <script> 标签中内嵌了一个 __INITIAL_STATE__ 全局变量，
    包含视频的完整信息（标题、统计数据等）。本函数用正则提取并解析这个 JSON。

    Args:
        html: 完整的页面 HTML 源码
        bvid: 视频 BV 号（用于回填结果）

    Returns:
        视频信息字典，包含 bvid, title, view_count, like_count,
        coin_count, favorite_count, share_count, danmaku_count, reply_count
        以及 _source 标记（值为 "playwright"）
    """
    import re
    import json as _json

    result = {"bvid": bvid, "title": "", "view_count": 0, "like_count": 0,
              "coin_count": 0, "favorite_count": 0, "share_count": 0,
              "danmaku_count": 0, "reply_count": 0, "_source": "playwright"}

    # 用正则提取 window.__INITIAL_STATE__ = {...}; 中的 JSON 对象
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
    if m:
        try:
            state = _json.loads(m.group(1))
            video_data = state.get("videoData", state.get("videoInfo", {}))
            if video_data:
                stat = video_data.get("stat", {})
                result["title"] = video_data.get("title", "")
                result["view_count"] = stat.get("view", 0)
                result["like_count"] = stat.get("like", 0)
                result["coin_count"] = stat.get("coin", 0)
                result["favorite_count"] = stat.get("favorite", 0)
                result["share_count"] = stat.get("share", 0)
                result["danmaku_count"] = stat.get("danmaku", 0)
                result["reply_count"] = stat.get("reply", 0)
                return result
        except _json.JSONDecodeError:
            pass
    return None


def fetch_video_info_playwright(bvid: str) -> Optional[Dict]:
    """使用 Playwright 无头浏览器获取视频信息（最终兜底方案）

    这是数据获取的最后一道防线——启动真实的 Chromium 浏览器，
    模拟正常用户访问 B站 视频页面，从渲染后的 HTML 中提取数据。

    浏览器启动参数：
      - --disable-blink-features=AutomationControlled  （隐藏自动化标识）
      - --disable-dev-shm-usage                          （避免 /dev/shm 不足）
      - --no-sandbox                                     （Docker 兼容）

    Args:
        bvid: 视频 BV 号

    Returns:
        视频信息字典，包含 view_count, like_count 等核心字段。
        如果 Playwright 未安装、解析失败或网络异常，返回 None。
    """
    if not _HAS_PLAYWRIGHT:
        logger.debug("Playwright 未安装，跳过浏览器兜底 (pip install playwright)")
        return None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # 启动 Chromium 无头浏览器，禁用自动化检测特征
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            # 创建浏览器上下文（隔离的会话环境）
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = context.new_page()
            url = f"https://www.bilibili.com/video/{bvid}"
            logger.info("Playwright 正在访问 %s", url)

            # 等待 DOM 加载完成后额外等待 3 秒，确保 JS 渲染完毕
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            html = page.content()
            browser.close()

        result = _parse_bilibili_page(html, bvid)
        if result and result["view_count"] > 0:
            logger.info("Playwright 成功获取 %s 数据", bvid)
            return result

        logger.debug("Playwright 获取 %s 失败: 未解析到有效数据", bvid)
        return None

    except Exception as e:
        logger.debug("Playwright 获取 %s 异常: %s", bvid, e)
        return None
