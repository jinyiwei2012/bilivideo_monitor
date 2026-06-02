"""
B站 API 模块 — HTTP 请求核心 (_RequestMixin)
===============================================

本模块是 B站 API 请求的底层引擎，负责所有 HTTP 通信逻辑。

核心机制：
  1. 请求间隔控制        — 通过高斯随机抖动保证最小请求间隔，避免触发风控
  2. TLS 指纹伪装        — 优先使用 curl_cffi (chrome131 JA3 指纹)，失败回退 requests
  3. 412 错误重试         — 指数退避 + UA 轮换 + 代理切换 + buvid 随机化
  4. 代理绑定             — 每个代理 IP 绑定一个固定 UA，避免 IP-UA 不一致
  5. 双通道               — 主通道 (_request) 带 Cookie，公共通道 (_request_public) 免登录

架构说明 (Mixin 模式)：
  本模块的所有函数均在模块顶层定义（第一个参数为 self），
  通过 _RequestMixin 类属性赋值注入到 BilibiliAPI 中。
  这种设计使得各 Mixin 的代码在物理上分离，但逻辑上统一。

请求流程概览：
  _request(method, url, ...)
    └→ _ensure_min_interval()      # 节流控制
    └→ _prepare_request_kwargs()    # 代理/UA 准备
    └→ _get_request_cookies()       # Cookie 组装（含 buvid）
    └→ _do_http_request()           # curl_cffi → requests 兜底
    └→ _handle_successful_response()# 解析 JSON → 检查 412 → 提取 data
"""
import time
import random
import logging
import threading
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


def _ensure_min_interval(self):
    """确保两次请求之间的最小间隔（高斯随机抖动）

    使用高斯分布生成随机延迟，模拟人类不规律的请求模式。
    延迟中心值 = min_request_interval，标准差 = min_request_interval * 0.3。

    线程安全：通过 _interval_lock 保证并发安全。
    """
    with self._interval_lock:
        # 使用高斯分布计算目标间隔（比固定间隔更接近人类行为）
        target = max(
            self._min_request_interval * 0.5,
            random.gauss(self._min_request_interval, self._min_request_interval * 0.3),
        )
        elapsed = time.time() - self._last_request_time
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_request_time = time.time()


def _rotate_user_agent(self):
    """随机更换 User-Agent（用于绕过措施）"""
    self.session.headers["User-Agent"] = random.choice(self.USER_AGENTS)
    logger.debug(f"User-Agent已更换: {self.session.headers['User-Agent'][:50]}...")


def _get_request_cookies(self) -> Dict:
    """获取当前请求应该使用的 Cookie 字典

    包含当前账号的 Cookie，并自动添加 buvid3 和 buvid4 设备指纹。
    有 10% 的概率随机更换 buvid3（模拟设备变化，降低被关联的概率）。
    """
    cookies = dict(self._cookies)
    cookies.setdefault("buvid3", self._buvid3)
    cookies.setdefault("buvid4", self._buvid4)
    # 10% 概率更换 buvid3，模拟设备更替
    if random.random() < 0.1:
        self._buvid3 = self._gen_buvid()
        cookies["buvid3"] = self._buvid3
    return cookies


def _update_public_headers(self):
    """更新公共 API Session 的请求头（无需登录的请求用单独的 Session）"""
    self._public_session.headers.update(
        {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
        }
    )


def _get_retry_delay(self, attempt: int) -> float:
    """计算指数退避的重试延迟

    延迟公式：base_delay * 2^attempt + random_jitter，上限 max_retry_delay。
    第 0 次：约 2-3s，第 1 次：约 4-6s，第 2 次：约 8-12s。

    Args:
        attempt: 当前重试次数（从 0 开始）

    Returns:
        建议等待的秒数
    """
    base_delay = self.base_retry_delay * (2**attempt)
    jitter = random.uniform(0, base_delay * 0.5)  # 随机抖动，避免惊群效应
    delay = min(base_delay + jitter, self.max_retry_delay)
    return delay


