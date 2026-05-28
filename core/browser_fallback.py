"""
无头浏览器兜底模块
当所有 API 方式均被 412 限流时，使用 Playwright 无头浏览器模拟真实用户访问
"""

import logging
import time
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

_HAS_PLAYWRIGHT = False
try:
    import playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    pass


def _parse_bilibili_page(html: str, bvid: str) -> Optional[Dict]:
    """从 B站视频页面 HTML 中解析视频信息"""
    import re
    import json as _json

    result = {"bvid": bvid, "title": "", "view_count": 0, "like_count": 0,
              "coin_count": 0, "favorite_count": 0, "share_count": 0,
              "danmaku_count": 0, "reply_count": 0, "_source": "playwright"}

    # 尝试从 window.__INITIAL_STATE__ 提取
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
    """使用 Playwright 无头浏览器获取视频信息（最终兜底方案）"""
    if not _HAS_PLAYWRIGHT:
        logger.debug("Playwright 未安装，跳过浏览器兜底 (pip install playwright)")
        return None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
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
