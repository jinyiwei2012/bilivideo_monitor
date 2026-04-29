"""
B站API模块 - 封装B站相关接口
增强版：支持获取观看人数、412错误重试与绕过机制
"""
import requests
import re
import time
import random
import logging
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
                    logger.warning(f"HTTP 412错误 (第{attempt + 1}次尝试)")
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
                    logger.warning(f"B站API 412错误: {error_msg} (第{attempt + 1}次尝试)")
                    
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
                    logger.warning(f"API错误 [{api_code}]: {data.get('message', '')}")
                
                return data.get('data') if 'data' in data else None
                
            except requests.exceptions.Timeout:
                last_error = "请求超时"
                logger.warning(f"请求超时 (第{attempt + 1}次尝试)")
                
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接错误: {e}"
                logger.warning(f"连接错误 (第{attempt + 1}次尝试): {e}")
                
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP错误: {e}"
                if response.status_code in [502, 503, 504]:
                    logger.warning(f"服务器错误 {response.status_code} (第{attempt + 1}次尝试)")
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
    
    def get_status(self) -> Dict:
        """获取API状态信息"""
        return {
            'consecutive_412_errors': self._consecutive_412_errors,
            'min_request_interval': self._min_request_interval,
            'proxy_count': len(self.proxies),
            'has_cookies': bool(self._cookies),
        }
    
    def reset_status(self):
        """重置状态（用于连续失败后的恢复）"""
        self._consecutive_412_errors = 0
        self._min_request_interval = 0.5
        logger.info("API状态已重置")


# 全局API实例
bilibili_api = BilibiliAPI()
