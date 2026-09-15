"""
B站API模块 - HTTP请求核心
支持 curl_cffi TLS 指纹伪装、412 错误重试、代理绑定、指数退避
"""

import time
import random
import logging
from typing import Any, Dict, Optional, Tuple, cast

import requests

logger = logging.getLogger(__name__)


# ── 风控分流（依据 docs/risk_control_playbook.md §2/§11）──────────────────────
# -352 = UA/WBI 签名校验失败：换 IP 无效，重新签名 + 放慢才有效
# -412/-509/-10403 = IP 级限流：换 IP 有效
RISK_SIGN_CODES = (-352,)
RISK_IP_CODES = (-412, -509, -10403)
# code:0 也可能夹带一次性风控凭证；凭证不可构造，只能上报与冷却
RISK_VOUCHER_KEYS = ("v_voucher", "v_voucher_ttl", "gaia_vtoken")
RISK_COOLDOWN_SIGN = 180.0  # 首次命中 -352/v_voucher 的冷却（秒）
RISK_COOLDOWN_IP = 600.0  # 首次命中 412 的冷却（秒）
RISK_COOLDOWN_MAX = 1800.0  # 冷却上限（秒）
RISK_VOUCHER_GLOBAL_THRESHOLD = 3  # 连续命中达到此值才升级为全局冷却


def _extract_voucher(data: Any) -> str:
    """提取风控凭证（可能位于顶层或 data 内；不可构造，仅用于上报与冷却）。"""
    if not isinstance(data, dict):
        return ""
    for container in (data, data.get("data")):
        if isinstance(container, dict):
            for key in RISK_VOUCHER_KEYS:
                value = container.get(key)
                if isinstance(value, str) and value:
                    return value
    return ""


def _is_352_error(self: Any, data: Dict[str, Any]) -> bool:
    """-352：UA/WBI 签名校验失败（与 IP 级 412 成因不同，处置必须分流）。"""
    if not isinstance(data, dict):
        return False
    if data.get("code") in RISK_SIGN_CODES:
        return True
    message = str(data.get("message", ""))
    return "风控校验失败" in message or "签名校验失败" in message


def _refresh_ticket_after_risk(self: Any) -> None:
    """风控命中后顺手刷新 bili_ticket（失败只记日志，不影响主流程）。"""
    try:
        from core.bilibili_ticket import ensure_ticket

        ensure_ticket(self, force=True)
    except Exception as e:
        logger.debug("风控后刷新 bili_ticket 失败: %s", e)


def _register_risk_cooldown(self: Any, kind: str) -> float:
    """记录一次风控命中并返回冷却秒数（连续命中按次数升级，封顶 ``RISK_COOLDOWN_MAX``）。"""
    if kind == "sign":
        self._voucher_streak = int(getattr(self, "_voucher_streak", 0)) + 1
        seconds = RISK_COOLDOWN_SIGN * self._voucher_streak
        scope = "global" if self._voucher_streak >= RISK_VOUCHER_GLOBAL_THRESHOLD else "session"
        _refresh_ticket_after_risk(self)
    else:
        self._voucher_streak = 0
        seconds = RISK_COOLDOWN_IP
        scope = "session"
    seconds = float(min(seconds, RISK_COOLDOWN_MAX))
    self._risk_cooldown_until = time.time() + seconds
    self._risk_last_kind = kind
    self._risk_scope = scope
    logger.warning("风控命中(%s): 冷却 %.0fs 范围=%s 连续=%d", kind, seconds, scope, self._voucher_streak)
    return seconds


def risk_state(self: Any) -> Dict[str, Any]:
    """风控只读观测（供 UI / 日志 / 监控上报；不改变请求行为）。"""
    until = float(getattr(self, "_risk_cooldown_until", 0.0) or 0.0)
    return {
        "cooldown_remaining": round(max(0.0, until - time.time()), 1),
        "voucher_streak": int(getattr(self, "_voucher_streak", 0)),
        "scope": str(getattr(self, "_risk_scope", "")),
        "last_kind": str(getattr(self, "_risk_last_kind", "")),
        "last_voucher": str(getattr(self, "_risk_last_voucher", "")),
        "logged_out": bool(getattr(self, "_logged_out", False)),
        "consecutive_412_errors": int(getattr(self, "_consecutive_412_errors", 0)),
    }


def _ensure_min_interval(self: Any) -> None:
    with self._interval_lock:
        target = max(
            self._min_request_interval * 0.5,
            random.gauss(self._min_request_interval, self._min_request_interval * 0.3),
        )
        elapsed = time.time() - self._last_request_time
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last_request_time = time.time()


def _rotate_user_agent(self: Any) -> None:
    self.session.headers["User-Agent"] = random.choice(self.USER_AGENTS)
    logger.debug(f"User-Agent已更换: {self.session.headers['User-Agent'][:50]}...")


