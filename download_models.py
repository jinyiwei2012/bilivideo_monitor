"""download_models.py — 用 hf-mirror 下载 MOIRAI + Lag-Llama 到 HF 缓存。

绕开两个坑：
1. Windows 系统代理（v2ray/clash 等翻墙工具默认设的）会拦截 hf-mirror.com 的请求
   并 308 重定向到官方 huggingface.co（被墙）。修复：NO_PROXY=hf-mirror.com。
2. huggingface_hub 1.15 跟随相对重定向时丢失 query string，导致 hf-mirror 的
   ETag/签名参数被剥离。修复：monkey-patch _httpx_follow_relative_redirects_with_backoff
   保留 query。
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

# 必须在 import huggingface_hub 之前设
os.environ["NO_PROXY"] = "hf-mirror.com"
os.environ["no_proxy"] = "hf-mirror.com"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub.utils import _http  # noqa: E402
from huggingface_hub.utils._http import hf_raise_for_status, http_backoff  # noqa: E402
from huggingface_hub import file_download  # noqa: E402


def _patched_follow(method, url, *, retry_on_errors=False, **httpx_kwargs):
    no_retry_kwargs = (
        {} if retry_on_errors else {"retry_on_exceptions": (), "retry_on_status_codes": ()}
    )
    while True:
        response = http_backoff(
            method=method, url=url, **httpx_kwargs, follow_redirects=False, **no_retry_kwargs
        )
        hf_raise_for_status(response)
        if 300 <= response.status_code <= 399:
            parsed_target = urlparse(response.headers["Location"])
            if parsed_target.netloc == "":
                # 关键 FIX：保留 query string（hf-mirror 用 ?etag=... 传递元数据）
                url = urlparse(url)._replace(
                    path=parsed_target.path, query=parsed_target.query
                ).geturl()
                continue
        break
    return response


# 同时 patch 工具模块和已 import 的 file_download 模块
_http._httpx_follow_relative_redirects_with_backoff = _patched_follow
file_download._httpx_follow_relative_redirects_with_backoff = _patched_follow

from huggingface_hub import snapshot_download, hf_hub_download  # noqa: E402


def download_moirai() -> str:
    print("\n[download_models] === MOIRAI (Salesforce/moirai-1.1-R-small) ===")
    return snapshot_download(
        repo_id="Salesforce/moirai-1.1-R-small",
        endpoint="https://hf-mirror.com",
        max_workers=2,
    )


def download_lag_llama() -> str:
    print("\n[download_models] === Lag-Llama (time-series-foundation-models/Lag-Llama) ===")
    # lag-llama 只用 .ckpt 文件即可，整仓拉太大
    return hf_hub_download(
        repo_id="time-series-foundation-models/Lag-Llama",
        filename="lag-llama.ckpt",
        endpoint="https://hf-mirror.com",
    )


def main() -> int:
    try:
        p1 = download_moirai()
        print(f"[download_models] MOIRAI -> {p1}")
    except Exception as e:
        print(f"[download_models] MOIRAI 失败: {e}")
        return 1
    try:
        p2 = download_lag_llama()
        print(f"[download_models] Lag-Llama -> {p2}")
    except Exception as e:
        print(f"[download_models] Lag-Llama 失败: {e}")
        return 2
    print("\n[download_models] 全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
