"""``get_video_comments`` 迁移回归测试（完全离线：假 API 替身，无网络）。

背景（契约 §8）：``core/bilibili_video.py::get_video_comments`` 从已废弃的
``/x/v2/reply/main``（``pn`` 翻页）迁移为委托 ``core/bilibili_comment.py``
（``/x/v2/reply/wbi/main`` + WBI 签名 + ``pagination_str`` 游标翻页）。

覆盖：新端点与签名参数、游标回传、输出形状与 ``limit`` 语义（``0`` = 全部）、
无评论/风控 → 返回已取部分（可能为空）、``_VideoMixin`` 接线保持。
"""

import json
from typing import Any, Dict, List, Optional

from core.bilibili_comment import COMMENT_URL, MODE_HOT
from core.bilibili_video import get_video_comments

AID = 12345
LEGACY_URL = "https://api.bilibili.com/x/v2/reply/main"


def _reply(
    rpid: int, message: str = "hello", *, like: int = 1, mid: int = 100, uname: str = "tester"
) -> Dict[str, Any]:
    """构造一条顶层评论（仅含旧输出形状所依赖的字段）。"""
    return {
        "rpid": rpid,
        "like": like,
        "ctime": 1700000000 + rpid,
        "mid": mid,
        "content": {"message": message},
        "member": {"mid": mid, "uname": uname},
    }


def _page(replies: List[Dict[str, Any]], *, next_offset: str = "", is_end: bool = True) -> Dict[str, Any]:
    """构造一页主评论响应（data 层）。"""
    return {
        "replies": replies,
        "cursor": {
            "is_end": is_end,
            "pagination_reply": {"next_offset": next_offset},
        },
    }


class _FakeAPI:
    """替身 API：按 ``pagination_str.offset`` 返回预设页，并记录请求。"""

    def __init__(self, by_offset: Dict[str, Dict[str, Any]]) -> None:
        self._by_offset = by_offset
        self.calls: List[Dict[str, Any]] = []
        self._consecutive_412_errors = 0

    def _wbi_sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return dict(params, wts="1702204169", w_rid="deadbeef")

    def _request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        params = dict(params or {})
        self.calls.append({"url": url, "params": params})
        offset = json.loads(str(params.get("pagination_str", "{}"))).get("offset", "")
        return self._by_offset.get(offset, _page([]))


def test_targets_wbi_main_with_wbi_signature() -> None:
    api = _FakeAPI({"": _page([_reply(1)], is_end=True)})
    comments = get_video_comments(api, AID)
    assert len(comments) == 1
    assert api.calls, "必须至少发出一次请求"
    assert all(c["url"] == COMMENT_URL for c in api.calls), "必须打 /x/v2/reply/wbi/main"
    assert LEGACY_URL not in [c["url"] for c in api.calls], "不得再打已废弃的 /x/v2/reply/main"
    first = api.calls[0]["params"]
    assert first["w_rid"] == "deadbeef" and first["wts"] == "1702204169", "主接口必须带 WBI 签名"
    assert first["seek_rpid"] == "", "首页必须带空 seek_rpid"
    assert first["oid"] == AID and first["mode"] == MODE_HOT


def test_cursor_pagination_and_output_shape() -> None:
    api = _FakeAPI(
        {
            "": _page([_reply(1, "a", like=7, mid=11, uname="u1")], next_offset="abc", is_end=False),
            "abc": _page([_reply(2, "b", like=9, mid=22, uname="u2")], is_end=True),
        }
    )
    comments = get_video_comments(api, AID, limit=0)
    assert len(comments) == 2
    # 游标：第二页必须回传上一页的 next_offset
    assert len(api.calls) == 2
    assert json.loads(api.calls[1]["params"]["pagination_str"])["offset"] == "abc"
    # 输出形状与旧 get_video_comments 完全一致
    for item in comments:
        assert set(item.keys()) == {"content", "like", "ctime", "uname", "mid"}
    assert comments[0] == {"content": "a", "like": 7, "ctime": 1700000001, "uname": "u1", "mid": 11}
    assert comments[1] == {"content": "b", "like": 9, "ctime": 1700000002, "uname": "u2", "mid": 22}


def test_limit_truncates_and_stops_early() -> None:
    api = _FakeAPI({"": _page([_reply(i) for i in range(1, 6)], next_offset="n", is_end=False)})
    comments = get_video_comments(api, AID, limit=3)
    assert len(comments) == 3
    assert len(api.calls) == 1, "达到 limit 后不得继续翻页"


def test_limit_zero_fetches_all_pages_until_is_end() -> None:
    api = _FakeAPI(
        {
            "": _page([_reply(1), _reply(2)], next_offset="x", is_end=False),
            "x": _page([_reply(3)], is_end=True),
        }
    )
    comments = get_video_comments(api, AID, limit=0)
    assert len(comments) == 3
    assert len(api.calls) == 2


def test_no_comments_returns_empty_list() -> None:
    api = _FakeAPI({"": _page([])})
    assert get_video_comments(api, AID) == []


def test_v_voucher_returns_collected_so_far() -> None:
    api = _FakeAPI(
        {
            "": _page([_reply(1)], next_offset="x", is_end=False),
            "x": {"v_voucher": "voucher_84a8c3ce"},
        }
    )
    comments = get_video_comments(api, AID, limit=0)
    assert len(comments) == 1, "风控页之前已取到的评论必须保留（与旧实现同语义）"


def test_mixin_wiring_kept() -> None:
    """``_VideoMixin`` 的接线保持不变：``BilibiliAPI.get_video_comments`` 可用。"""
    from core.bilibili_api import BilibiliAPI

    assert callable(getattr(BilibiliAPI, "get_video_comments", None))
