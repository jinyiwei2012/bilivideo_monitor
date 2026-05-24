"""
B站API模块 - 封装B站相关接口
增强版：支持获取观看人数、412错误重试与绕过机制
"""

import requests
import time
import math
import random
import logging
from utils import project_path
import threading
import warnings
from typing import Dict, List, Optional, Any, Tuple

from core.proxy_manager import ProxyManager

# Suppress InsecureRequestWarning for SOCKS/HTTP proxies using self-signed certs
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BilibiliAPIError(Exception):
    """B站API异常基类"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class RateLimitError(BilibiliAPIError):
    """频率限制错误 (412)"""


class BilibiliAPI:
    """B站API封装类 - 支持重试与绕过412错误"""

    BASE_URL = "https://api.bilibili.com"
    SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
    VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"
    VIEWERS_URL = "https://api.bilibili.com/x/player/online/total"
    DANMAKU_URL = "https://api.bilibili.com/x/v1/dm/list.so"
    COMMENT_URL = "https://api.bilibili.com/x/v2/reply/main"
    POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"

    # wbi 密钥（运行时刷新）
    _wbi_key = None

    # 多个User-Agent轮换使用
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    # 默认请求头
    BASE_HEADERS = {
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def __init__(self):
        self.session = requests.Session()

        # 连接池复用：每个 host 最多 10 个连接，减少 TCP 握手开销
        from requests.adapters import HTTPAdapter

        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)  # 重试由 _request 统一管理
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._update_headers()

        # 重试配置
        self.max_retries = 3
        self.base_retry_delay = 2  # 基础重试延迟（秒）
        self.max_retry_delay = 60  # 最大重试延迟（秒）

        # 代理管理器
        self.proxy_manager = ProxyManager()

        # 全局限流状态
        self._consecutive_412_errors = 0
        self._last_request_time = 0
        self._min_request_interval = 0.5  # 最小请求间隔（秒）

        # 公开 API 复用 Session（首次调用时懒创建）
        self._public_session = None
        self._interval_lock = threading.Lock()  # 线程安全保护

        # cookie支持
        self._cookies: Dict = {}
        # 扫码登录刷新凭证（快过期时自动续签）
        self._refresh_token: str = ""
        self._cfg_path: str = ""

        # 启动时加载已保存的 Cookie 和代理
        self._load_saved_network_config()
        # 为每个代理绑定一个固定UA（启动时生成一组）
        self.proxy_manager.init_ua_bindings()

    def _load_saved_network_config(self):
        """从 network_config.json 加载已保存的 Cookie、代理和刷新凭证"""
        try:
            import json
            import os

            cfg_path = project_path("data", "network_config.json")
            self._cfg_path = cfg_path
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    net_cfg = json.load(f)
                cookies = net_cfg.get("cookies", {})
                if cookies:
                    self._cookies = cookies
                    self.session.cookies.update(cookies)
                    logger.debug(f"已加载 {len(cookies)} 个 Cookie")
                self._refresh_token = net_cfg.get("refresh_token", "")
                if self._refresh_token:
                    logger.debug("已加载 Cookie 刷新凭证")
                proxy_urls = net_cfg.get("proxies", [])
                if proxy_urls:
                    for p in proxy_urls:
                        self.proxy_manager.add_proxy({"http": p, "https": p})
                    logger.debug(f"已加载 {len(proxy_urls)} 个代理")
        except Exception as e:
            logger.warning(f"加载网络配置失败: {e}")

    def _save_network_config(self):
        """将当前 Cookie、代理和刷新凭证持久化到 network_config.json"""
        try:
            import json
            import os

            if not self._cfg_path:
                self._cfg_path = project_path("data", "network_config.json")
            os.makedirs(os.path.dirname(self._cfg_path), exist_ok=True)

            # 读取已有配置，保留未知字段
            cfg = {}
            if os.path.exists(self._cfg_path):
                with open(self._cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            cfg["cookies"] = self._cookies
            cfg["refresh_token"] = self._refresh_token
            with open(self._cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.debug("网络配置已保存")
        except Exception as e:
            logger.warning("保存网络配置失败: %s", e)

    def _update_headers(self, extra_headers: Dict = None):
        """更新请求头"""
        headers = self.BASE_HEADERS.copy()
        headers["User-Agent"] = random.choice(self.USER_AGENTS)
        if extra_headers:
            headers.update(extra_headers)
        self.session.headers.update(headers)

    def _rotate_user_agent(self):
        """轮换User-Agent"""
        self.session.headers["User-Agent"] = random.choice(self.USER_AGENTS)
        logger.debug(f"User-Agent已更换: {self.session.headers['User-Agent'][:50]}...")

    def set_cookies(self, cookies: Dict):
        """设置Cookie"""
        self._cookies = cookies
        self.session.cookies.update(cookies)
        logger.info("已设置Cookie")

    def set_refresh_token(self, token: str):
        """设置刷新凭证"""
        self._refresh_token = token
        self._save_network_config()
        logger.debug("已保存 Cookie 刷新凭证")

    def get_refresh_token(self) -> str:
        return self._refresh_token

    def _on_request_failure(self, proxy_idx: Optional[int] = None):
        """标记请求失败：委托 ProxyManager 处理并更新 session UA"""
        new_ua = self.proxy_manager.on_request_failure(proxy_idx)
        if new_ua:
            self.session.headers["User-Agent"] = new_ua

    def add_proxy(self, proxy: Dict):
        """添加代理（委托给 ProxyManager）"""
        self.proxy_manager.add_proxy(proxy)

    def clear_proxies(self):
        """清空代理列表（委托给 ProxyManager）"""
        self.proxy_manager.clear_proxies()

    def _ensure_min_interval(self):
        """确保请求间隔（线程安全）"""
        with self._interval_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
            self._last_request_time = time.time()

    def _is_412_error(self, data: Dict) -> bool:
        """检查是否是412频率限制错误"""
        if isinstance(data, dict):
            code = data.get("code")
            # -412 或其他风控相关错误码
            return code in [-412, -509, -10403] or "请求过于频繁" in str(data.get("message", ""))
        return False

    def _get_error_info(self, data: Dict) -> Tuple[int, str]:
        """获取错误信息"""
        return data.get("code", -1), data.get("message", "未知错误")

    def _request(
        self, method: str, url: str, max_retries: int = None, skip_retry: bool = False, **kwargs
    ) -> Optional[Dict]:
        """
        发送HTTP请求 - 支持412错误重试

        Args:
            method: 请求方法
            url: 请求URL
            max_retries: 最大重试次数（None使用默认值）
            skip_retry: 是否跳过重试
            **kwargs: 其他requests参数

        Returns:
            请求成功的data数据，失败返回None
        """
        if max_retries is None:
            max_retries = self.max_retries

        last_error = None

        logger.debug("→ %s %s", method.upper(), url.split("?")[0])

        for attempt in range(max_retries + 1):
            try:
                self._ensure_min_interval()
                request_kwargs = self._prepare_request_kwargs(attempt, **kwargs)
                response = self.session.request(method, url, **request_kwargs)

                # 检查HTTP状态码
                if response.status_code == 412:
                    if self._handle_http_412_response(attempt, max_retries, skip_retry):
                        continue
                    return None

                response.raise_for_status()
                data = response.json()

                logger.debug("← %s %s → %s", method.upper(), url.split("?")[0], response.status_code)

                result, should_retry = self._handle_successful_response(data, attempt, max_retries, skip_retry)
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
                if response.status_code in [502, 503, 504]:
                    logger.error(f"服务器错误 {response.status_code} (第{attempt + 1}次尝试)")
                else:
                    logger.error(f"HTTP错误: {e}")
                    break

            except Exception as e:
                last_error = str(e)
                logger.error(f"请求异常: {e}")
                break

            if attempt < max_retries and not skip_retry:
                delay = self._get_retry_delay(attempt)
                logger.info(f"等待 {delay:.1f} 秒后重试...")
                time.sleep(delay)
                self._on_request_failure()

        logger.error(f"请求最终失败: {last_error}")
        return None

    def _prepare_request_kwargs(self, attempt: int, **kwargs) -> Dict:
        """构建请求参数：使用代理绑定UA，跳过失败过多的代理"""
        idx, proxy, ua = self.proxy_manager.get_proxy_binding()
        request_kwargs = {"timeout": 15, **kwargs}
        if proxy:
            request_kwargs["proxies"] = proxy
            # SOCKS/HTTP代理可能使用自签名证书，关闭SSL验证
            # 代理使用自签名证书，需关闭验证。确保代理 URL 可信。
            request_kwargs.setdefault("verify", False)  # nosec — local proxies use self-signed certs
            masked = self.proxy_manager.mask_url(proxy.get("http", ""))
            logger.debug(f"→ 请求代理: {masked}")
        else:
            logger.debug("→ 请求直连（无代理）")
        if ua:
            self.session.headers["User-Agent"] = ua
        return request_kwargs

    def _handle_http_412_response(self, attempt, max_retries, skip_retry) -> bool:
        """处理HTTP 412响应，返回True表示应重试"""
        self._consecutive_412_errors += 1
        logger.error(f"HTTP 412错误 (第{attempt + 1}次尝试)")
        if attempt < max_retries and not skip_retry:
            delay = self._get_retry_delay(attempt)
            logger.info(f"等待 {delay:.1f} 秒后重试...")
            time.sleep(delay)
            self._on_request_failure()
            return True
        return False

    def _handle_successful_response(self, data, attempt, max_retries, skip_retry):
        """处理成功获取的JSON响应，返回 (result_data, should_retry)"""
        if not isinstance(data, dict):
            return data, False

        api_code = data.get("code", 0)

        if api_code == 0:
            self._consecutive_412_errors = 0
            return data.get("data"), False

        if self._is_412_error(data):
            self._consecutive_412_errors += 1
            error_code, error_msg = self._get_error_info(data)
            logger.error(f"B站API 412错误: {error_msg} (第{attempt + 1}次尝试)")
            if attempt < max_retries and not skip_retry:
                delay = self._get_retry_delay(attempt)
                logger.info(f"等待 {delay:.1f} 秒后重试...")
                time.sleep(delay)
                self._apply_bypass_measures(attempt)
                return None, True
            return None, False

        if api_code != 0:
            logger.error(f"API错误 [{api_code}]: {data.get('message', '')}")

        return data.get("data") if "data" in data else None, False

    def _request_public(self, method: str, url: str, **kwargs) -> Any:
        """使用复用 Session 请求公开 API（免登录回退，支持代理绑定）"""
        import requests as _req

        if self._public_session is None:
            self._public_session = _req.Session()
            adapter = _req.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
            self._public_session.mount("https://", adapter)
            self._public_session.mount("http://", adapter)

        # 每次按当前代理绑定刷新 UA + 代理
        idx, proxy, ua = self.proxy_manager.get_proxy_binding()
        self._public_session.headers.update(
            {
                "User-Agent": ua or random.choice(self.USER_AGENTS),
                "Referer": "https://www.bilibili.com/",
            }
        )
        if proxy:
            self._public_session.proxies.update(proxy)
            kwargs.setdefault("verify", False)  # nosec
        elif self._public_session.proxies:
            self._public_session.proxies.clear()

        logger.debug("→ [public] %s %s", method.upper(), url.split("?")[0])
        try:
            resp = self._public_session.request(method, url, timeout=15, **kwargs)
            logger.debug("← [public] %s", resp.status_code)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data")
        except Exception as e:
            logger.debug(f"公共API请求失败: {e}")
            return None
        finally:
            self._public_session.close()
        return None

    def _get_retry_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        # 基础延迟 * 2^attempt + 随机抖动
        base_delay = self.base_retry_delay * (2**attempt)
        jitter = random.uniform(0, base_delay * 0.5)
        delay = min(base_delay + jitter, self.max_retry_delay)
        return delay

    def _apply_bypass_measures(self, attempt: int):
        """
        应用绕过措施

        按顺序尝试不同的绕过方法：
        1. 更换User-Agent
        2. 增加请求间隔
        3. 更换代理（如果有）
        4. 临时禁用cookie
        """
        measures = []

        # 1. 更换User-Agent（当前代理绑定新UA）
        self._on_request_failure()
        measures.append("已更换User-Agent")

        # 2. 临时增加最小请求间隔
        if attempt >= 1:
            old_interval = self._min_request_interval
            self._min_request_interval = min(old_interval * 2, 5.0)
            measures.append(f"请求间隔: {old_interval:.1f}s -> {self._min_request_interval:.1f}s")

        # 3. 更换代理
        if self.proxy_manager.proxies:
            new_proxy = self.proxy_manager.get_next_proxy()
            masked = self.proxy_manager.mask_url(new_proxy.get("http", "N/A"))
            measures.append(f"更换代理: {masked}")

        logger.info(f"绕过措施: {', '.join(measures)}")

    def bypass_412_with_retry(self, func, *args, **kwargs) -> Optional[Any]:
        """
        使用重试机制执行函数（用于需要多次尝试的操作）

        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值，失败返回None
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
        """搜索视频"""
        params = {"keyword": keyword, "search_type": "video", "page": page, "pagesize": page_size}
        data = self._request("GET", self.SEARCH_URL, params=params)
        if data and "result" in data:
            return data["result"]
        return []

    def get_video_info(self, bvid: str) -> Optional[Dict]:
        """获取视频详细信息"""
        params = {"bvid": bvid}
        return self._request("GET", self.VIDEO_URL, params=params)

    def get_video_viewers(self, bvid: str, cid: int = None) -> Optional[Dict]:
        """获取视频在线观看人数"""
        try:
            if cid is None:
                video_info = self.get_video_info(bvid)
                if video_info:
                    cid = video_info.get("cid", 0)
                else:
                    return None

            params = {"bvid": bvid, "cid": cid}
            data = self._request("GET", self.VIEWERS_URL, params=params)

            if data:
                return {
                    "total": data.get("total", 0),
                    "count": data.get("count", 0),
                    "show_switch": data.get("show_switch", {}),
                }
        except Exception as e:
            logger.error(f"获取观看人数失败: {type(e).__name__}")
        return None

    def get_video_full_data(self, bvid: str) -> Optional[Dict]:
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
            "viewers_total": viewers_data.get("total", 0) if viewers_data else 0,
            "viewers_web": viewers_data.get("count", 0) if viewers_data else 0,
            "viewers_app": (viewers_data.get("total", 0) - viewers_data.get("count", 0)) if viewers_data else 0,
        }

    # ── UP主相关 ──────────────────────────────────────────
    def search_up_users(self, keyword: str, page: int = 1, order: str = "fans") -> List[Dict]:
        """多源搜索UP主"""
        from core.up_fetcher import search_up_users_multi

        return search_up_users_multi(keyword, page, self._own_search_up_users)

    def _own_search_up_users(self, keyword: str, page: int) -> List[Dict]:
        """自有 API 实现：按用户名搜索UP主"""
        url = f"{self.BASE_URL}/x/web-interface/wbi/search/type"
        params = {
            "search_type": "bili_user",
            "keyword": keyword,
            "page": page,
            "user_type": 1,
        }
        params = self._wbi_sign(params)
        data = self._request("GET", url, params=params)

        if data is None:
            url2 = f"{self.BASE_URL}/x/web-interface/search/type"
            params2 = {"search_type": "bili_user", "keyword": keyword, "page": page}
            data = self._request_public("GET", url2, params=params2)

        if data and "result" in data:
            return data["result"]
        return []

    def get_up_info(self, uid: int) -> Optional[Dict]:
        """多源获取UP主基本信息（优先无Cookie请求避免412）"""
        from core.up_fetcher import get_up_info_multi

        return get_up_info_multi(uid, self._own_get_up_info)

    def _own_get_up_info(self, uid: int) -> Optional[Dict]:
        """自有 API 实现：获取UP主基本信息"""
        data = self._request_public("GET", f"{self.BASE_URL}/x/space/acc/info", params={"mid": uid})
        if data is None:
            data = self._request("GET", f"{self.BASE_URL}/x/space/acc/info", params={"mid": uid})
        if data:
            return {
                "uid": data.get("mid", uid),
                "name": data.get("name", ""),
                "face": data.get("face", ""),
                "sign": data.get("sign", ""),
                "level": data.get("level", 0),
                "follower_count": data.get("fans", 0) or data.get("follower", 0),
                "video_count": data.get("video_count", data.get("videos", 0)),
                "official_verify": data.get("official_verify", {}),
                "nameplate": data.get("nameplate", {}),
            }
        return None

    def _calc_up_stat_from_videos(self, uid: int, max_pages: int = 5) -> Optional[Dict]:
        """从UP主视频列表逐页汇总总播放量和总点赞数（兜底方案）"""
        total_views = 0
        total_likes = 0
        try:
            for page in range(1, max_pages + 1):
                url = f"{self.BASE_URL}/x/space/arc/search"
                params = {"mid": uid, "pn": page, "ps": 30}
                data = self._request_public("GET", url, params=params)
                if data is None:
                    data = self._request("GET", url, params=params)
                if not data:
                    break
                vlist = []
                if "list" in data and "vlist" in data["list"]:
                    vlist = data["list"]["vlist"]
                elif "vlist" in data:
                    vlist = data["vlist"]
                if not vlist:
                    break
                for v in vlist:
                    total_views += int(v.get("play", 0))
                    total_likes += int(v.get("like", 0))
                if len(vlist) < 30:
                    break
            if total_views > 0:
                return {"total_views": total_views, "total_likes": total_likes}
        except Exception as e:
            logger.warning("从视频列表汇总数据失败 UID:%s: %s", uid, e)
        return None

    def get_up_videos(self, uid: int, page: int = 1, page_size: int = 30) -> List[Dict]:
        """获取UP主视频列表"""
        url = f"{self.BASE_URL}/x/space/arc/search"
        params = {"mid": uid, "pn": page, "ps": page_size}
        data = self._request("GET", url, params=params)
        if data and "list" in data and "vlist" in data["list"]:
            return data["list"]["vlist"]
        if data and "vlist" in data:
            return data["vlist"]
        return []

    def get_up_stat(self, uid: int) -> Optional[Dict]:
        """多源获取UP主统计数据（总播放/总点赞/粉丝趋势）"""
        from core.up_fetcher import get_up_stat_multi

        return get_up_stat_multi(uid, self._own_get_up_stat)

    def _own_get_up_stat(self, uid: int) -> Optional[Dict]:
        """自有 API 实现：获取UP主统计数据"""
        data = self._request("GET", f"{self.BASE_URL}/x/space/upstat", params={"mid": uid})
        if data is None:
            data = self._request_public("GET", f"{self.BASE_URL}/x/space/upstat", params={"mid": uid})
        if data:
            return {
                "total_views": data.get("archive", {}).get("view", 0),
                "total_likes": data.get("archive", {}).get("like", 0),
                "follower_change": data.get("follower_change", data.get("follower", 0)),
                "follower_count": (
                    data.get("follower", {}).get("follower", 0)
                    if isinstance(data.get("follower"), dict)
                    else data.get("follower", 0)
                ),
            }
        logger.info("upstat 接口不可用，尝试从视频列表汇总总播放量 UID:%s", uid)
        return self._calc_up_stat_from_videos(uid)

    # ── WBI签名 ───────────────────────────────────────────
    def _refresh_wbi_key(self):
        """刷新 WBI 密钥（从 nav 接口获取）"""
        try:
            nav_url = f"{self.BASE_URL}/x/web-interface/nav"
            data = self._request("GET", nav_url, skip_retry=True)
            if data and "wbi_img" in data:
                img_url = data["wbi_img"]["img_url"]
                sub_url = data["wbi_img"]["sub_url"]
                import re

                img_key = re.search(r"/([^/]+)\.png", img_url)
                sub_key = re.search(r"/([^/]+)\.png", sub_url)
                if img_key and sub_key:
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
        """为请求参数添加 WBI 签名"""
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

    # ── 弹幕/评论 ─────────────────────────────────────────
    def get_video_danmaku(self, oid: int) -> List[Dict]:
        """获取视频弹幕（XML接口，oid 为 cid）

        Returns:
            [{"text": str, "timestamp": int, "mode": int, "color": int}, ...]
        """
        try:
            logger.debug("→ GET %s?oid=%s", self.DANMAKU_URL, oid)
            resp = self.session.get(
                self.DANMAKU_URL,
                params={"oid": oid},
                headers={"User-Agent": random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"},
                timeout=15,
            )
            logger.debug("← GET %s → %s", self.DANMAKU_URL.split("?")[0], resp.status_code)
            if resp.status_code != 200:
                return []
            import xml.etree.ElementTree as ET

            parser = ET.XMLParser(resolve_entities=False)
            root = ET.fromstring(resp.content, parser)  # nosec B314
            danmaku = []
            for d in root.findall(".//d"):
                p = d.get("p", "")
                parts = p.split(",")
                danmaku.append(
                    {
                        "text": d.text or "",
                        "timestamp": float(parts[0]) if len(parts) > 0 else 0,
                        "mode": int(parts[1]) if len(parts) > 1 else 1,
                        "color": int(parts[2]) if len(parts) > 2 else 16777215,
                    }
                )
            return danmaku
        except Exception as e:
            logger.error(f"获取弹幕失败: {e}")
            return []

    def get_video_comments(self, aid: int, limit: int = 20) -> List[Dict]:
        """获取视频评论（需WBI签名），支持翻页

        Args:
            aid: 视频 aid
            limit: 最大获取条数，默认 20（一页）。设为 0 获取全量（最多 5000 条）

        Returns:
            [{"content": str, "like": int, "ctime": int, "uname": str}, ...]
        """
        max_pages = 50 if limit == 0 else max(1, math.ceil(limit / 20))
        max_pages = min(max_pages, 250)  # 最多 5000 条
        all_replies = []

        for page in range(1, max_pages + 1):
            params = {"oid": aid, "type": 1, "pn": page, "ps": 20, "sort": 2}
            params = self._wbi_sign(params)
            data = self._request("GET", self.COMMENT_URL, params=params)
            if not data or "replies" not in data or not data["replies"]:
                break

            for r in data["replies"]:
                all_replies.append(
                    {
                        "content": r.get("content", {}).get("message", ""),
                        "like": r.get("like", 0),
                        "ctime": r.get("ctime", 0),
                        "uname": r.get("member", {}).get("uname", ""),
                        "mid": r.get("mid", 0),
                    }
                )

            if limit > 0 and len(all_replies) >= limit:
                return all_replies[:limit]

            self._ensure_min_interval()

        return all_replies[:limit] if limit > 0 else all_replies

    # ── 热门视频 ─────────────────────────────────────────
    def get_popular_videos(self, pn: int = 1, ps: int = 20) -> List[Dict]:
        """获取热门视频列表"""
        data = self._request("GET", self.POPULAR_URL, params={"pn": pn, "ps": ps})
        if data and "list" in data:
            return data["list"]
        return []

    def get_weekly_series(self, number: int = None) -> List[Dict]:
        """获取每周必看列表（自动获取最新期数）"""
        # 先获取可用期数列表
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
            return data["list"]
        return []

    def get_status(self) -> Dict:
        """获取API状态信息"""
        # 验证登录状态
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
                    # nav 返回了有效响应但未登录 — API 可能拒绝了这个 cookie
                    # 但仍标记为有 cookie，只是登录验证失败
                    logger.debug("nav 接口返回未登录，Cookie 可能已过期")
            except Exception as e:
                # API 调用异常（网络错误等），但有 cookie，标记为待验证
                logger.debug(f"登录验证请求失败: {e}")
        else:
            # 尝试记住上次的 cookies（即使 session 里没有）
            has_sessdata = bool(self._cookies.get("SESSDATA"))

        return {
            "consecutive_412_errors": self._consecutive_412_errors,
            "min_request_interval": self._min_request_interval,
            "proxy_count": len(self.proxy_manager.proxies),
            "has_cookies": bool(self._cookies),
            "has_sessdata": bool(has_sessdata),
            "is_login": login_status,
            "login_name": login_name,
        }

    def reset_status(self):
        """重置状态（用于连续失败后的恢复）"""
        self._consecutive_412_errors = 0
        self._min_request_interval = 0.5
        logger.info("API状态已重置")

    def close(self):
        """关闭 HTTP Session，释放连接池。"""
        try:
            self.session.close()
        except Exception as e:
            logger.debug("关闭HTTP Session失败: %s", e)

    # ── QR码登录 ─────────────────────────────────────────
    def get_qrcode_login_url(self) -> Optional[Dict]:
        """获取二维码登录地址（使用独立 session，避免旧 Cookie 干扰）"""
        import requests as _req

        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        clean_session = _req.Session()
        clean_session.headers.update(
            {"User-Agent": random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"}
        )
        try:
            logger.debug("→ GET passport.bilibili.com/qrcode/generate")
            resp = clean_session.get(url, timeout=15)
            logger.debug("← passport.bilibili.com/qrcode/generate → %s", resp.status_code)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                return {"url": d.get("url", ""), "qrcode_key": d.get("qrcode_key", "")}
        except Exception as e:
            logger.warning(f"获取二维码失败: {e}")
            return None
        finally:
            clean_session.close()
        return None

    def poll_qrcode_login(self, qrcode_key: str) -> Dict:
        """轮询二维码扫码状态

        Args:
            qrcode_key: get_qrcode_login_url 返回的 key

        Returns:
            {"status": int, "message": str, "cookies": dict}
            status: 0=未扫码, 1=已扫码待确认, 2=已确认/成功, -1=已过期
        """
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        result = {"status": 0, "message": "等待扫码", "cookies": {}}
        try:
            logger.debug("→ GET passport.bilibili.com/qrcode/poll")
            resp = self.session.get(
                url,
                params={"qrcode_key": qrcode_key},
                headers={
                    "User-Agent": random.choice(self.USER_AGENTS),
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=15,
            )
            logger.debug("← passport.bilibili.com/qrcode/poll → %s", resp.status_code)
            if resp.status_code != 200:
                result["message"] = f"HTTP {resp.status_code}"
                return result
            data = resp.json()
            code = data.get("code", -1)

            if code == 86038:
                result["status"] = -1
                result["message"] = "二维码已过期"
                return result

            if code != 0:
                result["message"] = data.get("message", f"错误码 {code}")
                return result

            d = data.get("data", {})
            # B站新API: status 可能是整数 (0=等待, 1=已扫码, 2=已确认)
            raw_status = d.get("status", False)
            if isinstance(raw_status, int):
                if raw_status == 2:
                    result["status"] = 2
                    result["message"] = "登录成功"
                elif raw_status == 1:
                    result["status"] = 1
                    result["message"] = d.get("message", "已扫码，请在手机上确认")
                    return result
                else:
                    result["message"] = d.get("message", "等待扫码")
                    return result
            elif raw_status is True:
                result["status"] = 2
                result["message"] = "登录成功"
            else:
                result["status"] = 1 if d.get("message", "") == "已扫码" else 0
                result["message"] = d.get("message", "等待扫码")
                return result

            # ── 登录成功，提取 Cookie ──
            cookies = self._extract_login_cookies(resp, d)
            if cookies:
                self.set_cookies(cookies)
                result["cookies"] = cookies
            # 捕获刷新凭证，用于后续自动续签
            refresh_token = d.get("refresh_token", "")
            if refresh_token:
                self.set_refresh_token(refresh_token)
                result["refresh_token"] = refresh_token
        except Exception as e:
            result["message"] = f"轮询异常: {e}"
        return result

    @staticmethod
    def _extract_login_cookies(resp, data: dict) -> dict:
        """从登录响应中提取 Cookie（多种回退方式）"""
        cookies = {}
        from urllib.parse import urlparse, parse_qs

        # 方式1: 从 data.url 中提取 token
        redirect_url = data.get("url", "")
        if redirect_url:
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)
            for key in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                val = params.get(key, [None])[0]
                if val:
                    cookies[key] = val

        # 方式2: 从 Set-Cookie 响应头
        if not cookies:
            set_cookie = resp.headers.get("Set-Cookie", "")
            for part in set_cookie.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    k = k.strip()
                    if k in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                        cookies[k] = v.split(";")[0].split(",")[0].strip()

        # 方式3: 从 resp.cookies (http.cookiejar)
        if not cookies:
            for k in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                if k in resp.cookies:
                    cookies[k] = resp.cookies[k]

        return cookies

    # ── 密码登录 ────────────────────────────────────────────

    def login_with_password(self, username: str, password: str, captcha: str = "",
                            captcha_type: int = 0) -> Dict:
        """使用账号密码登录 B站

        B站登录流程：
        1. GET /api/v2/oauth2/getKey → 获取 RSA 公钥 + hash
        2. RSA PKCS1_v1_5 加密 hash+password
        3. POST /api/v2/oauth2/login → 获取 Cookie

        Args:
            username: 账号
            password: 密码
            captcha: 验证码（短信验证码，首次调用填空）
            captcha_type: 验证码类型（6=短信验证码，0=无）

        Returns:
            {"code": 0, "cookies": {...}, "refresh_token": "", "message": "",
             "need_captcha": False, "captcha_type": 0}
        """
        result: Dict = {"code": -1, "cookies": {}, "refresh_token": "", "message": "",
                        "need_captcha": False, "captcha_type": 0}
        try:
            # Step 1: 获取 RSA 公钥
            key_resp = requests.get(
                "https://passport.bilibili.com/api/v2/oauth2/getKey",
                headers={"User-Agent": random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"},
                timeout=15,
            )
            if key_resp.status_code != 200:
                result["message"] = f"获取密钥失败: HTTP {key_resp.status_code}"
                return result
            key_data = key_resp.json()
            if key_data.get("code") != 0:
                result["message"] = f"获取密钥失败: {key_data.get('message', '')}"
                return result
            key_info = key_data.get("data", {})
            rsa_key = key_info.get("key", "")
            rsa_hash = key_info.get("hash", "")

            # Step 2: RSA 加密密码
            from Cryptodome.PublicKey import RSA as _RSA
            from Cryptodome.Cipher import PKCS1_v1_5 as _PKCS1

            pubkey = _RSA.import_key(rsa_key)
            cipher = _PKCS1.new(pubkey)
            encrypted = cipher.encrypt((rsa_hash + password).encode("utf-8"))
            import base64 as _b64

            encrypted_password = _b64.b64encode(encrypted).decode("utf-8")

            # Step 3: 登录
            login_data = {
                "username": username,
                "password": encrypted_password,
                "keep": "true",
            }
            if captcha:
                login_data["captcha"] = captcha
            if captcha_type:
                login_data["captcha_type"] = str(captcha_type)

            login_resp = requests.post(
                "https://passport.bilibili.com/api/v2/oauth2/login",
                data=login_data,
                headers={
                    "User-Agent": random.choice(self.USER_AGENTS),
                    "Referer": "https://www.bilibili.com/",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=30,
            )
            if login_resp.status_code != 200:
                result["message"] = f"登录失败: HTTP {login_resp.status_code}"
                return result
            login_data = login_resp.json()
            if login_data.get("code") != 0:
                result["code"] = login_data.get("code", -1)
                result["message"] = login_data.get("message", "登录失败")
                # 常见错误: -629 = 需要验证码
                if login_data.get("code") == -629:
                    body = login_data.get("data", {})
                    result["need_captcha"] = True
                    # B站返回的验证码类型: 6=短信验证码, geetest=滑块
                    ct = body.get("captcha_type", 0)
                    result["captcha_type"] = ct
                    result["captcha_url"] = body.get("url", "")
                    result["captcha_phone"] = body.get("phone", "")
                    result["message"] = body.get("message", "需要安全验证，请完成验证后再登录")
                elif login_data.get("code") == -1057:
                    result["message"] += "，请检查账号密码"
                return result

            # 从 token_info 直接提取
            cookies = {}
            for k in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                val = token_info.get(k, "")
                if val:
                    cookies[k] = val

            # 回退到 header/cookiejar 方式
            if not cookies:
                cookies = self._extract_login_cookies(login_resp, token_info)

            if cookies:
                self.set_cookies(cookies)

            refresh_token = token_info.get("refresh_token", "")
            if refresh_token:
                self.set_refresh_token(refresh_token)

            result["code"] = 0
            result["cookies"] = cookies
            result["refresh_token"] = refresh_token
            result["message"] = "登录成功"
        except Exception as e:
            result["message"] = f"登录异常: {e}"
        return result

    # ── Cookie 刷新 ────────────────────────────────────────────

    def _refresh_cookies(self) -> bool:
        """使用 refresh_token 刷新过期的 SESSDATA

        B站刷新流程：
        1. POST /x/passport-login/web/cookie/refresh → 获取新 Cookie
        2. 若 data.status == 0 需 POST /confirm 确认

        Returns:
            True 刷新成功，False 失败
        """
        if not self._refresh_token or not self._cookies.get("bili_jct"):
            return False

        csrf = self._cookies["bili_jct"]
        url = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
        try:
            resp = self.session.post(
                url,
                data={"csrf": csrf, "refresh_token": self._refresh_token},
                headers={"User-Agent": random.choice(self.USER_AGENTS), "Referer": "https://www.bilibili.com/"},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("Cookie 刷新失败: HTTP %s", resp.status_code)
                return False
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("Cookie 刷新失败: %s", data.get("message", ""))
                return False
            d = data.get("data", {})
            refresh_status = d.get("status", 0)
            # 提取新 Cookie
            new_cookies = self._extract_login_cookies(resp, d)
            if not new_cookies and "cookie_info" in d:
                for c in d["cookie_info"].get("cookies", []):
                    name = c.get("name", "")
                    if name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                        new_cookies[name] = c.get("value", "")
            if not new_cookies:
                logger.warning("Cookie 刷新失败: 未提取到新 Cookie")
                return False

            # 需要确认
            if refresh_status == 0:
                confirm_url = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh/confirm"
                confirm_resp = self.session.post(
                    confirm_url,
                    data={"csrf": new_cookies.get("bili_jct", csrf), "refresh_token": self._refresh_token},
                    headers={
                        "User-Agent": random.choice(self.USER_AGENTS),
                        "Referer": "https://www.bilibili.com/",
                    },
                    timeout=15,
                )
                if confirm_resp.status_code == 200:
                    confirm_data = confirm_resp.json()
                    if confirm_data.get("code") == 0:
                        # 确认后可能再返回一次 Cookie
                        confirm_d = confirm_data.get("data", {})
                        confirm_cookies = self._extract_login_cookies(confirm_resp, confirm_d)
                        if confirm_cookies:
                            new_cookies.update(confirm_cookies)

            # 应用新 Cookie
            self._cookies.update(new_cookies)
            self.session.cookies.update(new_cookies)
            self._save_network_config()
            logger.info("Cookie 已自动续签刷新")
            return True
        except Exception as e:
            logger.warning("Cookie 刷新异常: %s", e)
            return False

    def _try_auto_refresh_cookies(self) -> bool:
        """检查当前 Cookie 状态，快过期时自动刷新

        先通过 nav 接口验证登录状态，若 Cookie 失效但有 refresh_token 则自动刷新。

        Returns:
            True 刷新成功或无需刷新，False 刷新失败
        """
        has_sessdata = bool(self._cookies.get("SESSDATA"))
        if not has_sessdata:
            return True  # 没有 Cookie 也就不需要刷新

        # 验证登录状态
        try:
            nav = self._request("GET", f"{self.BASE_URL}/x/web-interface/nav", skip_retry=True)
            if nav and nav.get("isLogin"):
                return True  # Cookie 仍有效
        except Exception:
            pass

        # Cookie 可能已过期，尝试自动刷新
        if self._refresh_token:
            logger.info("Cookie 可能已过期，尝试自动续签...")
            return self._refresh_cookies()
        return False


# 全局API实例（惰性初始化）
_bilibili_api = None


def get_bilibili_api():
    """获取全局 BilibiliAPI 单例（惰性初始化）"""
    global _bilibili_api
    if _bilibili_api is None:
        _bilibili_api = BilibiliAPI()
        # 启动后静默检查 Cookie 有效性，过期且可续签则自动刷新
        try:
            _bilibili_api._try_auto_refresh_cookies()
        except Exception:
            pass
    return _bilibili_api