def _get_request_cookies(self: Any) -> Dict[str, Any]:
    cookies = dict(self._cookies)
    cookies.setdefault("buvid3", self._buvid3)
    cookies.setdefault("buvid4", self._buvid4)
    # bili_ticket 可降低反复风控（规格见 docs/risk_control_playbook.md §3）：
    # 这里**只读实例缓存**，绝不在请求热路径上触发网络刷新
    ticket = str(getattr(self, "_bili_ticket", "") or "")
    if ticket:
        cookies.setdefault("bili_ticket", ticket)
    if random.random() < 0.1:
        self._buvid3 = self._gen_buvid()
        cookies["buvid3"] = self._buvid3
    return cookies


def _update_public_headers(self: Any) -> None:
    self._public_session.headers.update(
        {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
        }
    )


def _get_retry_delay(self: Any, attempt: int) -> float:
    base_delay = self.base_retry_delay * (2**attempt)
    jitter = random.uniform(0, base_delay * 0.5)
    delay = min(base_delay + jitter, self.max_retry_delay)
    return float(delay)


def _apply_bypass_measures(self: Any, attempt: int, proxy_idx: Optional[int] = None, kind: str = "ip") -> None:
    """按风控类型施加绕过措施：``sign``（352/签名）重新签名且**不轮换代理**，``ip``（412）才换 IP。"""
    measures: list[str] = []
    if kind == "sign":
        _rotate_user_agent(self)
        measures.append("352 换 IP 无效：保持代理，改重新签名/更换 UA")
    else:
        self._on_request_failure(proxy_idx)
        measures.append("已更换User-Agent")
    if attempt >= 1:
        old_interval = self._min_request_interval
        self._min_request_interval = min(old_interval * 2, 5.0)
        measures.append(f"请求间隔: {old_interval:.1f}s -> {self._min_request_interval:.1f}s")
    if kind == "ip" and self.proxy_manager.proxies:
        _, new_proxy, _ = self.proxy_manager.get_proxy_binding()
        if new_proxy:
            masked = self.proxy_manager.mask_url(new_proxy.get("http", "N/A"))
            measures.append(f"更换代理: {masked}")
    logger.info(f"绕过措施: {', '.join(measures)}")


def _is_412_error(self: Any, data: Dict[str, Any]) -> bool:
    if isinstance(data, dict):
        code = data.get("code")
        return code in [-412, -509, -10403] or "请求过于频繁" in str(data.get("message", ""))
    return False


def _get_error_info(self: Any, data: Dict[str, Any]) -> tuple[Any, Any]:
    return data.get("code", -1), data.get("message", "未知错误")


def _prepare_request_kwargs(self: Any, **kwargs: Any) -> Tuple[Dict[str, Any], Optional[int]]:
    idx, proxy, ua = self.proxy_manager.get_proxy_binding()
    request_kwargs = {"timeout": 15, **kwargs}
    if proxy:
        request_kwargs["proxies"] = proxy
        # 仅在 SOCKS 代理或用户显式配置时禁用 SSL 验证；HTTP/HTTPS 代理保留证书校验
        proxy_url = proxy.get("http", "") or proxy.get("https", "")
        if proxy_url.lower().startswith(("socks4", "socks5")):
            request_kwargs.setdefault("verify", False)
            logger.debug("→ SOCKS 代理，已禁用 SSL 证书验证")
        else:
            logger.info("→ 使用 HTTP/HTTPS 代理，SSL 证书验证已启用（若代理使用自签证书请手动配置）")
        masked = self.proxy_manager.mask_url(proxy_url)
        logger.debug(f"→ 请求代理: {masked}")
    else:
        logger.debug("→ 请求直连（无代理）")
    if self._has_curl_cffi and self._impersonate:
        pass
    elif ua:
        request_kwargs.setdefault("headers", {})
        request_kwargs["headers"]["User-Agent"] = ua
    return request_kwargs, idx


def _do_http_request(
    self: Any, method: str, url: str, request_kwargs: Dict[str, Any], cookies: Optional[Dict[str, Any]]
) -> Any:
    err: Optional[Exception] = None
    if self._has_curl_cffi and self._curl_session:
        try:
            from core.bilibili_api import _CurlCffiResponse

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
    try:
        if cookies:
            request_kwargs["cookies"] = cookies
        response = self.session.request(method, url, **request_kwargs)
        return response
    except Exception as e:
        if err:
            raise err from e
        raise


def _handle_http_412_response(
    self: Any, attempt: int, max_retries: int, skip_retry: bool, proxy_idx: Optional[int] = None
) -> bool:
    self._consecutive_412_errors += 1
    logger.error(f"HTTP 412错误 (第{attempt + 1}次尝试)")
    if attempt < max_retries and not skip_retry:
        delay = _get_retry_delay(self, attempt)
        logger.info(f"等待 {delay:.1f} 秒后重试...")
        time.sleep(delay)
        self._on_request_failure(proxy_idx)
        return True
    return False


