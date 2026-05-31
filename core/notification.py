"""
通知模块 - 支持Windows原生通知和QQ Bot推送
OneBot 调用策略：主力 WebSocket → 回退 HTTP
"""

import asyncio
import concurrent.futures
import json
import logging
import threading
from typing import Dict, Any
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)

# websockets 库（异步，用于 WS 主力通道）
try:
    import websockets

    _HAS_WS = True
except ImportError:
    _HAS_WS = False
    logger.warning("websockets 未安装，OneBot WS 通道不可用，仅使用 HTTP 回退")


class NotificationManager:
    """通知管理器"""

    def __init__(self):
        """初始化通知管理器，设置默认 OneBot 连接参数"""
        self.onebot_http = "http://127.0.0.1:5700"
        self.onebot_ws = "ws://127.0.0.1:6700"
        self.token = ""
        self.enabled = True
        self.qq_private = ""
        self.qq_group = ""
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def configure(self, config: Dict[str, Any]):
        """从 settings.json 的嵌套结构加载 OneBot 配置"""
        ob_cfg = config.get("onebot", {})
        self.onebot_http = ob_cfg.get("http_url", self.onebot_http)
        self.onebot_ws = ob_cfg.get("ws_url", self.onebot_ws)
        self.token = ob_cfg.get("access_token", "")
        self.enabled = ob_cfg.get("enabled", True)
        self.qq_private = str(ob_cfg.get("private_qq", ""))
        self.qq_group = str(ob_cfg.get("group_qq", ""))

    # ── OneBot 底层调用（WS → HTTP） ──────────────────────

    def _run_async_safe(self, coro):
        """安全运行协程，兼容已有事件循环的线程"""
        try:
            asyncio.get_running_loop()
            return self._executor.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    def _call_action_ws(self, action: str, params: dict, timeout: float = 5) -> bool | None:
        """通过 WebSocket 调用 OneBot 动作（主力通道）

        返回 True=成功, False=失败(不回退), None=需要回退到 HTTP
        """
        if not _HAS_WS or not self.onebot_ws:
            return None

        uri = self.onebot_ws
        extra_headers = {}

        if self.token:
            if uri.startswith("ws://"):
                logger.warning("有 token 但 WS 是明文连接，跳过 WS 通道")
                return None
            extra_headers["Authorization"] = f"Bearer {self.token}"

        async def _call():
            try:
                async with websockets.connect(
                    uri, additional_headers=extra_headers, open_timeout=timeout, close_timeout=3
                ) as ws:
                    payload = {"action": action, "params": params, "echo": str(uuid4())}
                    await ws.send(json.dumps(payload))
                    resp = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    data = json.loads(resp)
                    if data.get("status") == "ok":
                        return True
                    logger.warning("WS action %s 返回非 ok: %s", action, data.get("message", ""))
                    return False
            except (asyncio.TimeoutError, websockets.WebSocketException) as e:
                logger.info("WS %s 不可用 (%s)，准备回退 HTTP", action, e)
                return None  # 触发回退
            except Exception as e:
                logger.warning("WS %s 未知异常: %s", action, e)
                return None

        return self._run_async_safe(_call())

    def _call_action_http(self, action: str, params: dict, timeout: float = 5) -> bool:
        """通过 HTTP API 调用 OneBot 动作（保底通道）"""
        if not self.onebot_http:
            return False

        url = f"{self.onebot_http}/{action}"
        headers = {}
        if self.token:
            if self.onebot_http.startswith("http://"):
                logger.error("有 token 但 HTTP 是明文传输，拒绝发送")
                return False
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = requests.post(url, json=params, headers=headers, timeout=timeout)
            ok = resp.status_code == 200
            if not ok:
                logger.warning("HTTP %s 返回 %d: %s", action, resp.status_code, resp.text[:120])
            return ok
        except requests.ConnectionError:
            logger.error("HTTP %s 连接失败: %s", action, self.onebot_http)
            return False
        except Exception as e:
            logger.error("HTTP %s 异常: %s", action, e)
            return False

    def _call_action(self, action: str, params: dict) -> bool:
        """先 WS 后 HTTP 的 OneBot 动作调用（主力→保底）"""
        r = self._call_action_ws(action, params)
        if r is True:
            return True
        if r is None:
            return self._call_action_http(action, params)
        return False

    # ── 通知发送 ────────────────────────────────

    def send_windows_notification(self, title: str, message: str) -> bool:
        """发送Windows原生通知（自动截断以规避 plyer 256 字符限制）"""
        try:
            from plyer import notification

            # plyer Windows 后端有 256 字符总缓冲区限制，截断标题+消息
            max_msg = max(0, 220 - len(title))
            if max_msg < 10:
                title = title[:40]
                max_msg = 180
            safe_msg = message if len(message) <= max_msg else message[: max_msg - 3] + "..."
            notification.notify(title=title, message=safe_msg, timeout=10)
            return True
        except Exception as e:
            logger.error(f"Windows通知发送失败: {type(e).__name__}")
            return False

    def send_qq_private(self, message: str) -> bool:
        """发送QQ私聊消息（异步，不阻塞主线程）"""
        if not self.qq_private or not self.enabled:
            return False

        def _send():
            self._call_action("send_private_msg", {"user_id": self.qq_private, "message": message})

        self._executor.submit(_send)
        return True

    def send_qq_group(self, message: str) -> bool:
        """发送QQ群消息（异步，不阻塞主线程）"""
        if not self.qq_group or not self.enabled:
            return False

        def _send():
            self._call_action("send_group_msg", {"group_id": self.qq_group, "message": message})

        self._executor.submit(_send)
        return True

    def send_threshold_notification(self, bvid: str, title: str, threshold: int, current_views: int):
        """发送阈值突破通知（同时发送 Windows 通知和 QQ 通知）"""
        message = f"视频《{title}》播放量突破{threshold / 10000:.0f}万！\n当前播放量: {current_views}\nBV号: {bvid}"

        # Windows通知
        self.send_windows_notification("播放量突破提醒", message)

        # QQ通知
        qq_msg = f"🎉 播放量突破提醒\n{message}"
        self.send_qq_private(qq_msg)
        self.send_qq_group(qq_msg)

    # ── 连通性检查 ──────────────────────────────

    def test_connection(self) -> Dict[str, Any]:
        """测试 OneBot 服务连通性，返回 {'ok': bool, 'channel': str, 'version': str, 'error': str}

        先试 WS（主力），失败再试 HTTP（保底）。
        """
        result: Dict[str, Any] = {"ok": False, "channel": "", "version": "", "error": ""}

        # 1) 尝试 WS
        if _HAS_WS and self.onebot_ws:
            ws_ok = self._test_connection_ws(result)
            if ws_ok:
                return result

        # 2) 尝试 HTTP
        if self.onebot_http:
            self._test_connection_http(result)

        return result

    def _test_connection_ws(self, result: dict) -> bool:
        """WS 连通性检测"""
        uri = self.onebot_ws
        extra_headers = {}
        if self.token:
            if uri.startswith("ws://"):
                result["error"] = "有 token 但 WS 是明文，跳过"
                return False
            extra_headers["Authorization"] = f"Bearer {self.token}"

        async def _check():
            async with websockets.connect(uri, additional_headers=extra_headers, open_timeout=5, close_timeout=3) as ws:
                payload = {"action": "get_version_info", "echo": str(uuid4())}
                await ws.send(json.dumps(payload))
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(resp)
                return data

        try:
            data = self._run_async_safe(_check())
            result["ok"] = True
            result["channel"] = "WebSocket"
            d = data.get("data", {})
            result["version"] = d.get("app_version", d.get("version", str(d)))
            return True
        except ImportError:
            result["error"] = "websockets 库未安装"
            return False
        except Exception as e:
            result["error"] = f"WS 连接失败: {e}"
            return False

    def _test_connection_http(self, result: dict):
        """HTTP 连通性检测"""
        try:
            url = f"{self.onebot_http}/get_version_info"
            headers = {}
            if self.token:
                if self.onebot_http.startswith("http://"):
                    result["error"] = "有 token 但 HTTP 是明文，拒绝请求"
                    return
                headers["Authorization"] = f"Bearer {self.token}"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                result["ok"] = True
                result["channel"] = "HTTP"
                d = data.get("data", {})
                result["version"] = d.get("app_version", d.get("version", str(d)))
            elif resp.status_code == 401:
                result["error"] = "鉴权失败（HTTP 401），请检查 access_token 是否匹配"
            else:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.ConnectionError:
            result["error"] = f"HTTP 无法连接 {self.onebot_http}"
        except Exception as e:
            result["error"] = f"HTTP 异常: {e}"


# 全局通知管理器实例
notification_manager = NotificationManager()
