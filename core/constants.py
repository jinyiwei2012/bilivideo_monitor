"""core 层共享常量 —— 单点维护, 避免跨模块重复定义。

当前托管:
    USER_AGENTS: 请求 UA 池 (bilibili_api / proxy_manager 共用)
    BV_PATTERN: BV 号校验正则 (database.models / cover_manager / ui.helpers 共用)
"""
import re

# ── UA 池 (412 绕过: 模拟真实浏览器指纹, 与 curl_cffi impersonate 对齐) ──
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
]

# ── BV 号校验 (防路径穿越) ────────────────────────────────────
BV_PATTERN = re.compile(r"^BV[A-Za-z0-9]{10,12}$")
