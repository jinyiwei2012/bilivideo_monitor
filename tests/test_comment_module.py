"""评论抓取模块回归测试（完全离线：假 API + 临时独立库）。

覆盖：游标翻页 / WBI 签名调用 / 去重计数 / 楼中楼参数 / 风控识别 / 手动停止 / raw_json 原文保留 /
用户去重 / 任务与统计查询。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.bilibili_comment import (
    MODE_HOT,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_STOPPED,
    CommentFetcher,
)
from core.database.comment_db import CommentDatabase

AID = 12345


def _reply(
    rpid: int,
    message: str = "hello",
    *,
    like: int = 1,
    rcount: int = 0,
    mid: int = 100,
    uname: str = "tester",
    location: str = "IP属地：上海",
) -> Dict[str, Any]:
    """构造一条评论（含一个未知字段用于验证 raw_json 保真）。"""
    return {
        "rpid": rpid,
        "rpid_str": str(rpid),
        "root": 0,
        "parent": 0,
        "like": like,
        "rcount": rcount,
        "ctime": 1700000000 + rpid,
        "mid": mid,
        "content": {"message": message, "jump_url": ""},
        "member": {
            "mid": mid,
            "uname": uname,
            "sex": "保密",
            "sign": "",
            "avatar": "https://example.invalid/a.jpg",
            "level_info": {"current_level": 5},
            "vip": {"vipStatus": 0},
        },
        "reply_control": {"location": location, "time_desc": "3小时前"},
        "up_action": {"like": True, "reply": False},
        "brand_new_field_from_api": "keep-me",  # 未知字段 → 必须进 raw_json
    }


def _page(replies: List[Dict[str, Any]], *, next_offset: str = "", is_end: bool = True) -> Dict[str, Any]:
    """构造一页主评论响应（data 层）。"""
    return {
        "replies": replies,
        "cursor": {
            "is_end": is_end,
            "all_count": 99,
            "pagination_reply": {"next_offset": next_offset},
        },
        "all_count": 99,
    }


class _FakeAPI:
    """替身 API：按 ``pagination_str.offset`` 返回预设页，并记录调用参数。"""

    def __init__(self, by_offset: Dict[str, Dict[str, Any]], subs: Optional[List[Dict[str, Any]]] = None) -> None:
        self._by_offset = by_offset
        self._subs = subs or []
        self.calls: List[Dict[str, Any]] = []
        self._consecutive_412_errors = 0

    def get_video_info(self, bvid: str) -> Dict[str, Any]:
        return {"aid": AID, "bvid": bvid}

    def _wbi_sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return dict(params, wts="1702204169", w_rid="deadbeef")

    def _request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        params = dict(params or {})
        self.calls.append({"url": url, "params": params})
        if url.endswith("/reply/reply"):
            return {"replies": self._subs}
        offset = json.loads(str(params.get("pagination_str", "{}"))).get("offset", "")
        return self._by_offset.get(offset, _page([]))


def _fetcher(tmp_path: Path, api: _FakeAPI, **kwargs: Any) -> CommentFetcher:
    """构造使用临时独立库的抓取器（不碰真实 data/ 目录）。"""
    db = CommentDatabase(base_dir=str(tmp_path))
    return CommentFetcher(api=api, db=db, min_interval=0.0, **kwargs)


def test_paginates_with_cursor_and_signs_wbi(tmp_path: Path) -> None:
    api = _FakeAPI(
        {
            "": _page([_reply(1), _reply(2)], next_offset="abc", is_end=False),
            "abc": _page([_reply(3)], is_end=True),
        }
    )
    fetcher = _fetcher(tmp_path, api)
    result = fetcher.fetch("BV1xx411c7mu", mode=MODE_HOT, max_pages=5)

    assert result.status == STATUS_DONE
    assert result.top_count == 3
    assert result.pages == 2
    main_calls = [c for c in api.calls if c["url"].endswith("/reply/wbi/main")]
    assert len(main_calls) == 2
    # WBI 签名必须带上（契约 §8：主接口需签名）
    assert main_calls[0]["params"]["w_rid"] == "deadbeef"
    assert main_calls[0]["params"]["wts"] == "1702204169"
    # 首页带 seek_rpid，第二页改为回传游标
    assert main_calls[0]["params"]["seek_rpid"] == ""
    assert json.loads(main_calls[1]["params"]["pagination_str"])["offset"] == "abc"
    fetcher.close()


def test_dedup_increments_seen_count(tmp_path: Path) -> None:
    api = _FakeAPI(
        {
            "": _page([_reply(7)], next_offset="n", is_end=False),
            "n": _page([_reply(7)], is_end=True),
        }
    )
    fetcher = _fetcher(tmp_path, api)
    fetcher.fetch("BV1xx411c7mu", max_pages=5)
    rows = fetcher.db.get_comments(bvid="BV1xx411c7mu", limit=10)
    assert len(rows) == 1, "同 rpid 必须去重"
    assert int(rows[0]["seen_count"]) == 2, "重复抓取应累加 seen_count"
    fetcher.close()


def test_sub_comments_use_expected_params(tmp_path: Path) -> None:
    api = _FakeAPI(
        {"": _page([_reply(9, rcount=2)], is_end=True)},
        subs=[_reply(11, message="reply", mid=200)],
    )
    fetcher = _fetcher(tmp_path, api)
    result = fetcher.fetch("BV1xx411c7mu", fetch_sub=True, sub_pages=1)

    sub_calls = [c for c in api.calls if c["url"].endswith("/reply/reply")]
    assert sub_calls, "有 rcount>0 的评论时必须抓楼中楼"
    params = sub_calls[0]["params"]
    assert params["root"] == 9
    assert params["gaia_source"] == "main_web"
    assert params["web_location"] == "333.788"
    assert "w_rid" not in params, "楼中楼接口无需 WBI 签名"
    assert result.sub_count == 1
    subs = fetcher.db.get_comments(bvid="BV1xx411c7mu", only_sub=True, limit=10)
    assert len(subs) == 1 and int(subs[0]["is_sub"]) == 1
    fetcher.close()


def test_v_voucher_marks_blocked(tmp_path: Path) -> None:
    api = _FakeAPI({"": {"v_voucher": "voucher_84a8c3ce-33f5-4551-9552-9c6b13aa7938"}})
    fetcher = _fetcher(tmp_path, api)
    result = fetcher.fetch("BV1xx411c7mu")
    assert result.status == STATUS_BLOCKED
    assert "风控" in result.message
    assert fetcher.db.count_comments(bvid="BV1xx411c7mu") == 0
    fetcher.close()


def test_should_stop_marks_stopped(tmp_path: Path) -> None:
    api = _FakeAPI({"": _page([_reply(1)], next_offset="x", is_end=False)})
    fetcher = _fetcher(tmp_path, api)
    result = fetcher.fetch("BV1xx411c7mu", should_stop=lambda: True)
    assert result.status == STATUS_STOPPED
    assert fetcher.db.count_comments(bvid="BV1xx411c7mu") == 0
    fetcher.close()


def test_raw_json_keeps_unknown_fields(tmp_path: Path) -> None:
    api = _FakeAPI({"": _page([_reply(5)], is_end=True)})
    fetcher = _fetcher(tmp_path, api)
    fetcher.fetch("BV1xx411c7mu")
    row = fetcher.db.get_comments(bvid="BV1xx411c7mu", limit=1)[0]
    assert "brand_new_field_from_api" in str(row["raw_json"]), "未知字段必须保留在 raw_json"
    assert row["location"] == "上海", "IP 属地应去掉前缀"
    assert int(row["level"]) == 5
    assert int(row["up_liked"]) == 1
    fetcher.close()


def test_users_dedup_and_count(tmp_path: Path) -> None:
    api = _FakeAPI({"": _page([_reply(1, mid=300), _reply(2, mid=300)], is_end=True)})
    fetcher = _fetcher(tmp_path, api)
    fetcher.fetch("BV1xx411c7mu")
    users = fetcher.db.get_user_stats(bvid="BV1xx411c7mu", limit=5)
    assert len(users) == 1, "同 mid 只应有一行用户"
    assert int(users[0]["comment_count_in_video"]) == 2
    fetcher.close()


def test_task_lifecycle_and_summary(tmp_path: Path) -> None:
    api = _FakeAPI({"": _page([_reply(1, rcount=1), _reply(2)], is_end=True)}, subs=[_reply(3, mid=400)])
    fetcher = _fetcher(tmp_path, api)
    result = fetcher.fetch("BV1xx411c7mu")
    db = fetcher.db

    tasks = db.list_tasks(limit=5)
    assert tasks and int(tasks[0]["id"]) == result.task_id
    assert tasks[0]["status"] == STATUS_DONE
    stats = db.task_stats(result.task_id)
    assert int(stats["top_count"]) == 2
    assert int(stats["sub_count"]) == 1
    summary = db.summary("BV1xx411c7mu")
    assert int(summary["total"]) == 3
    assert int(summary["sub_count"]) == 1
    assert any(item["location"] == "上海" for item in summary["locations"])
    fetcher.close()


def test_request_carries_gaia_vtoken_when_present(tmp_path: Path) -> None:
    """命中风控并解除后，重试请求必须在原请求上带 gaia_vtoken（风控手册 §7 第 5 步）。"""
    from core.gaia_vgate import GAIA_VTOKEN_PARAM, store_vtoken

    api = _FakeAPI({"": _page([_reply(1)], is_end=True)})
    store_vtoken(api, "VT-retry")
    fetcher = _fetcher(tmp_path, api)
    fetcher.fetch("BV1xx411c7mu", max_pages=1)
    main_calls = [c for c in api.calls if c["url"].endswith("/reply/wbi/main")]
    assert main_calls and main_calls[-1]["params"][GAIA_VTOKEN_PARAM] == "VT-retry"
    assert "w_rid" in main_calls[-1]["params"], "gaia_vtoken 不应影响 WBI 签名本身"
    fetcher.close()


def test_database_roundtrip(tmp_path: Path) -> None:
    db = CommentDatabase(base_dir=str(tmp_path))
    task_id = db.create_task("BV1xx411c7mu", AID, MODE_HOT, {"x": 1})
    assert task_id > 0
    written = db.save_comments(
        [
            {
                "rpid": 1,
                "bvid": "BV1xx411c7mu",
                "aid": AID,
                "oid": AID,
                "message": "m",
                "mid": 9,
                "uname": "u",
                "like_count": 3,
                "ctime": 1700000000,
                "location": "北京",
                "task_id": task_id,
                "first_seen_at": 1,
                "last_seen_at": 1,
            }
        ]
    )
    assert written == 1
    db.save_page(task_id, 1, MODE_HOT, True, 10, {"pagination_reply": {"next_offset": "zz"}})
    db.finish_task(task_id, status=STATUS_DONE, pages=1, top_count=1)
    assert db.count_comments(bvid="BV1xx411c7mu") == 1
    row = db.get_comments(bvid="BV1xx411c7mu", limit=1)[0]
    assert row["message"] == "m" and int(row["like_count"]) == 3
    tasks = db.list_tasks(limit=1)
    assert tasks[0]["status"] == STATUS_DONE and int(tasks[0]["pages"]) == 1
    db.close()
