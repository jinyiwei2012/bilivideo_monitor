"""WBI 签名回归测试（离线，不依赖网络）。

验证向量取自原文档 `misc/sign/wbi.md`（离线留档：docs/bilibili-api/frozen-fork/wbi.md）
与契约 docs/bilibili_api_contract.md §1。
"""

import hashlib
import time
from typing import Any, Dict

from core.bilibili_api import (
    MIXIN_KEY_ENC_TAB,
    BilibiliAPI,
    wbi_key_from_url,
    wbi_mixin_key,
    wbi_query,
)

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
MIXIN_KEY = "ea1db124af3c7062474693fa704f4ff8"
# 文档给定示例的 w_rid（bar=514&foo=114&wts=1702204169&zab=1919810 + mixin_key）
DOC_W_RID = "8f6f2b5b3d485fe1886cec6a0be8c5d4"


def _bare_api() -> BilibiliAPI:
    """绕过 __init__ 构造实例（不建 session、不读配置/代理），用于纯签名测试。"""
    return BilibiliAPI.__new__(BilibiliAPI)


def test_mixin_key_matches_doc_vector() -> None:
    assert wbi_mixin_key(IMG_KEY, SUB_KEY) == MIXIN_KEY


def test_mixin_table_is_a_permutation_of_0_63() -> None:
    assert len(MIXIN_KEY_ENC_TAB) == 64
    assert sorted(MIXIN_KEY_ENC_TAB) == list(range(64))


def test_key_extraction_handles_any_extension() -> None:
    assert wbi_key_from_url(f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png") == IMG_KEY
    # 旧实现硬编码 ".png"，后缀变化即失效
    assert wbi_key_from_url(f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.webp") == SUB_KEY
    assert wbi_key_from_url("") == ""


def test_query_encoding_matches_doc_example() -> None:
    """文档示例：空格必须编码为 %20（不是 +），中文大写百分号编码。"""
    params = {"foo": "one one four", "bar": "五一四", "baz": 1919810}
    assert wbi_query(params) == "bar=%E4%BA%94%E4%B8%80%E5%9B%9B&baz=1919810&foo=one%20one%20four"


def test_query_filters_illegal_chars_and_sorts_keys() -> None:
    assert wbi_query({"b": "x!y'z(p)q*r", "a": 2}) == "a=2&b=xyzpqr"


def test_w_rid_matches_doc_vector() -> None:
    params = {"foo": "114", "bar": "514", "zab": 1919810, "wts": 1702204169}
    query = wbi_query(params)
    assert query == "bar=514&foo=114&wts=1702204169&zab=1919810"
    assert hashlib.md5((query + MIXIN_KEY).encode()).hexdigest() == DOC_W_RID


def test_sign_adds_wts_and_w_rid_including_wts_in_hash() -> None:
    api = _bare_api()
    api._wbi_key = MIXIN_KEY
    api._wbi_key_expire = time.time() + 600.0
    signed = api._wbi_sign({"oid": 123, "type": 1})
    assert isinstance(signed["wts"], str) and signed["wts"].isdigit()
    expected = hashlib.md5((wbi_query({"oid": 123, "type": 1, "wts": signed["wts"]}) + MIXIN_KEY).encode()).hexdigest()
    assert signed["w_rid"] == expected
    assert "w_rid" not in {"oid": 123, "type": 1}  # 原参数未被就地修改


def test_sign_without_key_returns_params_unchanged(monkeypatch: Any) -> None:
    api = _bare_api()
    api._wbi_key = None
    api._wbi_key_expire = 0.0
    monkeypatch.setattr(api, "_refresh_wbi_key", lambda: None)
    original = {"pn": 1}
    assert api._wbi_sign(original) == original


def test_key_refresh_is_cached_for_ttl(monkeypatch: Any) -> None:
    api = _bare_api()
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        calls.append(url)
        return {
            "wbi_img": {
                "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
            }
        }

    monkeypatch.setattr(api, "_request", fake_request)
    api._wbi_sign({"pn": 1})
    api._wbi_sign({"pn": 2})
    assert len(calls) == 1, "TTL 内不应重复刷新密钥"
    assert api._wbi_key == MIXIN_KEY

    api._wbi_key_expire = 0.0  # 模拟过期
    api._wbi_sign({"pn": 3})
    assert len(calls) == 2, "过期后应重新取密钥"
