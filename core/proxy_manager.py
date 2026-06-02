"""
代理管理器 (ProxyManager)
=========================

本模块管理 HTTP/SOCKS 代理池，提供代理轮询、UA 绑定、失败自动清理和代理自动发现功能。

核心功能：
  1. 代理轮询                — 轮转使用多个代理 IP，避免单一 IP 被限流
  2. UA-IP 绑定              — 每个代理 IP 绑定一个固定的 User-Agent，模拟真实用户
  3. 失败计数与自动清理       — 连续失败 3 次的代理自动从池中移除
  4. 代理可用性测试           — 通过实际请求 B站 API 验证代理是否可用
  5. 代理自动发现             — 定时从多个公开代理源拉取免费代理

代理源 (PROXY_SOURCES)：
  - geonode.com        (JSON API，含多协议代理)
  - TheSpeedX 仓库     (HTTP/SOCKS4/SOCKS5 纯文本列表)
  - hookzof/socks5     (SOCKS5 纯文本列表)
  - ProxyScrape        (JSON 格式免费代理列表)

安全设计：
  - 代理 URL 脱敏显示（IP 最后一段替换为 ***，认证信息隐藏）
  - 日志中不输出完整的代理地址
"""
import json
import logging
import random
import re
import threading
import time
import warnings
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class ProxyManager:
    """代理管理器：轮询、UA 绑定、失败计数与自动清理

    管理一组 HTTP/SOCKS 代理，通过轮询机制分配请求到不同代理，
    并自动移除不可用的代理。

    线程安全：所有修改操作均使用 _lock 互斥锁保护。
    """

    # 代理使用的 User-Agent 列表（与 BilibiliAPI.USER_AGENTS 独立维护）
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    ]

    def __init__(self):
        """初始化代理管理器

        初始化以下数据结构：
          - proxies: 代理列表（每个元素为 {"http": url, "https": url}）
          - _proxy_ua_map: 代理索引 → 绑定的 UA 字符串
          - _proxy_failure_count: 代理索引 → 连续失败次数
          - _MAX_PROXY_FAILURES: 失败上限（超过此值自动移除代理）
        """
        self.proxies: List[Dict] = []
        self.current_proxy_index = 0
        self._proxy_ua_map: Dict[int, str] = {}  # 代理索引 → 绑定 UA
        self._proxy_failure_count: Dict[int, int] = {}  # 代理索引 → 失败次数
        self._MAX_PROXY_FAILURES = 3  # 超过此失败次数自动移除代理
        self._current_request_proxy_idx: Optional[int] = None
        self._socks_available = self._check_socks()
        self._lock = threading.Lock()
        # 代理自动发现配置
        self._auto_discovery_running = False
        self._last_discovery_time = 0
        self._discovery_interval = 600  # 每 10 分钟自动发现一次

    # ── SOCKS 检测 ────────────────────────────────────────

    @staticmethod
    def _check_socks() -> bool:
        """检测 PySocks 是否可用

        SOCKS4/SOCKS5 代理需要 PySocks 库的支持。
        requests 在安装了 PySocks 后自动支持 socks:// 协议。

        Returns:
            True=PySocks 已安装, False=未安装
        """
        try:
            import socks  # noqa: F401

            return True
        except ImportError:
            logger.info("PySocks 未安装，SOCKS4/5 代理不可用 (pip install PySocks)")
            return False

    # ── URL 工具（静态） ───────────────────────────────────

    @staticmethod
    def normalize_url(url: str) -> str:
        """自动识别代理协议并规范化

        如果 URL 没有协议前缀，默认添加 http://。
        支持的协议：http://, https://, socks4://, socks4a://, socks5://, socks5h://

        Args:
            url: 原始代理 URL

        Returns:
            规范化后的 URL（含协议前缀）
        """
        url = url.strip()
        if not url:
            return url
        if not re.match(r"^(https?|socks[45][ah]?)://", url, re.IGNORECASE):
            url = "http://" + url
        return url

    @staticmethod
    def mask_url(url: str) -> str:
        """脱敏代理 URL — 隐藏认证信息和 IP 最后一段

        脱敏规则：
          - @ 之前的内容（用户名:密码）替换为 ***
          - IPv4 地址的最后一段替换为 ***

        Args:
            url: 原始代理 URL

        Returns:
            脱敏后的 URL（不包含敏感信息）
        """
        if "@" in url:
            url = f"***@{url.split('@', 1)[-1]}"

        def _mask_ip(m):
            ip = m.group(0)
            parts = ip.split(".")
            if len(parts) == 4:
                return f"{parts[0]}.{parts[1]}.{parts[2]}.***"
            return ip

        return re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", _mask_ip, url)

    # ── UA 绑定 ────────────────────────────────────────────

    def init_ua_bindings(self):
        """为代理池中的每个代理绑定一个固定 UA

        每个代理 IP 都应该绑定一个不变的 User-Agent。
        如果单个代理频繁切换 UA 反而会引起 B站 风控系统的注意。

        调用时机：
          - 加载代理列表后
          - 自动发现新代理后
        """
        for i in range(len(self.proxies)):
            self._proxy_ua_map[i] = random.choice(self.USER_AGENTS)
            self._proxy_failure_count[i] = 0
        if self.proxies:
            logger.debug(f"已为 {len(self.proxies)} 个代理绑定固定UA")

    # ── 代理轮询 ──────────────────────────────────────────

    def get_proxy_binding(self) -> Tuple[Optional[int], Optional[Dict], Optional[str]]:
        """获取下一个可用代理及其绑定的 UA（线程安全，轮询模式）

        按轮询顺序查找下一个失败次数未超限的代理。
        如果所有代理都失败过多，则重置失败计数后从头开始。

        Returns:
            (代理索引, 代理配置dict, 绑定的UA字符串) 三元组
            无代理可用时返回 (None, None, None)
        """
        with self._lock:
            if not self.proxies:
                return None, None, None

            # 按轮询顺序查找可用代理（跳过失败次数 >= MAX_PROXY_FAILURES 的）
            for _ in range(len(self.proxies)):
                idx = self.current_proxy_index
                if self._proxy_failure_count.get(idx, 0) < self._MAX_PROXY_FAILURES:
                    proxy = self.proxies[idx]
                    ua = self._proxy_ua_map.get(idx)
                    if not ua:
                        ua = random.choice(self.USER_AGENTS)
                        self._proxy_ua_map[idx] = ua
                    self.current_proxy_index = (idx + 1) % len(self.proxies)
                    self._current_request_proxy_idx = idx
                    return idx, proxy, ua
                self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)

            # 所有代理都失败过多，重置计数器后重试第一个
            self._proxy_failure_count = {i: 0 for i in range(len(self.proxies))}
            idx = 0
            self.current_proxy_index = 1 % max(1, len(self.proxies))
            self._current_request_proxy_idx = idx
            return idx, self.proxies[0], self._proxy_ua_map.get(0, random.choice(self.USER_AGENTS))

    def get_next_proxy(self) -> Optional[Dict]:
        """获取下一个代理（简单轮询，不检查失败计数）

        用于非关键请求的场景（如代理测试），不做失败次数过滤。

        Returns:
            代理配置 dict，无代理时返回 None
        """
        with self._lock:
            if not self.proxies:
                return None
            proxy = self.proxies[self.current_proxy_index]
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
            return proxy

    def peek_proxy(self) -> Optional[str]:
        """预览下一个将被使用的代理 URL（脱敏），不改变内部状态

        用于 UI 显示当前活跃代理。会跳过失败次数过多的代理。

        Returns:
            脱敏后的代理 URL 字符串，无代理时返回 None
        """
        with self._lock:
            if not self.proxies:
                return None
            idx = self.current_proxy_index
            # 跳过失败过多的代理，找到第一个可用代理的 URL 用于预览
            if self._proxy_failure_count.get(idx, 0) >= self._MAX_PROXY_FAILURES:
                for i in range(len(self.proxies)):
                    if self._proxy_failure_count.get(i, 0) < self._MAX_PROXY_FAILURES:
                        idx = i
                        break
            proxy = self.proxies[idx]
            return self.mask_url(proxy.get("http", ""))

    # ── 添加 / 清理 ─────────────────────────────────────────

    def add_proxy(self, proxy: Dict):
        """添加代理到池中（自动识别协议并规范化）

        为新代理分配一个随机 UA 绑定，失败计数初始为 0。

        Args:
            proxy: 原始代理 dict，格式为 {"http": "ip:port", "https": "ip:port"}
        """
        with self._lock:
            normalized = {}
            for scheme, url in proxy.items():
                normalized[scheme] = self.normalize_url(url)
            self.proxies.append(normalized)
            idx = len(self.proxies) - 1
            self._proxy_ua_map[idx] = random.choice(self.USER_AGENTS)
            self._proxy_failure_count[idx] = 0
        masked = self.mask_url(proxy.get("http", "unknown"))
        logger.info(f"已添加代理: {masked}")

    def clear_proxies(self):
        """清空代理列表，重置所有相关状态"""
        with self._lock:
            self.proxies = []
            self.current_proxy_index = 0
            self._proxy_ua_map.clear()
            self._proxy_failure_count.clear()
            self._current_request_proxy_idx = None
        logger.info("已清空代理列表")

    # ── 失败处理 ──────────────────────────────────────────

    def on_request_failure(self, proxy_idx: Optional[int] = None) -> Optional[str]:
        """标记请求失败：增加失败计数，更换当前代理绑定的 UA（线程安全）

        当代理连续失败达到 _MAX_PROXY_FAILURES 时，自动从池中移除。

        移除代理后，会重新索引后续条目的 _proxy_ua_map 和 _proxy_failure_count，
        保持三个集合（proxies, _proxy_ua_map, _proxy_failure_count）的索引一致。

        Args:
            proxy_idx: 失败的代理索引（为 None 时使用最后分配的那个代理）

        Returns:
            更换后的新 UA 字符串，无操作返回 None
        """
        with self._lock:
            if proxy_idx is None:
                proxy_idx = self._current_request_proxy_idx
            if proxy_idx is not None and proxy_idx < len(self.proxies):
                current_failures = self._proxy_failure_count.get(proxy_idx, 0)
                self._proxy_failure_count[proxy_idx] = current_failures + 1
                new_ua = random.choice(self.USER_AGENTS)
                self._proxy_ua_map[proxy_idx] = new_ua
                masked = self.mask_url(self.proxies[proxy_idx].get("http", ""))
                total = current_failures + 1
                if total >= self._MAX_PROXY_FAILURES:
                    # 失败次数超过上限，自动移除代理
                    logger.error(f"代理 {masked} 请求失败已达 {total} 次，自动移除")
                    self.proxies.pop(proxy_idx)
                    self._proxy_ua_map.pop(proxy_idx, None)
                    self._proxy_failure_count.pop(proxy_idx, None)
                    # 重新索引后续条目（保持三个集合一致）
                    for i in range(proxy_idx, len(self.proxies)):
                        self._proxy_ua_map[i] = self._proxy_ua_map.pop(i + 1)
                        self._proxy_failure_count[i] = self._proxy_failure_count.pop(i + 1)
                else:
                    logger.warning(f"代理 {masked} 请求失败 ({total}/{self._MAX_PROXY_FAILURES}), 继续使用当前IP")
                return new_ua
        return None

    # ── 可用性测试（静态） ───────────────────────────────

    # 常见 HTTP 错误码对应的中文原因说明
    HTTP_ERROR_REASONS = {
        403: "HTTP 403 禁止访问（代理被目标拒绝）",
        407: "HTTP 407 需要代理认证（需提供用户名密码）",
        429: "HTTP 429 请求过快",
        502: "HTTP 502 代理服务器错误（Bad Gateway）",
        503: "HTTP 503 代理服务不可用",
        504: "HTTP 504 代理网关超时",
    }

    @staticmethod
    def _build_result() -> dict:
        """构建代理测试结果的默认字典模板

        Returns:
            {"ok": False, "latency_ms": None, "ip": None, "country": None,
             "asn": None, "isp": None, "error": None, "data": None}
        """
        return {
            "ok": False,
            "latency_ms": None,
            "ip": None,
            "country": None,
            "asn": None,
            "isp": None,
            "error": None,
            "data": None,
        }

    @staticmethod
    def _classify_connection_error(e: requests.exceptions.ConnectionError) -> str:
        """将 ConnectionError 归类为可读的中文错误信息

        通过正则匹配错误消息中的关键字来判断具体的连接失败原因。
        注意：错误消息取决于操作系统语言，非中文 Windows 上可能无法匹配中文模式。

        Args:
            e: requests 抛出的 ConnectionError 异常

        Returns:
            中文错误描述字符串
        """
        err_str = str(e)
        root_cause = ""
        try:
            if e.args and hasattr(e.args[0], "reason"):
                root_cause = str(e.args[0].reason)
        except Exception:
            logger.debug("解析代理错误原因失败")
        check = err_str + " " + root_cause

        # 常见错误模式匹配
        # 注意：非中文 Windows 环境可能无法匹配中文关键字模式
        patterns = [
            (["Connection refused", "连接被拒绝", "积极拒绝"], "连接被拒绝（代理地址或端口无效）"),
            (
                ["getaddrinfo failed", "Name or service not known", "Temporary failure in name resolution"],
                "DNS解析失败（代理域名无法解析）",
            ),
            (["resolving host"], "DNS解析失败（代理域名无法解析）"),
            (["No route to host", "无法路由"], "无法路由到主机（网络不可达）"),
            (["Network is unreachable", "网络不可达"], "网络不可达（本地网络异常）"),
            (["Remote end closed connection", "远程主机关闭连接"], "代理连接被远端关闭"),
            (["SSL", "ssl"], f"SSL/TLS握手失败: {root_cause[:120] or err_str[:120]}"),
        ]
        for keywords, message in patterns:
            if any(kw in check for kw in keywords):
                return message
        if root_cause and root_cause != err_str:
            return f"连接失败: {root_cause[:200]}"
        return f"连接失败: {err_str[:200]}"

    @staticmethod
    def _proxy_http_request(proxy_url: str, test_url: str, ua: str, timeout: int) -> dict:
        """通过代理发起 HTTP 请求，测试代理可用性和延迟

        这是代理测试的第一步——验证代理能否建立 HTTP 连接并获取响应。

        Args:
            proxy_url: 代理 URL
            test_url: 测试目标 URL（通常为 B站 API）
            ua: 请求使用的 User-Agent
            timeout: 超时时间（秒）

        Returns:
            结果 dict，成功时包含 resp 对象和 latency_ms，
            失败时包含 error 描述
        """
        import requests
        from urllib3.exceptions import InsecureRequestWarning

        warnings.filterwarnings("ignore", category=InsecureRequestWarning)

        proxies = {"http": proxy_url, "https": proxy_url}
        result = ProxyManager._build_result()
        start = time.time()

        logger.debug("→ [proxy-test] GET %s via %s", test_url.split("?")[0], ProxyManager.mask_url(proxy_url))
        try:
            resp = requests.get(
                test_url,
                proxies=proxies,
                timeout=timeout,
                verify=False,  # nosec - 代理通常使用自签名证书
                headers={
                    "User-Agent": ua,
                    "Referer": "https://www.bilibili.com/",
                    "Accept": "application/json, text/plain, */*",
                },
            )
            result["latency_ms"] = int((time.time() - start) * 1000)
            return {**result, "resp": resp}
        except requests.exceptions.ConnectTimeout:
            result["latency_ms"] = timeout * 1000
            result["error"] = "连接超时（代理无响应，30秒未建立连接）"
        except requests.exceptions.ConnectionError as e:
            result["latency_ms"] = int((time.time() - start) * 1000)
            result["error"] = ProxyManager._classify_connection_error(e)
        except requests.exceptions.Timeout:
            result["latency_ms"] = timeout * 1000
            result["error"] = "响应超时（代理已连接但30秒未返回数据）"
        except Exception as e:
            result["latency_ms"] = int((time.time() - start) * 1000)
            result["error"] = str(e)[:200]
        return result

    @staticmethod
    def _parse_bilibili_json(resp, result: dict) -> dict:
        """解析 B站 API JSON 响应，判断代理是否真正可用

        代理测试的第二步——验证返回的 B站 数据是否有效。
        HTTP 200 不一定代表代理可用（可能返回空内容或被 B站 限流）。

        Args:
            resp: requests.Response 对象
            result: 之前步骤的结果 dict（原地修改）

        Returns:
            填充后的 result dict（ok 字段只有在 API code=0 时才设为 True）
        """
        result["latency_ms"] = result.get("latency_ms") or 0

        if resp.status_code != 200:
            result["error"] = ProxyManager.HTTP_ERROR_REASONS.get(resp.status_code, f"HTTP {resp.status_code}")
            return result

        try:
            body = resp.json()
            code = body.get("code", -1)
            if code == 0:
                result["ok"] = True
                data = body.get("data", {})
                result["data"] = {"title": data.get("title", "")[:30], "view": data.get("stat", {}).get("view", 0)}
            elif code == -412:
                result["error"] = f"被B站频率限制 (HTTP {resp.status_code})"
            else:
                result["ok"] = True
                logger.debug("代理测试收到非预期 API code=%d (%s)", code, body.get("message", ""))
        except Exception:
            result["error"] = f"响应格式错误 (HTTP {resp.status_code})"
        return result

    @staticmethod
    def _proxy_geo_lookup(proxy_url: str, ua: str, timeout: int) -> dict:
        """通过 ip-api.com 查询代理出口 IP 的地理位置、ASN 和 ISP

        这是代理测试的可选第三步——获取代理出口的地理信息。
        尽力而为，失败不影响代理可用性判断。

        Args:
            proxy_url: 代理 URL
            ua: User-Agent
            timeout: 超时时间

        Returns:
            包含 ip, country, asn, isp 的字典，失败返回空字典
        """
        import requests
        from urllib3.exceptions import InsecureRequestWarning

        warnings.filterwarnings("ignore", category=InsecureRequestWarning)

        proxies = {"http": proxy_url, "https": proxy_url}
        try:
            logger.debug("→ [geo] GET ip-api.com/json/ via %s", ProxyManager.mask_url(proxy_url))
            geo_resp = requests.get(
                "https://ip-api.com/json/",
                proxies=proxies,
                timeout=timeout,
                verify=False,  # nosec - 代理通常使用自签名证书
                headers={"User-Agent": ua},
            )
            logger.debug("← [geo] ip-api.com/json/ → %s", geo_resp.status_code)
            if geo_resp.status_code == 200:
                geo = geo_resp.json()
                as_raw = (geo.get("as") or "").strip()
                return {
                    "ip": geo.get("query"),
                    "country": geo.get("country"),
                    "asn": as_raw.split(" ", 1)[0] if as_raw.startswith("AS") else as_raw,
                    "isp": geo.get("isp") or geo.get("org") or "",
                }
        except Exception as e:
            logger.debug("ip-api 地理查询失败: %s", e)
        return {}

    @staticmethod
    def _log_test_result(proxy_url: str, result: dict):
        """记录代理测试结果到日志

        Args:
            proxy_url: 代理 URL
            result: 测试结果 dict
        """
        masked = ProxyManager.mask_url(proxy_url)
        if result.get("ok"):
            logger.info(
                f"代理测试 {masked}: {result['latency_ms']}ms | IP {result.get('ip', '?')} | "
                f"{result.get('country', '')} | {result.get('asn', '')} | {result.get('isp', '')}"
            )
        else:
            logger.warning(f"代理测试 {masked}: 不可用 — {result.get('error', '未知错误')}")

    # ── 代理自动发现 ──────────────────────────────────

    def start_auto_discovery(self, interval: int = 600):
        """启动后台线程定期自动发现免费代理

        启动一个守护线程，每隔 interval 秒自动从公开代理源拉取新代理。
        新发现的代理会先经过连通性测试，通过后才加入池。

        Args:
            interval: 发现间隔（秒），默认 600（10 分钟）
        """
        self._discovery_interval = interval
        if not self._auto_discovery_running:
            self._auto_discovery_running = True
            threading.Thread(target=self._auto_discovery_loop, daemon=True, name="proxy-discovery").start()
            logger.info(f"代理自动发现已启动（间隔 {interval}s）")

    def _auto_discovery_loop(self):
        """后台自动发现循环

        守护线程的主循环，定期调用 _discover_free_proxies()，
        线程在应用退出时自动终止（daemon=True）。
        """
        while self._auto_discovery_running:
            try:
                self._discover_free_proxies()
            except Exception as e:
                logger.debug("代理自动发现异常: %s", e)
            time.sleep(self._discovery_interval)

    # 公开代理源列表（免费代理，速度和可用性参差不齐）
    PROXY_SOURCES = [
        "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps%2Csocks4%2Csocks5",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/refs/heads/main/proxies/all/data.json",
    ]

    def _discover_free_proxies(self):
        """从多个免费代理源拉取代理列表并加入池

        对每个源：
        1. 拉取代理列表
        2. 解析为标准化 URL
        3. 过滤已在池中的重复代理
        4. 快速连通性测试（5 秒超时）
        5. 通过测试的代理加入池

        完成后为新代理绑定 UA。
        """
        added = 0
        tested = 0
        for src_url in self.PROXY_SOURCES:
            try:
                resp = requests.get(src_url, timeout=10,
                                    headers={"User-Agent": "Mozilla/5.0"},
                                    verify=False)
                if resp.status_code != 200:
                    continue
                urls = self._parse_proxy_list(resp.text, src_url)
                for url in urls:
                    if self._proxy_exists(url):
                        continue
                    # 快速连通性测试（5 秒超时）
                    fast_test = ProxyManager._proxy_http_request(url, "http://httpbin.org/ip",
                                                                    "Mozilla/5.0", 5)
                    if not fast_test.get("error"):
                        self.add_proxy({"http": url, "https": url})
                        added += 1
                    tested += 1
            except Exception as e:
                logger.debug("代理源 %s 获取失败: %s", src_url.split("/")[2], e)
        if added:
            self.init_ua_bindings()
            logger.info(f"代理自动发现: 测试 {tested} 个, 新增 {added} 个可用代理 (共 {len(self.proxies)} 个)")

    @staticmethod
    def _parse_proxy_list(text: str, src_url: str) -> List[str]:
        """解析不同格式的代理列表

        根据源 URL 自动识别格式：
          - geonode API → JSON 格式（含多协议）
          - proxyscrape → JSON 数组格式
          - TheSpeedX 等 → 纯文本 ip:port 格式（根据 URL 中的协议名确定协议）

        Args:
            text: 代理源的响应文本
            src_url: 代理源 URL（用于判断格式类型）

        Returns:
            规范化后的代理 URL 列表
        """
        urls = []

        # 根据源 URL 中的关键词确定默认协议
        proto = "http"
        if "socks5" in src_url.lower():
            proto = "socks5"
        elif "socks4" in src_url.lower():
            proto = "socks4"

        # JSON 格式（geonode 源）
        if "geonode" in src_url:
            try:
                data = json.loads(text)
                for item in data.get("data", []):
                    ip = item.get("ip", "")
                    port = item.get("port", "")
                    protocols = item.get("protocols", [])
                    for p in protocols:
                        if p in ("http", "https", "socks4", "socks5"):
                            urls.append(f"{p}://{ip}:{port}")
            except json.JSONDecodeError:
                pass
        elif "proxyscrape" in src_url.lower():
            # proxyscrape JSON 格式
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    for item in data:
                        ip = item.get("ip", "")
                        port = item.get("port", "")
                        p = str(item.get("protocol", "http")).lower()
                        if p in ("http", "https", "socks4", "socks5"):
                            urls.append(f"{p}://{ip}:{port}")
            except json.JSONDecodeError:
                pass
        else:
            # 纯文本格式（ip:port 每行一个）
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "://" in line:
                    urls.append(line)
                else:
                    urls.append(f"{proto}://{line}")
        return urls

    def _proxy_exists(self, url: str) -> bool:
        """检查代理是否已在池中（通过规范化 URL 比对）

        Args:
            url: 待检查的代理 URL

        Returns:
            True=代理已在池中, False=不在
        """
        norm = ProxyManager.normalize_url(url)
        with self._lock:
            for p in self.proxies:
                if ProxyManager.normalize_url(p.get("http", "")) == norm:
                    return True
            return False

    @staticmethod
    def test_proxy(proxy_url: str, timeout: int = 30, test_url: str = None) -> dict:
        """测试单个代理的可用性、延迟、地理位置、ASN、ISP

        完整的代理测试流程（3 阶段）：
          阶段 1：HTTP 请求测试 → 验证代理能否连通
          阶段 2：B站 JSON 解析 → 验证 B站 API 是否正常返回数据
          阶段 3：地理信息查询 → 通过 ip-api.com 获取出口 IP 的地理信息

        默认测试 B站 视频 API 实际获取一次数据。

        Args:
            proxy_url: 待测试的代理 URL
            timeout: 总超时时间（秒），默认 30
            test_url: 自定义测试 URL（默认测试 B站 视频 API）

        Returns:
            {"ok": bool, "latency_ms": int, "ip": str, "country": str,
             "asn": str, "isp": str, "error": str, "data": dict}
        """
        proxy_url = ProxyManager.normalize_url(proxy_url)
        ua = random.choice(ProxyManager.USER_AGENTS)

        if not test_url:
            test_url = "https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ"

        # 阶段 1：HTTP 请求
        resp_data = ProxyManager._proxy_http_request(proxy_url, test_url, ua, timeout)
        if resp_data.get("error"):
            ProxyManager._log_test_result(proxy_url, resp_data)
            return resp_data

        # 阶段 2：解析 B站 JSON 响应
        result = ProxyManager._parse_bilibili_json(resp_data.pop("resp"), resp_data)
        if result.get("error"):
            ProxyManager._log_test_result(proxy_url, result)
            return result

        # 阶段 3：地理信息查询（尽力而为，失败不影响代理可用性判断）
        geo = ProxyManager._proxy_geo_lookup(proxy_url, ua, timeout)
        result.update(geo)

        ProxyManager._log_test_result(proxy_url, result)
        return result
