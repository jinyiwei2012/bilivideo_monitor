"""
B站 API 模块 (BilibiliAPI)
===========================

本模块封装了与 B站 (Bilibili) 进行数据交互的所有核心功能，是系统的 API 网关层。

主要功能：
  1. HTTP 请求管理        — 连接池复用、UA 轮换、TLS 指纹伪装 (curl_cffi)
  2. 412 错误重试与绕过    — 指数退避、代理切换、buvid 随机化
  3. WBI 签名              — 为搜索等高级接口自动添加 w_rid 签名参数
  4. Cookie 管理            — 多账号支持、持久化、自动加载
  5. 统一数据获取接口      — 视频信息 / 统计数据 / 观看人数 / 热门 / 每周必看

架构说明：
  BilibiliAPI 通过多重继承组合了 4 个 Mixin 模块：
    - _RequestMixin       (bilibili_request.py)  — HTTP 请求核心逻辑
    - _AuthMixin          (bilibili_auth.py)     — 认证与账号管理
    - _VideoMixin         (bilibili_video.py)    — 视频相关接口
    - _UpMixin            (bilibili_up.py)       — UP 主相关接口

使用示例：
  from core import bilibili_api
  info = bilibili_api.get_video_info("BV1xx411c7mD")
"""

import requests
import time
import math
import random
import logging
import threading
import warnings
from typing import Dict, List, Optional, Any, Tuple

from core.proxy_manager import ProxyManager

# 抑制 SOCKS/HTTP 代理使用自签名证书时的 InsecureRequestWarning
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)


class BilibiliAPIError(Exception):
    """B站 API 异常基类

    封装 B站 API 返回的错误码和错误信息。

    Attributes:
        code: B站 API 返回的错误码（如 -412、-509 等）
        message: 错误描述信息
    """

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class RateLimitError(BilibiliAPIError):
    """频率限制错误（HTTP 412 或 API -412）

    当请求频率过高时，B站会返回 412 状态码或 API 错误码 -412。
    本系统通过指数退避 + UA 轮换 + 代理切换 + TLS 伪装来绕过此限制。
    """


class _CurlCffiResponse:
    """curl_cffi 响应适配器

    将 curl_cffi 库的 Response 对象包装为与 requests.Response 兼容的接口，
    以便在 _do_http_request 中统一处理两种 HTTP 客户端的响应。

    curl_cffi 用于 TLS 指纹伪装，模拟真实 Chrome 浏览器的 JA3 指纹，
    降低被 B站风控系统识别的概率。
    """

    def __init__(self, resp):
        """包装 curl_cffi Response 对象

        Args:
            resp: curl_cffi.requests.Response 实例
        """
        self.status_code = resp.status_code
        self.content = resp.content
        self.raw = resp.content
        self.text = resp.text
        self.headers = resp.headers
        self.url = str(resp.url)
        self.cookies = resp.cookies
        self._resp = resp

    def json(self, **kwargs):
        """解析 JSON 响应体（委托给原始 Response）"""
        return self._resp.json(**kwargs)

    def raise_for_status(self):
        """检查 HTTP 状态码，4xx/5xx 时抛出 HTTPError"""
        if self.status_code >= 400:
            from requests.exceptions import HTTPError
            raise HTTPError(f"HTTP {self.status_code}", response=self)


# 导入各个 Mixin 子模块（每个都定义了独立的方法，通过类属性赋值注入到 BilibiliAPI）
from core.bilibili_request import _RequestMixin
from core.bilibili_auth import _AuthMixin
from core.bilibili_video import _VideoMixin
from core.bilibili_up import _UpMixin


