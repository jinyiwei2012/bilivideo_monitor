"""
B站API模块 - 封装B站相关接口
增强版：支持获取观看人数、412错误重试与绕过机制
"""

import requests
import time
import random
import logging
import threading
import warnings
import hashlib
import re
from typing import Any, Callable, Dict, List, Optional, ParamSpec, TypeVar, cast
from urllib.parse import quote

from core.proxy_manager import ProxyManager
from core.constants import USER_AGENTS
from core.bilibili_request import _RequestMixin
from core.bilibili_auth import _AuthMixin
from core.bilibili_video import _VideoMixin
from core.bilibili_up import _UpMixin

# Suppress InsecureRequestWarning for SOCKS/HTTP proxies using self-signed certs
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_T = TypeVar("_T")


class BilibiliAPIError(Exception):
    """B站API异常基类"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class RateLimitError(BilibiliAPIError):
    """频率限制错误 (412)"""


class _CurlCffiResponse:
    """将 curl_cffi response 包装为与 requests.Response 兼容的接口"""

    def __init__(self, resp: Any) -> None:
        self.status_code = resp.status_code
        self.content = resp.content
        self.raw = resp.content
        self.text = resp.text
        self.headers = resp.headers
        self.url = str(resp.url)
        self.cookies = resp.cookies
        self._resp = resp

    def json(self, **kwargs: Any) -> Any:
        return self._resp.json(**kwargs)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            from requests.exceptions import HTTPError

            raise HTTPError(f"HTTP {self.status_code}", response=self)


# ── WBI 签名（规范、验证向量与来源见 docs/bilibili_api_contract.md §1）──────────
# 混音密钥置换表：按此表重排 ``img_key+sub_key`` 后取前 32 字符（**不是** md5(img+sub)）
MIXIN_KEY_ENC_TAB: List[int] = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]

_WBI_ILLEGAL_CHARS = re.compile(r"[!'()*]")


def wbi_mixin_key(img_key: str, sub_key: str) -> str:
    """WBI 混音密钥：按置换表重排 ``img_key+sub_key`` 后取前 32 字符。"""
    orig = img_key + sub_key
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB if i < len(orig))[:32]


def wbi_key_from_url(url: str) -> str:
    """从 ``wbi_img`` 的 ``img_url`` / ``sub_url`` 提取密钥（末段文件名去扩展名）。"""
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def wbi_query(params: Dict[str, Any]) -> str:
    """按 WBI 规则编码参数为 query：值过滤 ``!'()*``、k/v 百分号编码、key 升序。"""
    parts = []
    for key in sorted(params):
        value = _WBI_ILLEGAL_CHARS.sub("", str(params[key]))
        parts.append(f"{quote(str(key), safe='')}={quote(value, safe='')}")
    return "&".join(parts)


