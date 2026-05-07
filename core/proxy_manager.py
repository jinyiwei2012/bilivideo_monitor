"""
代理管理器 - 代理IP轮询、UA绑定、失败自动清理
"""

import json
import logging
import os
import random
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ProxyManager:
    """代理管理器：轮询、UA绑定、失败计数与自动清理"""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    def __init__(self):
        self.proxies: List[Dict] = []
        self.current_proxy_index = 0
        self._proxy_ua_map: Dict[int, str] = {}
        self._proxy_failure_count: Dict[int, int] = {}
        self._MAX_PROXY_FAILURES = 3
        self._current_request_proxy_idx: Optional[int] = None
        self._socks_available = self._check_socks()

    # ── SOCKS 检测 ────────────────────────────────────────

    @staticmethod
    def _check_socks() -> bool:
        """检测 PySocks 是否可用"""
        try:
            import socks  # noqa: F401

            return True
        except ImportError:
            logger.info("PySocks 未安装，SOCKS4/5 代理不可用 (pip install PySocks)")
            return False

    # ── URL 工具（静态） ───────────────────────────────────

    @staticmethod
    def normalize_url(url: str) -> str:
        """自动识别代理协议并规范化"""
        url = url.strip()
        if not url:
            return url
        if not re.match(r"^(https?|socks[45][ah]?)://", url, re.IGNORECASE):
            url = "http://" + url
        return url

    @staticmethod
    def mask_url(url: str) -> str:
        """脱敏代理URL：认证替换为***，IP地址保留前3段"""
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
        """为每个代理绑定一个固定UA"""
        for i in range(len(self.proxies)):
            self._proxy_ua_map[i] = random.choice(self.USER_AGENTS)
            self._proxy_failure_count[i] = 0
        if self.proxies:
            logger.info(f"已为 {len(self.proxies)} 个代理绑定固定UA")

    # ── 代理轮询 ──────────────────────────────────────────

    def get_proxy_binding(self) -> Tuple[Optional[int], Optional[Dict], Optional[str]]:
        """获取下一个代理及其绑定UA，跳过失败过多的代理"""
        if not self.proxies:
            return None, None, None

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

        # 所有代理都失败过多，重置后重试第一个
        self._proxy_failure_count = {i: 0 for i in range(len(self.proxies))}
        idx = 0
        self.current_proxy_index = 1 % max(1, len(self.proxies))
        self._current_request_proxy_idx = idx
        return idx, self.proxies[0], self._proxy_ua_map.get(0, random.choice(self.USER_AGENTS))

    def get_next_proxy(self) -> Optional[Dict]:
        """获取下一个代理（简单轮询，不检查失败计数）"""
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy

    # ── 添加/清理 ─────────────────────────────────────────

    def add_proxy(self, proxy: Dict):
        """添加代理（自动识别协议）"""
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
        """清空代理列表"""
        self.proxies = []
        self.current_proxy_index = 0
        self._proxy_ua_map.clear()
        self._proxy_failure_count.clear()
        self._current_request_proxy_idx = None
        logger.info("已清空代理列表")

    # ── 失败处理 ──────────────────────────────────────────

    def on_request_failure(self, proxy_idx: Optional[int] = None) -> Optional[str]:
        """标记请求失败：增加失败计数，更换当前代理绑定的UA

        Args:
            proxy_idx: 失败代理的索引，None 则使用当前请求索引

        Returns:
            新的 User-Agent（UA 有变更时），None 表示无变更
        """
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
                logger.error(f"代理 {masked} 请求失败已达 {total} 次，自动移除")
                self.proxies.pop(proxy_idx)
                self._proxy_ua_map.pop(proxy_idx, None)
                self._proxy_failure_count.pop(proxy_idx, None)
                for i in range(proxy_idx, len(self.proxies)):
                    self._proxy_ua_map[i] = self._proxy_ua_map.pop(i + 1)
                    self._proxy_failure_count[i] = self._proxy_failure_count.pop(i + 1)
            else:
                logger.warning(f"代理 {masked} 请求失败 ({total}/{self._MAX_PROXY_FAILURES}), 继续使用当前IP")
            return new_ua
        return None

    # ── 可用性测试（静态） ───────────────────────────────

    @staticmethod
    def test_proxy(proxy_url: str, timeout: int = 5, test_url: str = None) -> dict:
        """测试单个代理的可用性、延迟、地区、ASN、ISP

        默认测试 B站视频 API，实际获取一次数据验证代理可用性。
        test_url 可自定义测试地址（含 bvid 参数时自动附加随机 UA）。

        Returns: {ok, latency_ms, country, asn, isp, error, data}
        """
        proxy_url = ProxyManager.normalize_url(proxy_url)
        proxies = {"http": proxy_url, "https": proxy_url}
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        ]
        ua = random.choice(uas)
        import requests

        result = {"ok": False, "latency_ms": None, "country": None, "asn": None, "isp": None, "error": None, "data": None}

        if not test_url:
            test_url = "https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ"

        start = time.time()
        try:
            resp = requests.get(
                test_url, proxies=proxies, timeout=timeout,
                headers={"User-Agent": ua, "Referer": "https://www.bilibili.com/",
                         "Accept": "application/json, text/plain, */*"},
            )
            latency = int((time.time() - start) * 1000)
            result["latency_ms"] = latency

            if resp.status_code != 200:
                result["error"] = f"HTTP {resp.status_code}"
                return result

            # 验证 JSON 响应中有有效数据
            try:
                body = resp.json()
                code = body.get("code", -1)
                if code == 0:
                    result["ok"] = True
                    data = body.get("data", {})
                    result["data"] = {
                        "title": data.get("title", "")[:30],
                        "view": data.get("stat", {}).get("view", 0),
                    }
                elif code == -412:
                    result["error"] = "被B站频率限制"
                    return result
                else:
                    result["ok"] = True
            except Exception:
                result["ok"] = True

            # 通过 ip-api.com 获取地区、ASN、ISP（走同一代理）
            try:
                geo_resp = requests.get(
                    "https://ip-api.com/json/",
                    proxies=proxies, timeout=timeout,
                    headers={"User-Agent": ua},
                )
                if geo_resp.status_code == 200:
                    geo = geo_resp.json()
                    result["country"] = geo.get("country")
                    org = geo.get("org", "")
                    if org and "," in org:
                        asn_part, isp_part = org.split(",", 1)
                        result["asn"] = asn_part.strip()
                        result["isp"] = isp_part.strip()
                    else:
                        result["asn"] = geo.get("as", "")
                        result["isp"] = org or geo.get("isp", "")
            except Exception:
                pass

            # 记录测试结果到日志
            masked = ProxyManager.mask_url(proxy_url)
            if result.get("ok"):
                logger.info(f"代理测试 {masked}: {result['latency_ms']}ms | {result.get('country', '')} | {result.get('asn', '')} | {result.get('isp', '')}")
            else:
                logger.warning(f"代理测试 {masked}: 不可用 — {result.get('error', '未知错误')}")

            return result

        except requests.exceptions.ConnectTimeout:
            result["error"] = "连接超时"
            result["latency_ms"] = timeout * 1000
            return result
        except requests.exceptions.ConnectionError as e:
            result["error"] = "连接失败"
            result["latency_ms"] = int((time.time() - start) * 1000)
            return result
        except requests.exceptions.Timeout:
            result["error"] = "响应超时"
            result["latency_ms"] = timeout * 1000
            return result
        except Exception as e:
            result["error"] = str(e)[:60]
            result["latency_ms"] = int((time.time() - start) * 1000)
            return result