def _handle_successful_response(
    self: Any,
    data: Any,
    attempt: int,
    max_retries: int,
    skip_retry: bool,
    proxy_idx: Optional[int] = None,
) -> tuple[Any, bool]:
    if not isinstance(data, dict):
        return data, False
    api_code = data.get("code", 0)
    voucher = _extract_voucher(data)
    if api_code == 0:
        self._consecutive_412_errors = 0
        self._logged_out = False
        if voucher:
            # code:0 仍可能夹带一次性风控凭证（数据可用，但要记冷却并上报）
            self._risk_last_voucher = voucher
            _register_risk_cooldown(self, "sign")
        return data.get("data"), False
    if api_code == -101:
        logger.warning("登录态可能已失效 (api_code=-101)，请重新登录")
        self._logged_out = True
        return None, False
    if _is_352_error(self, data):
        # 签名/风控校验失败：过去落到末行被当作「空数据」静默吞掉
        self._consecutive_412_errors += 1
        error_code, error_msg = _get_error_info(self, data)
        self._risk_last_voucher = voucher
        _register_risk_cooldown(self, "sign")
        logger.error(f"B站API 签名风控错误 [{error_code}]: {error_msg} (第{attempt + 1}次尝试)")
        if attempt < max_retries and not skip_retry:
            delay = _get_retry_delay(self, attempt)
            logger.info(f"等待 {delay:.1f} 秒后重试...")
            time.sleep(delay)
            _apply_bypass_measures(self, attempt, proxy_idx, kind="sign")
            return None, True
        return None, False
    if _is_412_error(self, data):
        self._consecutive_412_errors += 1
        error_code, error_msg = _get_error_info(self, data)
        _register_risk_cooldown(self, "ip")
        logger.error(f"B站API 412错误: {error_msg} (第{attempt + 1}次尝试)")
        if attempt < max_retries and not skip_retry:
            delay = _get_retry_delay(self, attempt)
            logger.info(f"等待 {delay:.1f} 秒后重试...")
            time.sleep(delay)
            _apply_bypass_measures(self, attempt, proxy_idx, kind="ip")
            return None, True
        return None, False
    if api_code != 0:
        logger.error(f"API错误 [{api_code}]: {data.get('message', '')}")
        if voucher:
            self._risk_last_voucher = voucher
            _register_risk_cooldown(self, "sign")
    return data.get("data") if "data" in data else None, False


def _process_request_response(
    self: Any,
    response: Any,
    method: str,
    url: str,
    attempt: int,
    max_retries: int,
    skip_retry: bool,
    proxy_idx: Optional[int],
) -> tuple[Any, bool]:
    sc = response.status_code
    if sc == 412:
        if _handle_http_412_response(self, attempt, max_retries, skip_retry, proxy_idx):
            return None, True
        return None, False
    if sc >= 500 or sc == 429:
        raise requests.exceptions.HTTPError(f"HTTP {sc}")
    data = response.json()
    self._consecutive_412_errors = 0
    logger.debug("← %s %s → %s", method.upper(), url.split("?")[0], sc)
    return _handle_successful_response(self, data, attempt, max_retries, skip_retry, proxy_idx)


def _request(
    self: Any,
    method: str,
    url: str,
    max_retries: Optional[int] = None,
    skip_retry: bool = False,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    if max_retries is None:
        max_retries = self.max_retries
    last_error = None
    proxy_idx: Optional[int] = None
    logger.debug("→ %s %s", method.upper(), url.split("?")[0])
    for attempt in range(max_retries + 1):
        try:
            _ensure_min_interval(self)
            request_kwargs, proxy_idx = _prepare_request_kwargs(self, **kwargs)
            cookies = _get_request_cookies(self)
            response = _do_http_request(self, method, url, request_kwargs, cookies)
            if response is None:
                continue
            result, should_retry = _process_request_response(
                self, response, method, url, attempt, max_retries, skip_retry, proxy_idx
            )
            if should_retry:
                continue
            return cast(Optional[Dict[str, Any]], result)
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
                self._on_request_failure(proxy_idx)
                continue
            break
        except UnicodeEncodeError as e:
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
            self._on_request_failure(proxy_idx)
    logger.error(f"请求最终失败: {last_error}")
    return None


def _request_public(self: Any, method: str, url: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
        try:
            _update_public_headers(self)
            idx, proxy, ua = self.proxy_manager.get_proxy_binding()
            if proxy:
                self._public_session.proxies.update(proxy)
                self._public_session.headers["User-Agent"] = ua or self._public_session.headers["User-Agent"]
                proxy_url = proxy.get("http", "") or proxy.get("https", "")
                if proxy_url.lower().startswith(("socks4", "socks5")):
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
                return cast(Optional[Dict[str, Any]], data.get("data"))
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
    _is_352_error = _is_352_error
    _get_error_info = _get_error_info
    risk_state = risk_state