def _apply_bypass_measures(self, attempt: int):
    """应用绕过措施（在检测到 412 或其他限制时调用）

    第 0 次尝试：更换 UA
    第 1 次起：增加请求间隔 + 切换到下一个代理

    Args:
        attempt: 当前尝试次数
    """
    measures = []
    self._on_request_failure()  # 通知 ProxyManager 记录失败
    measures.append("已更换User-Agent")
    if attempt >= 1:
        old_interval = self._min_request_interval
        self._min_request_interval = min(old_interval * 2, 5.0)  # 逐步增长，上限 5s
        measures.append(f"请求间隔: {old_interval:.1f}s -> {self._min_request_interval:.1f}s")
    if self.proxy_manager.proxies:
        # 获取下一个代理（已自动跳过失败过多的代理）
        _, new_proxy, _ = self.proxy_manager.get_proxy_binding()
        if new_proxy:
            masked = self.proxy_manager.mask_url(new_proxy.get("http", "N/A"))
            measures.append(f"更换代理: {masked}")
    logger.info(f"绕过措施: {', '.join(measures)}")


def _is_412_error(self, data: Dict) -> bool:
    """判断 API 响应是否为 412/509/10403 限流错误

    B站限流错误码：-412（频率限制）、-509（IP 受限）、-10403（访问过于频繁）。
    同时也检查 message 中是否包含"请求过于频繁"。

    Args:
        data: API 返回的 JSON 响应体（dict）

    Returns:
        True 表示这是限流错误
    """
    if isinstance(data, dict):
        code = data.get("code")
        return code in [-412, -509, -10403] or "请求过于频繁" in str(data.get("message", ""))
    return False


def _get_error_info(self, data: Dict):
    """从 API 响应中提取错误码和错误信息

    Args:
        data: API 返回的 JSON 响应体

    Returns:
        (错误码, 错误信息) 元组
    """
    return data.get("code", -1), data.get("message", "未知错误")


def _prepare_request_kwargs(self, **kwargs) -> Dict:
    """准备请求参数：获取代理绑定并设置 proxies/headers

    从 ProxyManager 获取当前使用的代理及其绑定的 UA。

    Args:
        **kwargs: 调用方传入的额外请求参数

    Returns:
        准备好的 requests.request() 参数字典
    """
    idx, proxy, ua = self.proxy_manager.get_proxy_binding()
    request_kwargs = {"timeout": 15, **kwargs}
    if proxy:
        request_kwargs["proxies"] = proxy
        request_kwargs.setdefault("verify", False)  # 代理通常使用自签名证书
        masked = self.proxy_manager.mask_url(proxy.get("http", ""))
        logger.debug(f"→ 请求代理: {masked}")
    else:
        logger.debug("→ 请求直连（无代理）")
    # curl_cffi 的 UA 在 _do_http_request 中通过 impersonate 参数控制
    if self._has_curl_cffi and self._impersonate:
        pass  # impersonate 会自动设置 TLS 指纹和 UA
    elif ua:
        request_kwargs.setdefault("headers", {})
        request_kwargs["headers"]["User-Agent"] = ua
    return request_kwargs


def _do_http_request(self, method, url, request_kwargs, cookies):
    """执行 HTTP 请求（curl_cffi 优先，失败回退 requests）

    优先使用 curl_cffi（TLS 指纹伪装），如果 curl_cffi 抛出异常，
    则回退到标准的 requests 库。

    Args:
        method: HTTP 方法（GET/POST）
        url: 请求 URL
        request_kwargs: 请求参数字典
        cookies: Cookie 字典

    Returns:
        _CurlCffiResponse 或 requests.Response 对象
    """
    err = None
    if self._has_curl_cffi and self._curl_session:
        try:
            from curl_cffi import requests as _curl_req
            from core.bilibili_api import _CurlCffiResponse

            # 提取代理字符串（curl_cffi 使用 "all" 键表示全局代理）
            proxy = request_kwargs.get("proxies", None)
            proxy_str = proxy.get("http", "") if proxy else ""
            curl_kwargs = {
                "params": request_kwargs.get("params"),
                "data": request_kwargs.get("data"),
                "headers": {k: v for k, v in self._curl_session.headers.items()},
                "cookies": cookies,
                "timeout": request_kwargs.get("timeout", 15),
                "verify": request_kwargs.get("verify", True),
            }
            if proxy_str:
                curl_kwargs["proxies"] = {"all": proxy_str}
            if self._impersonate:
                curl_kwargs["impersonate"] = self._impersonate
            resp = self._curl_session.request(method, url, **curl_kwargs)
            return _CurlCffiResponse(resp)
        except Exception as e:
            err = e
            logger.debug("curl_cffi 失败，回退 requests: %s", e)
    # 回退到标准 requests（不带 TLS 伪装）
    try:
        if cookies:
            request_kwargs["cookies"] = cookies
        response = self.session.request(method, url, **request_kwargs)
        return response
    except Exception as e:
        if err:
            raise err from e  # 保留原始原因
        raise


