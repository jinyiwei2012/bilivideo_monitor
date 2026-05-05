"""
B站API模块 - 封装B站相关接口
增强版：支持获取观看人数、412错误重试与绕过机制
"""
import requests
import re
import time
import math
import random
import logging
import threading
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import quote
from functools import wraps

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
    pass


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
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    ]
    
    # 默认请求头
    BASE_HEADERS = {
        'Referer': 'https://www.bilibili.com/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
    }
    
    def __init__(self):
        self.session = requests.Session()
        # 连接池复用：每个 host 最多 10 个连接，减少 TCP 握手开销
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10,
                              max_retries=0)  # 重试由 _request 统一管理
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._update_headers()
        
        # 重试配置
        self.max_retries = 3
        self.base_retry_delay = 2  # 基础重试延迟（秒）
        self.max_retry_delay = 60  # 最大重试延迟（秒）
        
        # 代理配置
        self.proxies: List[Dict] = []
        self.current_proxy_index = 0
        
        # 全局限流状态
        self._consecutive_412_errors = 0
        self._last_request_time = 0
        self._min_request_interval = 0.5  # 最小请求间隔（秒）
        self._interval_lock = threading.Lock()  # 线程安全保护
        
        # cookie支持
        self._cookies: Dict = {}
        # 启动时加载已保存的 Cookie
        self._load_saved_cookies()

    def _load_saved_cookies(self):
        """从 network_config.json 加载已保存的 Cookie"""
        try:
            import json, os
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'config', 'network_config.json')
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    net_cfg = json.load(f)
                cookies = net_cfg.get("cookies", {})
                if cookies:
                    self._cookies = cookies
                    self.session.cookies.update(cookies)
                    logger.info(f"已加载 {len(cookies)} 个 Cookie")
        except Exception as e:
            logger.warning(f"加载 Cookie 失败: {e}")
    
    def _update_headers(self, extra_headers: Dict = None):
        """更新请求头"""
        headers = self.BASE_HEADERS.copy()
        headers['User-Agent'] = random.choice(self.USER_AGENTS)
        if extra_headers:
            headers.update(extra_headers)
        self.session.headers.update(headers)
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        self.session.headers['User-Agent'] = random.choice(self.USER_AGENTS)
        logger.debug(f"User-Agent已更换: {self.session.headers['User-Agent'][:50]}...")
    
    def set_cookies(self, cookies: Dict):
        """设置Cookie"""
        self._cookies = cookies
        self.session.cookies.update(cookies)
        logger.info("已设置Cookie")
    
    @staticmethod
    def _mask_proxy_url(url: str) -> str:
        """脱敏代理URL中的认证信息（user:pass@host -> ***@host）"""
        if '@' in url:
            parts = url.split('@', 1)
            return f"***@{parts[-1]}"
        return url

    def add_proxy(self, proxy: Dict):
        """添加代理"""
        # proxy格式: {'http': 'http://user:pass@host:port', 'https': 'https://user:pass@host:port'}
        self.proxies.append(proxy)
        masked = self._mask_proxy_url(proxy.get('http', 'unknown'))
        logger.info(f"已添加代理: {masked}")
    
    def clear_proxies(self):
        """清空代理列表"""
        self.proxies = []
        self.current_proxy_index = 0
        logger.info("已清空代理列表")
    
    def _get_proxy(self) -> Optional[Dict]:
        """获取下一个代理"""
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
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
            code = data.get('code')
            # -412 或其他风控相关错误码
            return code in [-412, -509, -10403] or '请求过于频繁' in str(data.get('message', ''))
        return False
    
    def _get_error_info(self, data: Dict) -> Tuple[int, str]:
        """获取错误信息"""
        return data.get('code', -1), data.get('message', '未知错误')
    
    def _request(self, method: str, url: str, max_retries: int = None, 
                 skip_retry: bool = False, **kwargs) -> Optional[Dict]:
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
        
        for attempt in range(max_retries + 1):
            try:
                self._ensure_min_interval()
                
                # 获取代理
                proxy = self._get_proxy() if attempt > 0 else None
                
                # 构建请求参数
                request_kwargs = {
                    'timeout': 15,
                    **kwargs
                }
                if proxy:
                    request_kwargs['proxies'] = proxy
                
                # 发送请求
                response = self.session.request(method, url, **request_kwargs)
                
                # 检查HTTP状态码
                if response.status_code == 412:
                    self._consecutive_412_errors += 1
                    logger.error(f"HTTP 412错误 (第{attempt + 1}次尝试)")
                    if attempt < max_retries and not skip_retry:
                        delay = self._get_retry_delay(attempt)
                        logger.info(f"等待 {delay:.1f} 秒后重试...")
                        time.sleep(delay)
                        self._rotate_user_agent()
                        continue
                    return None
                
                response.raise_for_status()
                data = response.json()
                
                # 检查B站API错误码
                if not isinstance(data, dict):
                    return data
                
                api_code = data.get('code', 0)
                
                if api_code == 0:
                    # 成功
                    self._consecutive_412_errors = 0
                    return data.get('data')
                
                # 处理API错误
                if self._is_412_error(data):
                    self._consecutive_412_errors += 1
                    error_code, error_msg = self._get_error_info(data)
                    logger.error(f"B站API 412错误: {error_msg} (第{attempt + 1}次尝试)")
                    
                    if attempt < max_retries and not skip_retry:
                        delay = self._get_retry_delay(attempt)
                        logger.info(f"等待 {delay:.1f} 秒后重试...")
                        time.sleep(delay)
                        
                        # 尝试绕过措施
                        self._apply_bypass_measures(attempt)
                        continue
                    return None
                
                # 其他API错误，不重试
                if api_code != 0:
                    logger.error(f"API错误 [{api_code}]: {data.get('message', '')}")
                
                return data.get('data') if 'data' in data else None
                
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
                    break  # 非临时错误不重试
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"请求异常: {e}")
                break
            
            # 重试前等待
            if attempt < max_retries and not skip_retry:
                delay = self._get_retry_delay(attempt)
                logger.info(f"等待 {delay:.1f} 秒后重试...")
                time.sleep(delay)
                self._rotate_user_agent()
        
        logger.error(f"请求最终失败: {last_error}")
        return None

    def _request_public(self, method: str, url: str, **kwargs) -> Any:
        """使用无Cookie的独立Session请求公开API（免登录回退）"""
        import requests as _req
        public_session = _req.Session()
        public_session.headers.update({
            "User-Agent": random.choice(self.USER_AGENTS),
            "Referer": "https://www.bilibili.com/",
        })
        try:
            resp = public_session.request(method, url, timeout=15, **kwargs)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data")
        except Exception as e:
            logger.debug(f"公共API请求失败: {e}")
        return None

    def _get_retry_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        # 基础延迟 * 2^attempt + 随机抖动
        base_delay = self.base_retry_delay * (2 ** attempt)
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
        
        # 1. 更换User-Agent
        self._rotate_user_agent()
        measures.append("已更换User-Agent")
        
        # 2. 临时增加最小请求间隔
        if attempt >= 1:
            old_interval = self._min_request_interval
            self._min_request_interval = min(old_interval * 2, 5.0)
            measures.append(f"请求间隔: {old_interval:.1f}s -> {self._min_request_interval:.1f}s")
        
        # 3. 更换代理
        if self.proxies:
            new_proxy = self._get_proxy()
            masked = self._mask_proxy_url(new_proxy.get('http', 'N/A'))
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
        params = {
            'keyword': keyword,
            'search_type': 'video',
            'page': page,
            'pagesize': page_size
        }
        data = self._request('GET', self.SEARCH_URL, params=params)
        if data and 'result' in data:
            return data['result']
        return []
    
    def get_video_info(self, bvid: str) -> Optional[Dict]:
        """获取视频详细信息"""
        params = {'bvid': bvid}
        return self._request('GET', self.VIDEO_URL, params=params)
    
    def get_video_viewers(self, bvid: str, cid: int = None) -> Optional[Dict]:
        """获取视频在线观看人数"""
        try:
            if cid is None:
                video_info = self.get_video_info(bvid)
                if video_info:
                    cid = video_info.get('cid', 0)
                else:
                    return None
            
            params = {'bvid': bvid, 'cid': cid}
            data = self._request('GET', self.VIEWERS_URL, params=params)
            
            if data:
                return {
                    'total': data.get('total', 0),
                    'count': data.get('count', 0),
                    'show_switch': data.get('show_switch', {})
                }
        except Exception as e:
            logger.error(f"获取观看人数失败: {type(e).__name__}")
        return None
    
    def get_video_full_data(self, bvid: str) -> Optional[Dict]:
        """获取视频完整数据"""
        video_info = self.get_video_info(bvid)
        if not video_info:
            return None

        viewers_data = self.get_video_viewers(bvid, video_info.get('cid', 0))

        return {
            'bvid': bvid,
            'title': video_info.get('title', ''),
            'description': video_info.get('desc', ''),
            'pic': video_info.get('pic', ''),
            'owner': video_info.get('owner', {}),
            'stat': video_info.get('stat', {}),
            'viewers_total': viewers_data.get('total', 0) if viewers_data else 0,
            'viewers_web': viewers_data.get('count', 0) if viewers_data else 0,
            'viewers_app': (viewers_data.get('total', 0) - viewers_data.get('count', 0)) if viewers_data else 0,
        }

    # ── UP主相关 ──────────────────────────────────────────
    def search_up_users(self, keyword: str, page: int = 1, order: str = "fans") -> List[Dict]:
        """按用户名搜索UP主

        Args:
            keyword: 用户名关键词
            page: 页码
            order: 排序方式，默认按粉丝数 ("fans"/"level"/"0")

        Returns:
            [{"mid": int, "uname": str, "usign": str, "fans": int, "videos": int,
              "level": int, "upic": str, "is_live": bool, "room_id": int}, ...]
        """
        url = f"{self.BASE_URL}/x/web-interface/wbi/search/type"
        params = {
            "search_type": "bili_user",
            "keyword": keyword,
            "page": page,
            "user_type": 1,  # 1=UP主
        }
        if order:
            params["order"] = order
        params = self._wbi_sign(params)
        data = self._request("GET", url, params=params)
        if data and "result" in data:
            return data["result"]
        return []

    def get_up_info(self, uid: int) -> Optional[Dict]:
        """获取UP主基本信息（先试带Cookie请求，-401时用无Cookie回退）"""
        data = self._request('GET', f"{self.BASE_URL}/x/space/acc/info",
                             params={'mid': uid})
        # -401 非法访问 → Cookie 过期，用免登录方式重试
        if data is None:
            data = self._request_public('GET', f"{self.BASE_URL}/x/space/acc/info",
                                        params={'mid': uid})
        if data:
            return {
                'uid':            data.get('mid', uid),
                'name':           data.get('name', ''),
                'face':           data.get('face', ''),
                'sign':           data.get('sign', ''),
                'level':          data.get('level', 0),
                'follower_count': data.get('fans', 0) or data.get('follower', 0),
                'video_count':    data.get('video_count', data.get('videos', 0)),
                'official_verify': data.get('official_verify', {}),
                'nameplate':      data.get('nameplate', {}),
            }
        return None

    def get_up_videos(self, uid: int, page: int = 1, page_size: int = 30) -> List[Dict]:
        """获取UP主视频列表"""
        url = f"{self.BASE_URL}/x/space/arc/search"
        params = {'mid': uid, 'pn': page, 'ps': page_size}
        data = self._request('GET', url, params=params)
        if data and 'list' in data and 'vlist' in data['list']:
            return data['list']['vlist']
        if data and 'vlist' in data:
            return data['vlist']
        return []

    def get_up_stat(self, uid: int) -> Optional[Dict]:
        """获取UP主统计数据（总播放/总点赞/粉丝趋势）"""
        url = f"{self.BASE_URL}/x/space/upstat"
        data = self._request('GET', url, params={'mid': uid})
        if data:
            return {
                'total_views':  data.get('archive', {}).get('view', 0),
                'total_likes':  data.get('archive', {}).get('like', 0),
                'follower_change': data.get('follower_change', data.get('follower', 0)),
                'follower_count':  data.get('follower', {}).get('follower', 0)
                    if isinstance(data.get('follower'), dict) else data.get('follower', 0),
            }
        return None
    
    # ── WBI签名 ───────────────────────────────────────────
    def _refresh_wbi_key(self):
        """刷新 WBI 密钥（从 nav 接口获取）"""
        try:
            nav_url = f"{self.BASE_URL}/x/web-interface/nav"
            data = self._request('GET', nav_url, skip_retry=True)
            if data and 'wbi_img' in data:
                img_url = data['wbi_img']['img_url']
                sub_url = data['wbi_img']['sub_url']
                import re
                img_key = re.search(r'/([^/]+)\.png', img_url)
                sub_key = re.search(r'/([^/]+)\.png', sub_url)
                if img_key and sub_key:
                    mix = img_key.group(1) + sub_key.group(1)
                    import hashlib
                    self._wbi_key = hashlib.md5(mix.encode()).hexdigest()
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
        query = '&'.join(f'{k}={v}' for k, v in sorted_params)
        query += self._wbi_key
        import hashlib
        wts = int(time.time())
        w_rid = hashlib.md5(query.encode()).hexdigest()
        params['wts'] = wts
        params['w_rid'] = w_rid
        return params

    # ── 弹幕/评论 ─────────────────────────────────────────
    def get_video_danmaku(self, oid: int) -> List[Dict]:
        """获取视频弹幕（XML接口，oid 为 cid）

        Returns:
            [{"text": str, "timestamp": int, "mode": int, "color": int}, ...]
        """
        try:
            resp = self.session.get(
                self.DANMAKU_URL,
                params={'oid': oid},
                headers={'User-Agent': random.choice(self.USER_AGENTS),
                         'Referer': 'https://www.bilibili.com/'},
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            danmaku = []
            for d in root.findall('.//d'):
                p = d.get('p', '')
                parts = p.split(',')
                danmaku.append({
                    'text': d.text or '',
                    'timestamp': float(parts[0]) if len(parts) > 0 else 0,
                    'mode': int(parts[1]) if len(parts) > 1 else 1,
                    'color': int(parts[2]) if len(parts) > 2 else 16777215,
                })
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
            params = {'oid': aid, 'type': 1, 'pn': page, 'ps': 20, 'sort': 2}
            params = self._wbi_sign(params)
            data = self._request('GET', self.COMMENT_URL, params=params)
            if not data or 'replies' not in data or not data['replies']:
                break

            for r in data['replies']:
                all_replies.append({
                    'content': r.get('content', {}).get('message', ''),
                    'like': r.get('like', 0),
                    'ctime': r.get('ctime', 0),
                    'uname': r.get('member', {}).get('uname', ''),
                    'mid': r.get('mid', 0),
                })

            if limit > 0 and len(all_replies) >= limit:
                return all_replies[:limit]

            self._apply_request_interval()

        return all_replies[:limit] if limit > 0 else all_replies

    # ── 热门视频 ─────────────────────────────────────────
    def get_popular_videos(self, pn: int = 1, ps: int = 20) -> List[Dict]:
        """获取热门视频列表"""
        data = self._request('GET', self.POPULAR_URL, params={'pn': pn, 'ps': ps})
        if data and 'list' in data:
            return data['list']
        return []

    def get_weekly_series(self, number: int = None) -> List[Dict]:
        """获取每周必看列表（自动获取最新期数）"""
        # 先获取可用期数列表
        series_list_url = f"{self.BASE_URL}/x/web-interface/popular/series/list"
        list_data = self._request('GET', series_list_url)
        if list_data and 'list' in list_data and list_data['list']:
            if number is None:
                number = list_data['list'][0].get('number', number)
        if number is None:
            return []
        url = f"{self.BASE_URL}/x/web-interface/popular/series/one"
        params = {'number': number}
        data = self._request('GET', url, params=params)
        if data and 'list' in data:
            return data['list']
        return []

    def get_status(self) -> Dict:
        """获取API状态信息"""
        # 验证登录状态
        login_status = False
        login_name = ""
        has_sessdata = bool(self.session.cookies.get("SESSDATA", domain=".bilibili.com")
                          or self._cookies.get("SESSDATA"))
        if has_sessdata:
            try:
                nav = self._request("GET", f"{self.BASE_URL}/x/web-interface/nav",
                                    skip_retry=True)
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
            'consecutive_412_errors': self._consecutive_412_errors,
            'min_request_interval': self._min_request_interval,
            'proxy_count': len(self.proxies),
            'has_cookies': bool(self._cookies),
            'has_sessdata': bool(has_sessdata),
            'is_login': login_status,
            'login_name': login_name,
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
        clean_session.headers.update({"User-Agent": random.choice(self.USER_AGENTS),
                                       "Referer": "https://www.bilibili.com/"})
        try:
            resp = clean_session.get(url, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                return {"url": d.get("url", ""), "qrcode_key": d.get("qrcode_key", "")}
        except Exception as e:
            logger.warning(f"获取二维码失败: {e}")
            return None
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
            resp = self.session.get(
                url,
                params={"qrcode_key": qrcode_key},
                headers={
                    "User-Agent": random.choice(self.USER_AGENTS),
                    "Referer": "https://www.bilibili.com/",
                },
                timeout=15,
            )
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


# 全局API实例
bilibili_api = BilibiliAPI()