class BilibiliAPI(_RequestMixin, _AuthMixin, _VideoMixin, _UpMixin):
    """B站 API 封装类

    通过多重继承组合了请求、认证、视频、UP 主四类功能。
    支持：
      - TLS 指纹伪装 (curl_cffi chrome131)
      - 412 错误重试（指数退避 + UA/代理/buvid 轮换）
      - 多账号 Cookie 管理
      - 代理池管理

    使用全局单例模式，通过 get_bilibili_api() 获取全局实例。
    """

    # ── API 端点常量 ──────────────────────────────
    BASE_URL = "https://api.bilibili.com"
    SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
    VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"
    VIEWERS_URL = "https://api.bilibili.com/x/player/online/total"
    DANMAKU_URL = "https://api.bilibili.com/x/v1/dm/list.so"
    COMMENT_URL = "https://api.bilibili.com/x/v2/reply/main"
    POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"

    # WBI 签名密钥（运行时从 nav 接口刷新）
    _wbi_key = None

    # 多个 User-Agent 轮换使用（2026 版本，与 curl_cffi 默认 impersonate Chrome 版本对齐）
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    ]

    # 默认请求头（会与随机 UA 组合使用）
    BASE_HEADERS = {
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def __init__(self):
        """初始化 BilibiliAPI 实例

        执行以下初始化步骤：
        1. 创建 requests Session 并配置连接池（复用 TCP 连接）
        2. 初始化 curl_cffi 会话（TLS 指纹伪装）
        3. 设置随机 UA 请求头
        4. 配置重试参数和限流状态
        5. 加载已保存的 Cookie 和代理配置
        6. 初始化代理 UA 绑定
        """
        self.session = requests.Session()

        # 连接池复用：每个 host 最多 10 个连接，减少 TCP 握手开销
        from requests.adapters import HTTPAdapter

        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # 公共 API Session（免 Cookie，复用连接池，用于无需登录的接口）
        self._public_session = requests.Session()
        self._public_session.mount("https://", adapter)
        self._public_session.mount("http://", adapter)

        # curl_cffi Session（TLS 指纹伪装，主 API 路径优先使用）
        self._curl_session = None
        self._has_curl_cffi = False
        self._impersonate = ""
        self._init_curl_cffi()

        # 更新两个 Session 的默认请求头
        self._update_headers()
        self._update_public_headers()

        # 重试配置
        self.max_retries = 3
        self.base_retry_delay = 2
        self.max_retry_delay = 60

        # 代理管理器（独立模块，负责代理池的轮询、失败计数和自动清理）
        self.proxy_manager = ProxyManager()

        # 全局限流状态（用于自适应调整请求间隔）
        self._consecutive_412_errors = 0
        self._last_request_time = 0
        self._min_request_interval = 0.5
        self._interval_lock = threading.Lock()

        # Cookie 支持（多账号管理）
        self._cookies: Dict = {}
        self._refresh_token: str = ""
        self._accounts: list = []
        self._active_account_idx: int = -1
        self._account_name: str = "默认"

        # 随机 buvid（模拟不同设备指纹，降低 412 概率）
        # 每次初始化生成两个 buvid（buvid3 和 buvid4）
        self._buvid3 = self._gen_buvid()
        self._buvid4 = self._gen_buvid()

        # 启动时加载已保存的 Cookie 和代理配置
        self._load_saved_network_config()
        # 为已加载的代理绑定固定 UA（UA 与代理 IP 绑定，避免 IP 和 UA 不匹配）
        self.proxy_manager.init_ua_bindings()
        # 代理自动发现改由用户在设置界面手动触发，启动时不拉取

    @staticmethod
    def _gen_buvid() -> str:
        """生成随机 buvid（模拟浏览器设备指纹）

        buvid 是 B站用于追踪设备的标识符，格式为 32 位十六进制 + "infoc" 后缀。
        定期随机更换 buvid 可以降低被 B站风控系统关联的概率。

        Returns:
            32 位随机十六进制字符串 + "infoc"
        """
        import uuid as _uuid
        return _uuid.uuid4().hex.upper()[:16] + _uuid.uuid4().hex.upper()[:16] + "infoc"

    def _init_curl_cffi(self):
        """初始化 curl_cffi 会话（TLS 指纹伪装）

        curl_cffi 是一个支持 TLS 指纹自定义的 HTTP 客户端库。
        通过 impersonate="chrome131" 参数，可以让请求的 JA3/JA4 指纹
        看起来与 Chrome 131 浏览器完全一致，从而绕过 B站的反爬检测。
        """
        try:
            from curl_cffi import requests as _curl_req
            self._curl_session = _curl_req.Session(impersonate="chrome131")
            self._curl_session.headers.update({
                "Referer": "https://www.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            self._has_curl_cffi = True
            self._impersonate = "chrome131"
            logger.info("curl_cffi TLS 指纹伪装已启用 (impersonate=chrome131)")
        except ImportError:
            self._has_curl_cffi = False
            logger.info("curl_cffi 未安装，使用 requests 直连 (pip install curl_cffi)")

    @staticmethod
    def _sanitize_cookies(cookies: Dict) -> Dict:
        """清理 Cookie 值中非 Latin-1 字符，防止 requests 编码报错

        requests 库要求 Cookie 值必须是 Latin-1 兼容的字符串。
        B站某些 Cookie 可能包含非 Latin-1 字符（如中文字符），
        直接传入会触发 UnicodeEncodeError。

        Args:
            cookies: 原始 Cookie 字典

        Returns:
            清理后的 Cookie 字典（非 Latin-1 字符被替换为 ? 或忽略）
        """
        sanitized = {}
        for k, v in cookies.items():
            if isinstance(v, str):
                sanitized[k] = v.encode("latin-1", errors="replace").decode("latin-1")
            else:
                sanitized[k] = v
        return sanitized

    def _load_saved_network_config(self):
        """从 network_config.json 加载多账号 Cookie 和代理

        加载流程：
        1. 读取 data/network_config.json
        2. 解析 accounts 列表（多账号 Cookie）
        3. 根据 active_account 切换到当前活跃账号
        4. 兼容旧格式（单账号 cookies 对象）
        5. 加载代理列表到 ProxyManager
        """
        try:
            import json, os
            from utils.crypto import decrypt_dict

            # 配置文件路径：项目根目录/data/network_config.json
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "network_config.json")
            if not os.path.exists(cfg_path):
                return
            with open(cfg_path, "r", encoding="utf-8") as f:
                net_cfg = json.load(f)

            # 加载多账号列表
            self._accounts = net_cfg.get("accounts", [])
            if not self._accounts:
                # 旧格式兼容：单账号 cookies 对象
                cookies = net_cfg.get("cookies", {})
                if cookies:
                    decrypt_dict(cookies, "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
                    cookies = self._sanitize_cookies(cookies)
                    name = net_cfg.get("account_name", "默认")
                    self._accounts = [{"name": name, "cookies": cookies,
                                       "refresh_token": net_cfg.get("refresh_token", ""), "active": True}]

            # 根据 active_account 切换当前账号
            active_name = net_cfg.get("active_account", "")
            found = False
            for acc in self._accounts:
                # 解密敏感 Cookie 字段并清理非 Latin-1 字符
                acc["cookies"] = self._sanitize_cookies(decrypt_dict(acc.get("cookies", {}),
                    "SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid") if acc.get("cookies") else {})
                if acc["name"] == active_name:
                    self._cookies = dict(acc.get("cookies", {}))
                    self._refresh_token = acc.get("refresh_token", "")
                    self.session.cookies.update(self._cookies)
                    self._account_name = active_name
                    self._active_account_idx = self._accounts.index(acc)
                    found = True
            if not found and self._accounts:
                # 未找到标记为活跃的账号，默认切换到第一个
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

    def _update_headers(self, extra_headers: Dict = None):
        """更新 Session 请求头（随机选择 UA）

        每次调用会从 USER_AGENTS 列表中随机选取一个 UA，
        配合 BASE_HEADERS 组成完整的请求头。

        Args:
            extra_headers: 额外的自定义请求头（可选）
        """
        headers = self.BASE_HEADERS.copy()
        headers["User-Agent"] = random.choice(self.USER_AGENTS)
        if extra_headers:
            headers.update(extra_headers)
        self.session.headers.update(headers)

    def _on_request_failure(self, proxy_idx: Optional[int] = None):
        """标记请求失败：委托 ProxyManager 处理并更新 session 的 UA

        Args:
            proxy_idx: 失败的代理索引（可选），用于 ProxyManager 记录失败次数
        """
        new_ua = self.proxy_manager.on_request_failure(proxy_idx)
        if new_ua:
            self.session.headers["User-Agent"] = new_ua

    def add_proxy(self, proxy: Dict):
        """添加代理（委托给 ProxyManager）

        Args:
            proxy: 代理配置字典，格式为 {"http": "http://ip:port", "https": "http://ip:port"}
        """
        self.proxy_manager.add_proxy(proxy)

    def clear_proxies(self):
        """清空代理列表（委托给 ProxyManager）"""
        self.proxy_manager.clear_proxies()

    def bypass_412_with_retry(self, func, *args, **kwargs) -> Optional[Any]:
        """使用重试机制执行函数（用于需要多次尝试的操作）

        Args:
            func: 需要重试执行的函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行成功时返回其结果，所有重试均失败时返回 None
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

    def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> List[Dict]:
        """搜索视频（主路径 + 多源兜底）

        优先使用自有 API（WBI 签名），失败时回退到 bilibili-api-python 库。

        Args:
            keyword: 搜索关键词
            page: 页码（从 1 开始）
            page_size: 每页结果数量

        Returns:
            视频搜索结果列表，每个元素含 bvid、title、play 等字段
        """
        params = {"keyword": keyword, "search_type": "video", "page": page, "pagesize": page_size}
        data = self._request("GET", self.SEARCH_URL, params=params)
        if data and "result" in data:
            return data["result"]
        return self._search_videos_fallback(keyword, page, page_size)

    def _search_videos_fallback(self, keyword: str, page: int, page_size: int) -> List[Dict]:
        """使用 bilibili-api-python 库兜底搜索视频

        当自有 API 的 WBI 搜索接口不可用时，回退到第三方库的实现。
        """
        try:
            from bilibili_api import sync
            from bilibili_api.search import search_by_type
            from bilibili_api.search import SearchObjectType

            result = sync(search_by_type(keyword, SearchObjectType.VIDEO, page=page))
            if result and "result" in result:
                return result["result"]
        except ImportError:
            pass
        except Exception as e:
            logger.debug("bilibili-api 兜底搜索失败: %s", e)
        return []

    def get_video_full_data(self, bvid: str) -> Optional[Dict]:
        """获取视频完整数据（信息 + 统计 + 实时观看人数）

        一次性获取视频的标题、描述、封面、UP主、统计数据、
        在线观看人数等全部信息。

        Args:
            bvid: 视频 BV 号

        Returns:
            完整视频数据字典，包含 bvid, title, description, pic,
            owner, stat, viewers_total, viewers_web, viewers_app 等字段
        """
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
            "viewers_app": max(0, int(viewers_data.get("total", 0)) - int(viewers_data.get("count", 0))) if viewers_data else 0,
        }

    # ── WBI 签名 ───────────────────────────────────────────

    def _refresh_wbi_key(self):
        """刷新 WBI 签名密钥（从 nav 接口获取 img_url 和 sub_url）

        B站 WBI (WBI Sign) 是用于搜索等接口的反爬签名机制。
        密钥需要从 /x/web-interface/nav 接口的 wbi_img 中提取。
        密钥由 img_url 和 sub_url 中的文件名前缀拼接后取 MD5 得到。
        """
        try:
            nav_url = f"{self.BASE_URL}/x/web-interface/nav"
            data = self._request("GET", nav_url, skip_retry=True)
            if data and "wbi_img" in data:
                img_url = data["wbi_img"]["img_url"]
                sub_url = data["wbi_img"]["sub_url"]
                import re

                # 从 URL 中提取图片文件名前缀（不含 .png 扩展名）
                img_key = re.search(r"/([^/]+)\.png", img_url)
                sub_key = re.search(r"/([^/]+)\.png", sub_url)
                if img_key and sub_key:
                    # 将两个密钥片段拼接后取 MD5
                    mix = img_key.group(1) + sub_key.group(1)
                    import hashlib

                    self._wbi_key = hashlib.md5(mix.encode(), usedforsecurity=False).hexdigest()
                    return
            self._wbi_key = None
            logger.warning("WBI密钥刷新失败: 无法解析密钥图片URL")
        except Exception as e:
            self._wbi_key = None
            logger.warning(f"WBI密钥刷新失败: {e}")

    def _wbi_sign(self, params: dict) -> dict:
        """为请求参数添加 WBI 签名

        WBI 签名算法：
        1. 将参数按 key 排序
        2. 拼接成 query 字符串
        3. 追加 WBI 密钥
        4. 取 MD5 得到 w_rid
        5. 添加 wts（时间戳）和 w_rid 到参数中

        Args:
            params: 原始请求参数字典

        Returns:
            添加了 wts 和 w_rid 的参数副本
        """
        if not self._wbi_key:
            self._refresh_wbi_key()
        if not self._wbi_key:
            return params
        sorted_params = sorted(params.items())
        query = "&".join(f"{k}={v}" for k, v in sorted_params)
        query += self._wbi_key
        import hashlib

        wts = int(time.time())
        w_rid = hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()
        params["wts"] = wts
        params["w_rid"] = w_rid
        return params

    # ── 热门视频 ─────────────────────────────────────────

    def get_popular_videos(self, pn: int = 1, ps: int = 20) -> List[Dict]:
        """获取热门视频列表

        Args:
            pn: 页码（从 1 开始）
            ps: 每页数量

        Returns:
            热门视频列表
        """
        data = self._request("GET", self.POPULAR_URL, params={"pn": pn, "ps": ps})
        if data and "list" in data:
            return data["list"]
        return []

    def get_weekly_series(self, number: int = None) -> List[Dict]:
        """获取每周必看列表

        自动获取最新一期的每周必看，也可指定期数。
        先通过 series/list 获取各个期数的编号，再用 series/one 获取具体内容。

        Args:
            number: 期数编号，为 None 时自动获取最新期

        Returns:
            每周必看视频列表
        """
        series_list_url = f"{self.BASE_URL}/x/web-interface/popular/series/list"
        list_data = self._request("GET", series_list_url)
        if list_data and "list" in list_data and list_data["list"]:
            if number is None:
                # 取最新一期
                number = list_data["list"][0].get("number", number)
        if number is None:
            return []
        url = f"{self.BASE_URL}/x/web-interface/popular/series/one"
        params = {"number": number}
        data = self._request("GET", url, params=params)
        if data and "list" in data:
            return data["list"]
        return []

    def get_status(self) -> Dict:
        """获取 API 状态信息（用于 UI 显示当前系统健康状况）

        Returns:
            包含以下字段的状态字典：
              - consecutive_412_errors: 连续 412 错误次数
              - min_request_interval: 当前最小请求间隔
              - proxy_count: 代理池大小
              - has_cookies: 是否有 Cookie
              - has_sessdata: 是否有 SESSDATA（登录凭证）
              - has_buvid3: 是否有 buvid3（设备指纹）
              - is_login: 是否已登录
              - login_name: 登录用户名
        """
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
        }

    def reset_status(self):
        """重置 API 状态（用于连续失败后的恢复）

        将 412 错误计数归零，请求间隔恢复到默认值。
        通常在用户手动执行"恢复"操作时调用。
        """
        self._consecutive_412_errors = 0
        self._min_request_interval = 0.5
        logger.info("API状态已重置")

    def close(self):
        """关闭 HTTP Session，释放连接池资源

        应用退出时应调用此方法，避免连接泄漏。
        """
        try:
            self.session.close()
            self._public_session.close()
        except Exception as e:
            logger.debug("关闭HTTP Session失败: %s", e)


# ═══════════════════════════════════════════════════════════
# 全局 API 实例（延迟初始化 + 双检锁线程安全）
# ═══════════════════════════════════════════════════════════

_bilibili_api_instance = None
_bilibili_api_lock = threading.Lock()


def _get_api():
    """延迟获取/创建 BilibiliAPI 实例（双检锁线程安全）

    使用双重检查锁定模式，确保在多线程环境下只创建一个实例。
    BilibiliAPI 的初始化涉及网络请求（nav 接口），延迟初始化可避免拖慢模块导入速度。
    """
    global _bilibili_api_instance
    if _bilibili_api_instance is None:
        with _bilibili_api_lock:
            if _bilibili_api_instance is None:
                _bilibili_api_instance = BilibiliAPI()
    return _bilibili_api_instance


def get_bilibili_api() -> BilibiliAPI:
    """获取全局 BilibiliAPI 实例的公开函数

    Returns:
        BilibiliAPI 全局单例
    """
    return _get_api()


# ── 模块级便捷函数（兼容 from core import bilibili_api 调用方式）──

def get_video_info(bvid: str) -> Optional[Dict]:
    """模块级便捷函数：获取视频信息

    Args:
        bvid: 视频 BV 号

    Returns:
        视频信息字典，包含 title, desc, pic, owner, stat 等字段
    """
    return _get_api().get_video_info(bvid)


def get_video_stat(bvid: str) -> Optional[Dict]:
    """模块级便捷函数：获取视频统计数据

    Args:
        bvid: 视频 BV 号

    Returns:
        统计数据字典，包含 view, like, coin, favorite, share, danmaku, reply
    """
    return _get_api().get_video_stat(bvid)


def get_video_viewers(bvid: str, cid: int) -> Optional[Dict]:
    """模块级便捷函数：获取视频实时观看人数

    Args:
        bvid: 视频 BV 号
        cid: 视频分P ID

    Returns:
        观看人数字典，包含 total（总人数）和 count（web 端人数）
    """
    return _get_api().get_video_viewers(bvid, cid)


def get_up_info(uid: int) -> Optional[Dict]:
    """模块级便捷函数：获取 UP 主信息

    Args:
        uid: UP 主 UID

    Returns:
        UP 主信息字典，包含 name, face, sign, level, follower_count 等
    """
    return _get_api().get_up_info(uid)


def get_up_stat(uid: int) -> Optional[Dict]:
    """模块级便捷函数：获取 UP 主统计数据

    Args:
        uid: UP 主 UID

    Returns:
        UP 主统计数据字典，包含 total_views, total_likes 等
    """
    return _get_api().get_up_stat(uid)


def close():
    """模块级便捷函数：关闭全局 API 实例"""
    _get_api().close()


# 模块级便捷属性代理（from core import bilibili_api 导入的是模块而非实例）
def __getattr__(name):
    """模块级属性代理

    当通过 from core import bilibili_api 导入后，
    可以通过 bilibili_api.bilibili_api 访问实例，
    通过 bilibili_api.proxy_manager 访问代理管理器。

    这种设计让使用者无需关心单例创建过程：
      from core import bilibili_api
      stat = bilibili_api.status  # 自动调用 get_status()
    """
    if name == "bilibili_api":
        return _get_api()
    if name == "proxy_manager":
        return _get_api().proxy_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