def _handle_http_412_response(self, attempt, max_retries, skip_retry) -> bool:
    """处理 HTTP 412 状态码响应（限流响应）

    如果可以重试：等待退避延迟后触发绕过措施，返回 True。
    如果不能重试：返回 False。

    Returns:
        True 表示应该重试，False 表示应该放弃
    """
    self._consecutive_412_errors += 1
    logger.error(f"HTTP 412错误 (第{attempt + 1}次尝试)")
    if attempt < max_retries and not skip_retry:
        delay = _get_retry_delay(self, attempt)
        logger.info(f"等待 {delay:.1f} 秒后重试...")
        time.sleep(delay)
        self._on_request_failure()
        return True
    return False


def _handle_successful_response(self, data, attempt, max_retries, skip_retry):
    """处理 HTTP 200 响应体中的 JSON 数据

    检查 API 层面的业务码：
      - code=0: 返回 data 字段，重置 412 计数
      - code=-412/-509/-10403: 限流错误，触发重试

    Args:
        data: JSON 解析后的响应体
        attempt: 当前尝试次数
        max_retries: 最大重试次数
        skip_retry: 是否跳过重试

    Returns:
        (解析结果, 是否应该重试) 元组
    """
    if not isinstance(data, dict):
        return data, False
    api_code = data.get("code", 0)
    if api_code == 0:
        self._consecutive_412_errors = 0
        return data.get("data"), False
    if _is_412_error(self, data):
        self._consecutive_412_errors += 1
        error_code, error_msg = _get_error_info(self, data)
        logger.error(f"B站API 412错误: {error_msg} (第{attempt + 1}次尝试)")
        if attempt < max_retries and not skip_retry:
            delay = _get_retry_delay(self, attempt)
            logger.info(f"等待 {delay:.1f} 秒后重试...")
            time.sleep(delay)
            _apply_bypass_measures(self, attempt)
            return None, True
        return None, False
    if api_code != 0:
        logger.error(f"API错误 [{api_code}]: {data.get('message', '')}")
    return data.get("data") if "data" in data else None, False


def _request(
    self, method: str, url: str, max_retries: int = None, skip_retry: bool = False, **kwargs
) -> Optional[Dict]:
    """HTTP 请求核心方法（带重试和绕过机制）

    统一的请求入口，支持：
      - 自动 curl_cffi/requests 切换
      - 412 错误重试（指数退避 + 绕过措施）
      - HTTP 超时/连接错误重试

    请求流程：
      1. 检查请求间隔 (_ensure_min_interval)
      2. 准备请求参数 (_prepare_request_kwargs)
      3. 组装 Cookie (_get_request_cookies)
      4. 发送请求 (_do_http_request)
      5. 处理响应 (_handle_http_412_response / _handle_successful_response)
      6. 异常处理（超时、连接错误、HTTP 5xx、UnicodeEncodeError）

    Args:
        method: HTTP 方法（GET/POST）
        url: 请求 URL
        max_retries: 最大重试次数（默认使用 self.max_retries）
        skip_retry: True 时跳过重试，直接返回失败
        **kwargs: 传递给 requests.request() 的额外参数

    Returns:
        解析后的 data 字典，失败返回 None
    """
    if max_retries is None:
        max_retries = self.max_retries
    last_error = None
    logger.debug("→ %s %s", method.upper(), url.split("?")[0])
    for attempt in range(max_retries + 1):
        try:
            _ensure_min_interval(self)
            request_kwargs = _prepare_request_kwargs(self, **kwargs)
            cookies = _get_request_cookies(self)
            response = _do_http_request(self, method, url, request_kwargs, cookies)
            if response is None:
                continue
            sc = response.status_code
            # HTTP 412: B站 频率限制
            if sc == 412:
                if _handle_http_412_response(self, attempt, max_retries, skip_retry):
                    continue
                return None
            # HTTP 5xx 或 429: 服务端异常或请求过多
            if sc >= 500 or sc == 429:
                raise requests.exceptions.HTTPError(f"HTTP {sc}")
            data = response.json()
            self._consecutive_412_errors = 0
            logger.debug("← %s %s → %s", method.upper(), url.split("?")[0], sc)
            result, should_retry = _handle_successful_response(self, data, attempt, max_retries, skip_retry)
            if should_retry:
                continue
            return result
        except requests.exceptions.Timeout:
            last_error = "请求超时"
            logger.error(f"请求超时 (第{attempt + 1}次尝试)")
        except requests.exceptions.ConnectionError as e:
            last_error = f"连接错误: {e}"
            logger.error(f"连接错误 (第{attempt + 1}次尝试): {e}")
        except requests.exceptions.HTTPError as e:
            last_error = f"HTTP错误: {e}"
            logger.error(f"HTTP错误 (第{attempt + 1}次尝试): {e}")
            if attempt < max_retries and not skip_retry:
                delay = _get_retry_delay(self, attempt)
                time.sleep(delay)
                self._on_request_failure()
                continue
            break
        except UnicodeEncodeError as e:
            # Cookie 中包含非 Latin-1 字符时会触发此异常
            last_error = f"编码错误: {e}"
            logger.error(f"请求头编码异常 (第{attempt + 1}次尝试): {e}")
            break
        except Exception as e:
            last_error = str(e)
            logger.error(f"请求异常: {e}")
            break
        if attempt < max_retries and not skip_retry:
            delay = _get_retry_delay(self, attempt)
            time.sleep(delay)
            self._on_request_failure()
    logger.error(f"请求最终失败: {last_error}")
    return None


