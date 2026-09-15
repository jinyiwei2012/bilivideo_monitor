"""会话隔离回归测试（风控手册 §6）。

覆盖：评论抓取自建独立 API 实例 / 注入的实例不被关闭 / 自建实例由自己关闭 /
风控冷却与限速状态不跨实例传染。
"""

from typing import Any, List, cast
from unittest import mock

import core.bilibili_comment as bilibili_comment
from core.bilibili_api import BilibiliAPI
from core.bilibili_comment import CommentFetcher
from core.bilibili_request import _register_risk_cooldown, risk_state


class _StubDB:
    """替身评论库：只记录 close 次数。"""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _StubAPI:
    """替身 API：只记录 close 次数。"""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_injected_api_is_not_closed_by_fetcher() -> None:
    api = _StubAPI()
    db = _StubDB()
    fetcher = CommentFetcher(api=cast(BilibiliAPI, api), db=cast(Any, db))
    assert fetcher._owns_api is False
    fetcher.close()
    assert api.close_calls == 0, "注入的实例由调用方负责关闭"
    assert db.close_calls == 1


def test_owned_api_is_closed_by_fetcher() -> None:
    created: List[Any] = []

    class _FakeAPI:
        def __init__(self) -> None:
            self.close_calls = 0
            created.append(self)

        def close(self) -> None:
            self.close_calls += 1

    db = _StubDB()
    with mock.patch.object(bilibili_comment, "BilibiliAPI", _FakeAPI):
        fetcher = CommentFetcher(db=cast(Any, db))
        assert fetcher._owns_api is True, "默认必须自建实例（会话隔离）"
        fetcher.close()
    assert len(created) == 1 and created[0].close_calls == 1, "自建实例应随抓取器一起关闭"


def test_comment_fetchers_use_distinct_api_instances() -> None:
    db_a, db_b = _StubDB(), _StubDB()
    a = CommentFetcher(db=cast(Any, db_a))
    b = CommentFetcher(db=cast(Any, db_b))
    try:
        assert a._api is not b._api, "两个抓取器不得共享同一个 API 实例"
        assert a._api.session is not b._api.session
    finally:
        a.close()
        b.close()


def test_risk_state_does_not_leak_between_instances() -> None:
    a, b = BilibiliAPI(), BilibiliAPI()
    try:
        # 防止「风控后刷新 bili_ticket」在单测里发网络请求
        with mock.patch.object(a, "_request", return_value=None):
            _register_risk_cooldown(a, "sign")
        assert risk_state(a)["voucher_streak"] >= 1
        assert risk_state(b)["voucher_streak"] == 0, "冷却状态不得跨实例传染"
        assert risk_state(b)["cooldown_remaining"] == 0.0
        a._min_request_interval = 3.0
        assert b._min_request_interval == 0.5, "限速状态必须各自独立"
    finally:
        a.close()
        b.close()


def test_risk_state_snapshot_shape_after_signal_hit() -> None:
    a = BilibiliAPI()
    try:
        with mock.patch.object(a, "_request", return_value=None):
            _register_risk_cooldown(a, "sign")
        state = risk_state(a)
        assert state["last_kind"] == "sign"
        assert state["cooldown_remaining"] > 0
        assert state["scope"] == "session"
    finally:
        a.close()