class BilibiliAPI(_RequestMixin, _AuthMixin, _VideoMixin, _UpMixin):
    """B站API封装类 - 支持重试与绕过412错误"""

    BASE_URL = "https://api.bilibili.com"
    SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
    VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"
    VIEWERS_URL = "https://api.bilibili.com/x/player/online/total"
    DANMAKU_URL = "https://api.bilibili.com/x/v1/dm/list.so"
    COMMENT_URL = "https://api.bilibili.com/x/v2/reply/main"
    POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"

    # wbi 混音密钥（运行时按 _WBI_KEY_TTL 刷新，见 docs/bilibili_api_contract.md §1）
    _wbi_key: Optional[str] = None
    _wbi_key_expire: float = 0.0
    _WBI_KEY_TTL: float = 600.0

    # 多个User-Agent轮换使用（2026 版本，与 curl_cffi 默认 impersonate Chrome 版本对齐）
    USER_AGENTS = USER_AGENTS

    # 默认请求头
    BASE_HEADERS = {
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def __init__(self) -> None:
        """初始化 BilibiliAPI 实例，创建连接池、加载 Cookie 和代理配置"""
        self.session = requests.Session()

        # 连接池复用：增大池大小以支持多视频并发监控 + 弹幕拉取
        from requests.adapters import HTTPAdapter

        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # 公共 API Session（免 Cookie，复用连接池）
        self._public_session = requests.Session()
        pub_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
        self._public_session.mount("https://", pub_adapter)
        self._public_session.mount("http://", pub_adapter)

        # curl_cffi Session（TLS 指纹伪装，主 API 路径优先使用）
        self._curl_session: Any = None
        self._has_curl_cffi = False
        self._impersonate = ""
        self._init_curl_cffi()

        self._update_headers()
        self._update_public_headers()

        # 重试配置
        self.max_retries = 3
        self.base_retry_delay = 2
        self.max_retry_delay = 60

        # 代理管理器
        self.proxy_manager = ProxyManager()

        # 全局限流状态
        self._consecutive_412_errors = 0
        self._last_request_time = 0
        self._min_request_interval = 0.5
        self._interval_lock = threading.Lock()

        # cookie支持（多账号）
        self._cookies: Dict[str, Any] = {}
        self._refresh_token: str = ""
        self._accounts: list[Dict[str, Any]] = []
        self._active_account_idx: int = -1
        self._account_name: str = "默认"

        # 登录态标记：收到 api_code=-101（未登录）时置 True，供上层提示重新登录
        self._logged_out = False
        # 风控观测状态（分流与冷却语义见 docs/risk_control_playbook.md §2/§11）
        self._voucher_streak = 0
        self._risk_cooldown_until = 0.0
        self._risk_last_kind = ""
        self._risk_scope = ""
        self._risk_last_voucher = ""
        # bili_ticket（缓存在 Cookie 里，规格见 docs/risk_control_playbook.md §3）
        self._bili_ticket = str(self._cookies.get("bili_ticket", "") or "")
        try:
            self._bili_ticket_expires = float(self._cookies.get("bili_ticket_expires", 0) or 0)
        except (TypeError, ValueError):
            self._bili_ticket_expires = 0.0

        # 随机 buvid（模拟不同设备指纹，降低 412 概率）
        self._buvid3 = self._gen_buvid()
        self._buvid4 = self._gen_buvid()

        # 启动时加载已保存的 Cookie 和代理
        self._load_saved_network_config()
        self.proxy_manager.init_ua_bindings()
        # 设备标识：补齐 _uuid / b_lsid / b_nut 并持久化（本地生成，不发网络请求；见风控手册 §4）
        self._uuid = ""
        self._b_lsid = ""
        self._b_nut = ""
        try:
            from core.device_identity import ensure_identity

            ensure_identity(self, fetch_remote=False)
        except Exception as e:
            logger.debug("初始化设备标识失败: %s", e)
        # 代理自动发现改由用户在设置界面手动触发，启动时不拉取

    @staticmethod
    def _gen_buvid() -> str:
        """生成随机 buvid（模拟浏览器设备指纹）"""
        import uuid as _uuid

        return _uuid.uuid4().hex.upper()[:16] + _uuid.uuid4().hex.upper()[:16] + "infoc"

    def _init_curl_cffi(self) -> None:
        """初始化 curl_cffi 会话（TLS 指纹伪装）"""
        try:
            from curl_cffi import requests as _curl_req

            curl_session: Any = _curl_req.Session(impersonate="chrome131")
            curl_session.headers.update(
                {
                    "Referer": "https://www.bilibili.com/",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
            self._curl_session = curl_session
            self._has_curl_cffi = True
            self._impersonate = "chrome131"
            logger.info("curl_cffi TLS 指纹伪装已启用 (impersonate=chrome131)")
        except ImportError:
            self._has_curl_cffi = False
            logger.info("curl_cffi 未安装，使用 requests 直连 (pip install curl_cffi)")

    @staticmethod
    def _sanitize_cookies(cookies: Dict[str, Any]) -> Dict[str, Any]:
        """清理 cookie 值中非 Latin-1 字符，防止 requests 编码报错"""
        sanitized: Dict[str, Any] = {}
        for k, v in cookies.items():
            if isinstance(v, str):
                sanitized[k] = v.encode("latin-1", errors="replace").decode("latin-1")
            else:
                sanitized[k] = v
        return sanitized

    def _load_saved_network_config(self) -> None:
        """从 network_config.json 加载多账号 Cookie 和代理"""
        try:
            import json
            import os
            from utils.crypto import decrypt_dict

            cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "network_config.json")
            if not os.path.exists(cfg_path):
                return
            with open(cfg_path, "r", encoding="utf-8") as f:
                net_cfg = json.load(f)

            self._accounts = net_cfg.get("accounts", [])
            if not self._accounts:
                # 旧格式兼容：单账号。这里**只读出、不预先解密**——下方统一循环
                # 会对每个账号各做一次 decrypt_dict + _sanitize_cookies；若在此处先解密，
                # 明文会被二次解密 → 每次启动刷 4 条 UnicodeDecodeError + 1 条 HMAC 校验失败。
                cookies = net_cfg.get("cookies", {})
                if cookies:
                    name = net_cfg.get("account_name", "默认")
                    self._accounts = [
                        {
                            "name": name,
                            "cookies": cookies,
                            "refresh_token": net_cfg.get("refresh_token", ""),
                            "active": True,
                        }
                    ]

            # 根据 active_account 切换当前账号
            active_name = net_cfg.get("active_account", "")
            found = False
            for acc in self._accounts:
                acc["cookies"] = self._sanitize_cookies(
                    decrypt_dict(
                        acc.get("cookies", {}), "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"
                    )
                    if acc.get("cookies")
                    else {}
                )
                if acc["name"] == active_name:
                    self._cookies = dict(acc.get("cookies", {}))
                    self._refresh_token = acc.get("refresh_token", "")
                    self.session.cookies.update(self._cookies)
                    self._account_name = active_name
                    self._active_account_idx = self._accounts.index(acc)
                    found = True
            if not found and self._accounts:
                self.switch_account(self._accounts[0]["name"])
            if self._cookies:
                logger.info(f"已加载账号: {self._account_name} ({len(self._cookies)} 个 Cookie)")

            # 加载代理列表
            proxy_urls = net_cfg.get("proxies", [])
            for p in proxy_urls:
                self.proxy_manager.add_proxy({"http": p, "https": p})
            if proxy_urls:
                logger.info(f"已加载 {len(proxy_urls)} 个代理")
        except Exception as e:
            logger.warning(f"加载网络配置失败: {e}")

    def _update_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> None:
        """更新请求头"""
        headers = self.BASE_HEADERS.copy()
        headers["User-Agent"] = random.choice(self.USER_AGENTS)
        if extra_headers:
            headers.update(extra_headers)
        self.session.headers.update(headers)

    def _on_request_failure(self, proxy_idx: Optional[int] = None) -> None:
        """标记请求失败：委托 ProxyManager 处理并更新 session UA"""
        new_ua = self.proxy_manager.on_request_failure(proxy_idx)
        if new_ua:
            self.session.headers["User-Agent"] = new_ua

    def add_proxy(self, proxy: Dict[str, str]) -> None:
        """添加代理（委托给 ProxyManager）"""
        self.proxy_manager.add_proxy(proxy)

    def clear_proxies(self) -> None:
        """清空代理列表（委托给 ProxyManager）"""
        self.proxy_manager.clear_proxies()

    def bypass_412_with_retry(
        self, func: Callable[_P, Optional[_T]], *args: _P.args, **kwargs: _P.kwargs
    ) -> Optional[_T]:
        """
        使用重试机制执行函数（用于需要多次尝试的操作）
        """
        for attempt in range(self.max_retries + 1):
            result = func(*args, **kwargs)
            if result is not None:
                return result
            if attempt < self.max_retries:
                delay = self._get_retry_delay(attempt)
                logger.info(f"操作失败，等待 {delay:.1f}s 后重试...")
                time.sleep(delay)
                self._apply_bypass_measures(attempt)
        return None

    def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> List[Dict[str, Any]]:
        """搜索视频（多源兜底）"""
        params = {"keyword": keyword, "search_type": "video", "page": page, "pagesize": page_size}
        data = self._request("GET", self.SEARCH_URL, params=params)
        if data and "result" in data:
            return cast(List[Dict[str, Any]], data["result"])
        return self._search_videos_fallback(keyword, page, page_size)

    def _search_videos_fallback(self, keyword: str, page: int, page_size: int) -> List[Dict[str, Any]]:
        """使用 bilibili-api-python 兜底搜索"""
        try:
            from bilibili_api import sync
            from bilibili_api.search import search_by_type
            from bilibili_api.search import SearchObjectType

            result = sync(search_by_type(keyword, SearchObjectType.VIDEO, page=page))
            if result and "result" in result:
                return cast(List[Dict[str, Any]], result["result"])
        except ImportError:
            logger.debug("bilibili-api-python 未安装，跳过兜底搜索")
            pass
        except Exception as e:
            logger.debug("bilibili-api 兜底搜索失败: %s", e)
        return []

    def get_video_full_data(self, bvid: str) -> Optional[Dict[str, Any]]:
        """获取视频完整数据"""
        video_info = self.get_video_info(bvid)
        if not video_info:
            return None

        viewers_data = self.get_video_viewers(bvid, video_info.get("cid", 0))

        return {
            "bvid": bvid,
            "title": video_info.get("title", ""),
            "description": video_info.get("desc", ""),
            "pic": video_info.get("pic", ""),
            "owner": video_info.get("owner", {}),
            "stat": video_info.get("stat", {}),
            "viewers_total": int(viewers_data.get("total", 0)) if viewers_data else 0,
            "viewers_web": int(viewers_data.get("count", 0)) if viewers_data else 0,
            "viewers_app": (
                max(0, int(viewers_data.get("total", 0)) - int(viewers_data.get("count", 0))) if viewers_data else 0
            ),
        }

    # ── WBI签名 ───────────────────────────────────────────
    def _refresh_wbi_key(self) -> None:
        """刷新 WBI 混音密钥（来自 nav 的 ``wbi_img``，有效期 ``_WBI_KEY_TTL`` 秒）。"""
        try:
            nav_url = f"{self.BASE_URL}/x/web-interface/nav"
            data = self._request("GET", nav_url, skip_retry=True)
            wbi_img = (data or {}).get("wbi_img") or {}
            img_key = wbi_key_from_url(str(wbi_img.get("img_url", "")))
            sub_key = wbi_key_from_url(str(wbi_img.get("sub_url", "")))
            if img_key and sub_key:
                self._wbi_key = wbi_mixin_key(img_key, sub_key)
                self._wbi_key_expire = time.time() + self._WBI_KEY_TTL
                return
            self._wbi_key = None
            logger.warning("WBI密钥刷新失败: 无法解析密钥图片URL")
        except Exception as e:
            self._wbi_key = None
            logger.warning(f"WBI密钥刷新失败: {e}")

    def _wbi_sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """为请求参数添加 WBI 签名（``wts`` + ``w_rid``）。

        密钥缺失或过期时先刷新；刷新失败则**原样返回**（调用方仍可发请求，服务端会
        回 ``-403`` 或风控票据 ``v_voucher``）。``wts`` 必须参与哈希，否则验签失败。
        """
        if not self._wbi_key or time.time() >= self._wbi_key_expire:
            self._refresh_wbi_key()
        if not self._wbi_key:
            return params
        signed = dict(params)
        signed["wts"] = str(int(time.time()))
        query = wbi_query(signed)
        signed["w_rid"] = hashlib.md5((query + self._wbi_key).encode(), usedforsecurity=False).hexdigest()
        return signed

    # ── 热门视频 ─────────────────────────────────────────
    def get_popular_videos(self, pn: int = 1, ps: int = 20) -> List[Dict[str, Any]]:
        """获取热门视频列表"""
        data = self._request("GET", self.POPULAR_URL, params={"pn": pn, "ps": ps})
        if data and "list" in data:
            return cast(List[Dict[str, Any]], data["list"])
        return []

    def get_weekly_series(self, number: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取每周必看列表（自动获取最新期数）"""
        series_list_url = f"{self.BASE_URL}/x/web-interface/popular/series/list"
        list_data = self._request("GET", series_list_url)
        if list_data and "list" in list_data and list_data["list"]:
            if number is None:
                number = list_data["list"][0].get("number", number)
        if number is None:
            return []
        url = f"{self.BASE_URL}/x/web-interface/popular/series/one"
        params = {"number": number}
        data = self._request("GET", url, params=params)
        if data and "list" in data:
            return cast(List[Dict[str, Any]], data["list"])
        return []

    def get_status(self) -> Dict[str, Any]:
        """获取API状态信息"""
        login_status = False
        login_name = ""
        has_sessdata = bool(
            self.session.cookies.get("SESSDATA", domain=".bilibili.com") or self._cookies.get("SESSDATA")
        )
        if has_sessdata:
            try:
                nav = self._request("GET", f"{self.BASE_URL}/x/web-interface/nav", skip_retry=True)
                if nav and nav.get("isLogin"):
                    login_status = True
                    login_name = nav.get("uname", "")
                else:
                    logger.debug("nav 接口返回未登录，Cookie 可能已过期")
            except Exception as e:
                logger.debug(f"登录验证请求失败: {e}")
        else:
            has_sessdata = bool(self._cookies.get("SESSDATA"))

        return {
            "consecutive_412_errors": self._consecutive_412_errors,
            "min_request_interval": self._min_request_interval,
            "proxy_count": len(self.proxy_manager.proxies),
            "has_cookies": bool(self._cookies),
            "has_sessdata": bool(has_sessdata),
            "has_buvid3": bool(
                self.session.cookies.get("buvid3", domain=".bilibili.com") or self._cookies.get("buvid3")
            ),
            "is_login": login_status,
            "login_name": login_name,
            "risk": self.risk_state(),
        }

    def refresh_device_identity(self) -> Dict[str, Any]:
        """向服务端补全设备标识（buvid3/4）。需要网络，供设置页或风控命中时调用。"""
        from core.device_identity import ensure_identity

        return ensure_identity(self, fetch_remote=True)

    def reset_status(self) -> None:
        """重置状态（用于连续失败后的恢复）"""
        self._consecutive_412_errors = 0
        self._min_request_interval = 0.5
        self._voucher_streak = 0
        self._risk_cooldown_until = 0.0
        self._risk_last_kind = ""
        self._risk_scope = ""
        self._risk_last_voucher = ""
        self._logged_out = False
        logger.info("API状态已重置")

    def close(self) -> None:
        """关闭 HTTP Session，释放连接池。"""
        try:
            self.session.close()
            self._public_session.close()
            if self._curl_session:
                self._curl_session.close()
            if hasattr(self, "_close_qr_session"):
                self._close_qr_session()
        except Exception as e:
            logger.debug("关闭HTTP Session失败: %s", e)


# 全局API实例（延迟初始化，避免拖慢模块导入）
_bilibili_api_instance: Optional[BilibiliAPI] = None
_bilibili_api_lock = threading.Lock()


def _get_api() -> BilibiliAPI:
    """延迟获取/创建 BilibiliAPI 实例（双检锁线程安全）"""
    global _bilibili_api_instance
    if _bilibili_api_instance is None:
        with _bilibili_api_lock:
            if _bilibili_api_instance is None:
                _bilibili_api_instance = BilibiliAPI()
    return _bilibili_api_instance


def get_bilibili_api() -> BilibiliAPI:
    """获取全局 BilibiliAPI 实例"""
    return _get_api()


# ── 模块级便捷函数（兼容 from core import bilibili_api 调用方式）──


def get_video_info(bvid: str) -> Optional[Dict[str, Any]]:
    """模块级便捷函数：获取视频信息"""
    return _get_api().get_video_info(bvid)


def get_video_stat(bvid: str) -> Optional[Dict[str, Any]]:
    """模块级便捷函数：获取视频统计数据"""
    return _get_api().get_video_stat(bvid)


def get_video_viewers(bvid: str, cid: int) -> Optional[Dict[str, Any]]:
    """模块级便捷函数：获取视频观看人数"""
    return _get_api().get_video_viewers(bvid, cid)


def get_up_info(uid: int) -> Optional[Dict[str, Any]]:
    """模块级便捷函数：获取UP主信息"""
    return _get_api().get_up_info(uid)


def get_up_stat(uid: int) -> Optional[Dict[str, Any]]:
    """模块级便捷函数：获取UP主统计数据"""
    return _get_api().get_up_stat(uid)


def close() -> None:
    """模块级便捷函数：关闭 API 实例"""
    _get_api().close()


# 模块级便捷属性代理（from core import bilibili_api 导入的是模块而非实例）
def __getattr__(name: str) -> Any:
    """模块级属性代理，提供 bilibili_api 和 proxy_manager 的便捷访问"""
    if name == "bilibili_api":
        return _get_api()
    if name == "proxy_manager":
        return _get_api().proxy_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
