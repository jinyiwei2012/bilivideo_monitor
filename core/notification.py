"""
通知模块 (NotificationManager)
==============================

本模块负责所有通知功能，支持两种通知渠道：

  1. Windows 原生通知     — 通过 plyer 库调用 Windows Toast 通知
  2. QQ Bot 推送          — 通过 OneBot 协议推送消息（QQ 私聊 + 群聊）

OneBot 调用策略：主力 WebSocket → 回退 HTTP

为什么使用双通道：
  - WebSocket (WS): 主力通道，实时性好，开销低
  - HTTP: 保底通道，兼容所有 OneBot 实现（包括 LAGRANGE、LLOneBot 等）

安全策略：
  - 如果设置了 access_token，明文连接（ws:// 或 http://）会拒绝发送
  - 敏感操作中的 token 会被自动脱敏处理
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
    """通知管理器

    集中管理所有通知的发送，支持：
      - Windows Toast 通知（桌面弹窗）
      - QQ 私聊消息（通过 OneBot WS/HTTP）
      - QQ 群消息（通过 OneBot WS/HTTP）
      - 阈值突破通知（播放量达到预设目标时的组合通知）
      - OneBot 连通性检测
    """

    def __init__(self):
        """初始化通知管理器，设置默认 OneBot 连接参数

        默认连接：
          - HTTP: http://127.0.0.1:5700
          - WS:   ws://127.0.0.1:6700
        """
        self.onebot_http = "http://127.0.0.1:5700"
        self.onebot_ws = "ws://127.0.0.1:6700"
        self.token = ""
        self.enabled = True
        self.qq_private = ""
        self.qq_group = ""
        # 单线程执行器，用于在有事件循环的线程中运行异步协程
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def configure(self, config: Dict[str, Any]):
        """从 settings.json 的嵌套结构中加载 OneBot 配置

        Args:
            config: 完整的应用配置字典，onebot 配置位于 config["onebot"]
        """
        ob_cfg = config.get("onebot", {})
        self.onebot_http = ob_cfg.get("http_url", self.onebot_http)
        self.onebot_ws = ob_cfg.get("ws_url", self.onebot_ws)
        self.token = ob_cfg.get("access_token", "")
        self.enabled = ob_cfg.get("enabled", True)
        self.qq_private = str(ob_cfg.get("private_qq", ""))
        self.qq_group = str(ob_cfg.get("group_qq", ""))

    # ── OneBot 底层调用（WS → HTTP） ──────────────────────

    def _run_async_safe(self, coro):
        """安全运行协程，兼容已有事件循环的线程

        Tkinter GUI 线程通常没有运行中的事件循环，可以直接用 asyncio.run()。
        但如果线程中已有事件循环（如某些测试环境），则通过 executor 在新线程中运行。

        Args:
            coro: 需要执行的协程对象

        Returns:
            协程的返回值
        """
        try:
            asyncio.get_running_loop()
            # 当前线程已有事件循环，通过 executor 在新线程中运行
            return self._executor.submit(asyncio.run, coro).result()
        except RuntimeError:
            # 当前线程没有事件循环，直接运行
            return asyncio.run(coro)

    def _call_action_ws(self, action: str, params: dict, timeout: float = 5) -> bool | None:
        """通过 WebSocket 调用 OneBot 动作（主力通道）

        先尝试 WS 通道，WS 失败时返回 None 触发 HTTP 回退。

        Args:
            action: OneBot 动作名称（如 "send_private_msg"）
            params: 动作参数（如 {"user_id": "xxx", "message": "yyy"}）
            timeout: 连接和读取超时（秒）

        Returns:
            True=WS调用成功, False=WS调用失败(不回退), None=需要回退到HTTP
        """
        if not _HAS_WS or not self.onebot_ws:
            return None

        uri = self.onebot_ws
        extra_headers = {}

        # 安全检查：如果设置了 token 但使用明文 WS，拒绝发送
        if self.token:
            if uri.startswith("ws://"):
                logger.warning("有 token 但 WS 是明文连接，跳过 WS 通道")
                return None
            extra_headers["Authorization"] = f"Bearer {self.token}"

        async def _call():
            try:
                # 建立 WebSocket 连接
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
                return None  # 触发 HTTP 回退
            except Exception as e:
                logger.warning("WS %s 未知异常: %s", action, e)
                return None

        return self._run_async_safe(_call())

    def _call_action_http(self, action: str, params: dict, timeout: float = 5) -> bool:
        """通过 HTTP API 调用 OneBot 动作（保底通道）

        当 WS 不可用时，回退到 HTTP 方式发送消息。
        OneBot HTTP 标准：POST /{action}，请求体为 JSON，响应 {"status": "ok"...}

        Args:
            action: OneBot 动作名称
            params: 动作参数字典
            timeout: 请求超时（秒）

        Returns:
            True=HTTP调用成功, False=失败
        """
        if not self.onebot_http:
            return False

        url = f"{self.onebot_http}/{action}"
        headers = {}
        if self.token:
            # 安全检查：明文 HTTP + token 拒绝发送
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
        """先 WS 后 HTTP 的 OneBot 动作调用策略（主力 → 保底）

        三层返回值：
          True  — WS 成功
          False — WS 失败且不触发回退
          None  — WS 不可用，已回退到 HTTP

        Args:
            action: OneBot 动作名称
            params: 动作参数字典

        Returns:
            True=通信成功, False=通信失败
        """
        r = self._call_action_ws(action, params)
        if r is True:
            return True
        if r is None:
            return self._call_action_http(action, params)
        return False

    # ── 通知发送 ────────────────────────────────

    def send_windows_notification(self, title: str, message: str) -> bool:
        """发送 Windows 原生通知（自动截断以规避 plyer 256 字符限制）

        plyer 的 Windows 后端有一个 256 字符的标题+消息总缓冲区。
        超过此限制会导致通知发送失败（不报错、无提示）。

        本方法会在发送前自动截断消息，确保不超过缓冲区大小。

        Args:
            title: 通知标题
            message: 通知内容

        Returns:
            True=通知发送成功, False=发送失败
        """
        try:
            from plyer import notification

            # plyer Windows 后端有 256 字符总缓冲区限制，提前截断
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
        """发送 QQ 私聊消息（异步，不阻塞主线程）

        消息通过线程池异步发送，调用不会等待发送完成即返回。
        需要在设置中配置 private_qq 参数。

        Args:
            message: 消息内容（支持纯文本和 CQ 码）

        Returns:
            True=消息已提交到发送队列
        """
        if not self.qq_private or not self.enabled:
            return False

        def _send():
            self._call_action("send_private_msg", {"user_id": self.qq_private, "message": message})

        self._executor.submit(_send)
        return True

    def send_qq_group(self, message: str) -> bool:
        """发送 QQ 群消息（异步，不阻塞主线程）

        消息通过线程池异步发送，调用不会等待发送完成即返回。
        需要在设置中配置 group_qq 参数。

        Args:
            message: 消息内容（支持纯文本和 CQ 码）

        Returns:
            True=消息已提交到发送队列
        """
        if not self.qq_group or not self.enabled:
            return False

        def _send():
            self._call_action("send_group_msg", {"group_id": self.qq_group, "message": message})

        self._executor.submit(_send)
        return True

    def send_threshold_notification(self, bvid: str, title: str, threshold: int, current_views: int):
        """发送阈值突破通知（同时发送 Windows 通知和 QQ 通知）

        当视频播放量达到或超过用户预设的阈值时触发。
        同时向以下渠道发送通知：
          - Windows Toast 桌面弹窗
          - QQ 私聊消息
          - QQ 群消息

        Args:
            bvid: 视频 BV 号
            title: 视频标题
            threshold: 阈值播放量
            current_views: 当前播放量
        """
        message = f"视频《{title}》播放量突破{threshold / 10000:.0f}万！\n当前播放量: {current_views}\nBV号: {bvid}"

        # Windows 通知
        self.send_windows_notification("播放量突破提醒", message)

        # QQ 通知（私聊 + 群聊）
        qq_msg = f"🎉 播放量突破提醒\n{message}"
        self.send_qq_private(qq_msg)
        self.send_qq_group(qq_msg)

    # ── 连通性检查 ──────────────────────────────

    def test_connection(self) -> Dict[str, Any]:
        """测试 OneBot 服务连通性

        检测顺序：先 WS（主力）→ 再 HTTP（保底）。
        成功时返回 OneBot 服务的版本信息。

        Returns:
            包含以下字段的字典：
              - ok: 是否连接成功
              - channel: 通信通道（"WebSocket" 或 "HTTP"）
              - version: OneBot 服务版本号
              - error: 错误信息（连接失败时填充）
        """
        result: Dict[str, Any] = {"ok": False, "channel": "", "version": "", "error": ""}

        # 1) 尝试 WS 连通性检测
        if _HAS_WS and self.onebot_ws:
            ws_ok = self._test_connection_ws(result)
            if ws_ok:
                return result

        # 2) 回退 HTTP 连通性检测
        if self.onebot_http:
            self._test_connection_http(result)

        return result

    def _test_connection_ws(self, result: dict) -> bool:
        """WS 连通性检测

        通过 get_version_info 动作检测 OneBot WS 服务是否正常运行。

        Args:
            result: 用于填充检测结果的字典（原地修改）

        Returns:
            True=WS 连接正常, False=连接失败
        """
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
        """HTTP 连通性检测

        通过 GET /get_version_info 检测 OneBot HTTP 服务是否正常运行。
        401 返回时提供明确的鉴权失败提示。

        Args:
            result: 用于填充检测结果的字典（原地修改）
        """
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

    def shutdown(self):
        """关闭线程池，释放资源（应用退出时调用）

        等待所有已提交的任务完成后再关闭线程池，
        确保最后一条消息能被成功发送。
        """
        self._executor.shutdown(wait=True)
        self._executor = None


# 全局通知管理器实例（单例模式）
notification_manager = NotificationManager()
