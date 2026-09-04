"""
通知模块 - 支持Windows原生通知和QQ Bot推送
OneBot 调用策略：主力 WebSocket → 回退 HTTP
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
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
        self.webhooks: list = []  # [{name, url, type}]
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)  # 防止单工作线程死锁（WS 调用可重入）

    def configure(self, config: Dict[str, Any]):
        """从 settings.json 的嵌套结构加载 OneBot / Webhook 配置"""
        ob_cfg = config.get("onebot", {})
        self.onebot_http = ob_cfg.get("http_url", self.onebot_http)
        self.onebot_ws = ob_cfg.get("ws_url", self.onebot_ws)
        self.token = ob_cfg.get("access_token", "")
        self.enabled = ob_cfg.get("enabled", True)
        self.qq_private = str(ob_cfg.get("private_qq", ""))
        self.qq_group = str(ob_cfg.get("group_qq", ""))
        notif_cfg = config.get("notification", {})
        self.webhooks = [w for w in notif_cfg.get("webhooks", []) if isinstance(w, dict) and w.get("url")]

    # ── OneBot 底层调用（WS → HTTP） ──────────────────────

    def _run_async_safe(self, coro):
        """安全运行协程，兼容已有事件循环的线程"""
        try:
            asyncio.get_running_loop()
            if self._executor is None:
                return asyncio.run(coro)
            return self._executor.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    def _submit(self, fn, *args, **kwargs):
        """向线程池投递任务；executor 已关闭(应用退出中)时静默丢弃。"""
        executor = self._executor
        if executor is None:
            return None
        try:
            return executor.submit(fn, *args, **kwargs)
        except RuntimeError:
            logger.debug("通知线程池已关闭,丢弃投递: %s", getattr(fn, "__name__", "task"))
            return None

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
            except json.JSONDecodeError as e:
                logger.warning("WS %s 返回无效 JSON: %s", action, e)
                return False  # 不触发回退——数据格式错误不会因 HTTP 改善
            except Exception as e:
                logger.exception("WS %s 异常", action)
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

    # ── Webhook 通知 ──────────────────────────────

    @staticmethod
    def _redact_url(url: str) -> str:
        """日志脱敏: 仅保留 scheme://host[:port]，去除 query/fragment（可能含密钥）。"""
        try:
            from urllib.parse import urlsplit

            p = urlsplit(url)
            host = p.hostname or ""
            port = f":{p.port}" if p.port else ""
            return f"{p.scheme}://{host}{port}"
        except Exception:
            return "<webhook>"

    @staticmethod
    def _check_webhook_url(url: str) -> str | None:
        """Webhook URL 安全校验。

        返回 None=通过; 否则返回拒绝原因。阻止 SSRF:
        - scheme 仅允许 http/https
        - 禁止指向回环/私网/链路本地/云元数据地址(169.254.169.254)
        """
        from urllib.parse import urlsplit
        import ipaddress
        import socket

        try:
            p = urlsplit(url)
            if p.scheme not in ("http", "https"):
                return f"仅支持 http/https, 当前: {p.scheme or '(空)'}"
            host = p.hostname
            if not host:
                return "URL 缺少主机名"
            # 先尝试按 IP 字面量判断
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                try:
                    ip = ipaddress.ip_address(socket.gethostbyname(host))
                except Exception:
                    return None  # DNS 解析失败交由请求超时兜底, 不阻塞用户
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
                return f"不允许指向内网/回环地址: {host}"
            return None
        except Exception as e:
            logger.debug("Webhook URL 校验异常: %s", e)
            return None

    @staticmethod
    def _build_webhook_payload(wh_type: str, text: str) -> dict:
        """按渠道类型构造 POST JSON payload。text 为纯文本消息内容。"""
        t = (wh_type or "generic").lower()
        if t == "wecom":  # 企业微信机器人
            return {"msgtype": "text", "text": {"content": text}}
        if t == "dingtalk":  # 钉钉机器人
            return {"msgtype": "text", "text": {"content": text}}
        if t == "slack":  # Slack Incoming Webhook
            return {"text": text}
        if t == "discord":  # Discord Webhook
            return {"content": text[:1900]}
        return {"text": text}  # generic: 简单 {"text": ...}

    def _post_webhook(self, wh: dict, text: str) -> bool:
        """发送单个 webhook（阻塞调用，供线程池执行）"""
        url = wh.get("url", "")
        if not url:
            return False
        label = wh.get("name") or self._redact_url(url)
        reject = self._check_webhook_url(url)
        if reject:
            logger.warning("Webhook %s 已拦截: %s", label, reject)
            return False
        payload = self._build_webhook_payload(wh.get("type", ""), text)
        try:
            resp = requests.post(url, json=payload, timeout=8, allow_redirects=False)
            ok = resp.status_code in (200, 201, 204)
            if not ok:
                logger.warning("Webhook %s 返回 %d: %s", label, resp.status_code, resp.text[:160])
            return ok
        except requests.RequestException as e:
            logger.error("Webhook %s 发送失败: %s", label, e)
            return False

    def send_webhook(self, message: str) -> bool:
        """向所有已配置的 Webhook 异步推送消息（不阻塞调用线程）。

        返回是否至少有一个渠道被投递（异步排队成功即视为投递）。
        """
        if not self.webhooks or not message:
            return False
        sent_any = False
        for wh in self.webhooks:
            if self._submit(self._post_webhook, wh, message) is None:
                return sent_any
            sent_any = True
        return sent_any

    def test_webhook(self, wh: dict) -> Dict[str, Any]:
        """同步测试单个 Webhook 配置（供设置界面「测试」按钮使用）"""
        url = wh.get("url", "")
        if not url:
            return {"ok": False, "error": "URL 为空"}
        label = wh.get("name") or self._redact_url(url)
        reject = self._check_webhook_url(url)
        if reject:
            return {"ok": False, "error": reject}
        payload = self._build_webhook_payload(wh.get("type", ""), "♪ B站监控 Webhook 测试连通性 (天依的试音) ")
        try:
            resp = requests.post(url, json=payload, timeout=8, allow_redirects=False)
            ok = resp.status_code in (200, 201, 204)
            if ok:
                return {"ok": True, "channel": label, "version": str(resp.status_code)}
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)}

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

        return self._submit(_send) is not None

    def send_qq_group(self, message: str) -> bool:
        """发送QQ群消息（异步，不阻塞主线程）"""
        if not self.qq_group or not self.enabled:
            return False

        def _send():
            self._call_action("send_group_msg", {"group_id": self.qq_group, "message": message})

        return self._submit(_send) is not None

    def send_threshold_notification(self, bvid: str, title: str, threshold: int, current_views: int):
        """发送阈值突破通知（Windows + QQ + Webhook 全渠道）"""
        message = (
            f"追上光啦!♪ 视频《{title}》播放量突破{threshold / 10000:.0f}万！\n"
            f"当前播放量: {current_views}\nBV号: {bvid}"
        )

        # Windows通知
        self.send_windows_notification("♪ 播放量突破提醒", message)

        # QQ通知
        qq_msg = f"♪ 播放量突破提醒\n{message}"
        self.send_qq_private(qq_msg)
        self.send_qq_group(qq_msg)

        # Webhook 通知
        self.send_webhook(f"♪ 播放量突破提醒\n{message}")

    # ── 连通性检查 ──────────────────────────────

    def test_connection(self, http_url: str = "", ws_url: str = "", token: str = "") -> Dict[str, Any]:
        """测试 OneBot 服务连通性，返回 {'ok': bool, 'channel': str, 'version': str, 'error': str}

        先试 WS（主力），失败再试 HTTP（保底）。
        支持传入测试参数覆盖（不修改实例状态，避免与真实发送竞争）。
        """
        http_url = http_url or self.onebot_http
        ws_url = ws_url or self.onebot_ws
        token = token if token is not None else self.token
        result: Dict[str, Any] = {"ok": False, "channel": "", "version": "", "error": ""}

        # 1) 尝试 WS
        if _HAS_WS and ws_url:
            ws_ok = self._test_connection_ws(result, ws_url=ws_url, token=token)
            if ws_ok:
                return result

        # 2) 尝试 HTTP
        if http_url:
            self._test_connection_http(result, http_url=http_url, token=token)

        return result

    def _test_connection_ws(self, result: dict, ws_url: str = "", token: str = "") -> bool:
        """WS 连通性检测（使用传入参数,不读实例状态）"""
        uri = ws_url or self.onebot_ws
        token = token if token is not None else self.token
        extra_headers = {}
        if token:
            if uri.startswith("ws://"):
                result["error"] = "有 token 但 WS 是明文，跳过"
                return False
            extra_headers["Authorization"] = f"Bearer {token}"

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

    def _test_connection_http(self, result: dict, http_url: str = "", token: str = "") -> bool:
        """HTTP 连通性检测（使用传入参数,不读实例状态）"""
        http_url = http_url or self.onebot_http
        token = token if token is not None else self.token
        try:
            url = f"{http_url}/get_version_info"
            headers = {}
            if token:
                if http_url.startswith("http://"):
                    result["error"] = "有 token 但 HTTP 是明文，拒绝请求"
                    return False
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                result["ok"] = True
                result["channel"] = "HTTP"
                d = data.get("data", {})
                result["version"] = d.get("app_version", d.get("version", str(d)))
                return True
            elif resp.status_code == 401:
                result["error"] = "鉴权失败（HTTP 401），请检查 access_token 是否匹配"
            else:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.ConnectionError:
            result["error"] = f"HTTP 无法连接 {http_url}"
        except Exception as e:
            result["error"] = f"HTTP 异常: {e}"
        return False

    def shutdown(self):
        """关闭线程池，释放资源（应用退出时调用）。

        wait=False: 不等待已排队 POST 的 8s 超时,避免退出卡顿;
        守护线程随进程结束,残留请求自然终止。
        """
        executor = self._executor
        self._executor = None
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.debug("通知线程池关闭异常: %s", e)


# 全局通知管理器实例
notification_manager = NotificationManager()