def _request_public(self, method: str, url: str, **kwargs) -> Any:
    """公共 API 请求（免 Cookie，用于无需登录的接口）

    使用独立的 _public_session，不携带任何 Cookie 和 WBI 签名。
    适用于 /x/space/acc/info 等无需登录即可访问的开放接口。

    Args:
        method: HTTP 方法
        url: 请求 URL
        **kwargs: 额外参数

    Returns:
        解析后的 data 字段，失败返回 None
    """
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
        try:
            _update_public_headers(self)
            idx, proxy, ua = self.proxy_manager.get_proxy_binding()
            if proxy:
                self._public_session.proxies.update(proxy)
                self._public_session.headers["User-Agent"] = ua or self._public_session.headers["User-Agent"]
                kwargs.setdefault("verify", False)
            logger.debug("→ [public] %s %s", method.upper(), url.split("?")[0])
            resp = self._public_session.request(method, url, timeout=15, **kwargs)
            logger.debug("← [public] %s", resp.status_code)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                if attempt < max_attempts - 1:
                    delay = _get_retry_delay(self, attempt)
                    logger.debug(f"公共API请求 {resp.status_code}，{delay:.1f}s 后重试...")
                    time.sleep(delay)
                    continue
                return None
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data")
            last_error = f"API code {data.get('code')}"
        except Exception as e:
            last_error = str(e)
            logger.debug(f"公共API请求失败 (第{attempt + 1}次): {e}")
            if attempt < max_attempts - 1:
                delay = _get_retry_delay(self, attempt)
                time.sleep(delay)
                continue
            return None
    logger.debug(f"公共API请求最终失败: {last_error}")
    return None


class _RequestMixin:
    """请求 Mixin 类 — 将所有模块级函数通过类属性注入到 BilibiliAPI

    Mixin 模式说明：
      模块中定义的 top-level 函数第一个参数都是 self，
      通过类属性赋值后，BilibiliAPI 实例调用这些方法时
      Python 会自动将实例作为 self 传入。
    """
    _request = _request
    _request_public = _request_public
    _prepare_request_kwargs = _prepare_request_kwargs
    _do_http_request = _do_http_request
    _handle_http_412_response = _handle_http_412_response
    _handle_successful_response = _handle_successful_response
    _apply_bypass_measures = _apply_bypass_measures
    _get_retry_delay = _get_retry_delay
    _ensure_min_interval = _ensure_min_interval
    _rotate_user_agent = _rotate_user_agent
    _get_request_cookies = _get_request_cookies
    _update_public_headers = _update_public_headers
    _is_412_error = _is_412_error
    _get_error_info = _get_error_info
