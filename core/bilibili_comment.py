"""B站评论抓取 —— 游标翻页 + 楼中楼 + 全字段留档。

契约见 ``docs/bilibili_api_contract.md`` §8：

- 主列表：``GET /x/v2/reply/wbi/main``（**需 WBI 签名**；``pn`` 被忽略，必须用游标）
  参数 ``type=1, oid=<aid>, mode=0|2|3, pagination_str, plat=1, web_location=1315875``，
  首页额外带 ``seek_rpid=""``；
- 楼中楼：``GET /x/v2/reply/reply``（``pn`` 页码翻页，无需签名）
  参数 ``oid, type=1, root=<rpid>, ps, pn, gaia_source=main_web, web_location=333.788``；
- 分页终止：``data.cursor.is_end``；下一页 ``data.cursor.pagination_reply.next_offset``；
- 风控：``-352`` / 响应体 ``v_voucher`` 表示**签名或 UA 问题**（换 IP 无效），
  ``-412`` 表示 **IP 级风控**（长冷却）；``12002`` 评论区已关闭、``12009`` 类型不合法。

数据落库见 :class:`core.database.comment_db.CommentDatabase`（独立库，保留 ``raw_json`` 原文）。
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.bilibili_api import BilibiliAPI
from core.database.comment_db import CommentDatabase

logger = logging.getLogger(__name__)

COMMENT_URL = "https://api.bilibili.com/x/v2/reply/wbi/main"
REPLY_URL = "https://api.bilibili.com/x/v2/reply/reply"
WEB_LOCATION_MAIN = 1315875
WEB_LOCATION_SUB = "333.788"
PAGE_SIZE = 20

MODE_LATEST = 0  # 按时间（新→旧）
MODE_TIME = 2  # 按时间
MODE_HOT = 3  # 按热度（默认）

# 需要区分处置的错误码（见风控手册 §1）
_CODE_CLOSED = 12002  # 评论区已关闭
_CODE_BAD_TYPE = 12009  # 评论区类型不合法
_IP_PREFIXES = ("IP属地：", "IP属地:")

# 任务状态
STATUS_DONE = "done"
STATUS_STOPPED = "stopped"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"

ProgressFn = Callable[[int, str], None]
StopFn = Callable[[], bool]


def _json_text(value: Any) -> str:
    """序列化为 JSON 文本（失败返回空串，绝不抛错）。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _strip_ip(location: Any) -> str:
    """``"IP属地：上海"`` → ``"上海"``。"""
    text = str(location or "")
    for prefix in _IP_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


@dataclass
class CommentFetchResult:
    """一次抓取的结果摘要。"""

    bvid: str
    aid: int
    task_id: int
    status: str
    pages: int = 0
    top_count: int = 0
    sub_count: int = 0
    total_count: int = 0
    all_count: int = 0
    message: str = ""


class CommentFetcher:
    """评论抓取器（自带独立 :class:`BilibiliAPI` 实例以避免与监控轮询共享会话配额）。"""

    def __init__(
        self,
        api: Optional[BilibiliAPI] = None,
        db: Optional[CommentDatabase] = None,
        *,
        min_interval: float = 1.0,
    ) -> None:
        """初始化。

        Args:
            api: 复用的 API 实例；默认**新建**一个（会话隔离，见风控手册 §6）
            db: 评论独立库；默认 ``data/comments/comments.db``
            min_interval: 页间最小间隔（秒），避免撞风控
        """
        self._api = api if api is not None else BilibiliAPI()
        self._db = db if db is not None else CommentDatabase()
        self._min_interval = max(0.0, float(min_interval))
        self._stop = False

    @property
    def db(self) -> CommentDatabase:
        """评论独立库（供 UI 查询统计）。"""
        return self._db

    def stop(self) -> None:
        """请求停止（线程安全：仅置标志，由抓取循环检查）。"""
        self._stop = True

    def close(self) -> None:
        """关闭数据库连接。"""
        self._db.close()

    # ── 单页请求 ────────────────────────────────────────
    def resolve_aid(self, bvid: str) -> int:
        """把 BV 号解析为 aid（评论接口的 ``oid`` 用 aid）。"""
        info = self._api.get_video_info(bvid)
        if not info:
            return 0
        try:
            return int(info.get("aid", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _fetch_main_page(
        self, aid: int, mode: int, offset: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], int, str]:
        """取一页主评论。

        Returns:
            ``(replies, cursor, all_count, error)``；``error`` 非空表示需要中止
            （``"challenge"`` / ``"blocked"`` / ``"closed"`` / ``"bad_type"``）。
        """
        params: Dict[str, Any] = {
            "oid": aid,
            "type": 1,
            "mode": mode,
            "plat": 1,
            "web_location": WEB_LOCATION_MAIN,
            "pagination_str": json.dumps({"offset": offset}, ensure_ascii=False),
        }
        if not offset:
            params["seek_rpid"] = ""
        data = self._api._request("GET", COMMENT_URL, params=self._api._wbi_sign(params))
        if data is None:
            # 请求层已耗尽重试：区分"IP 被风控"与"其它失败"
            blocked = int(getattr(self._api, "_consecutive_412_errors", 0) or 0) > 0
            return [], {}, 0, "blocked" if blocked else "error"
        if data.get("v_voucher"):
            # 风控挑战票据（可能伴随 code=0）→ 属签名/UA 问题，换 IP 无用
            return [], {}, 0, "challenge"
        replies = data.get("replies") or []
        cursor = data.get("cursor") or {}
        try:
            all_count = int(data.get("all_count", 0) or 0)
        except (TypeError, ValueError):
            all_count = 0
        return list(replies), dict(cursor), all_count, ""

    def _fetch_sub_page(self, aid: int, root: int, page: int) -> List[Dict[str, Any]]:
        """取某条主评论的一页楼中楼（无需 WBI 签名）。"""
        params = {
            "oid": aid,
            "type": 1,
            "root": root,
            "ps": PAGE_SIZE,
            "pn": page,
            "gaia_source": "main_web",
            "web_location": WEB_LOCATION_SUB,
        }
        data = self._api._request("GET", REPLY_URL, params=params)
        if not data or data.get("v_voucher"):
            return []
        return list(data.get("replies") or [])

    # ── 主流程 ──────────────────────────────────────────
    def fetch(
        self,
        bvid: str,
        *,
        mode: int = MODE_HOT,
        max_pages: int = 20,
        max_comments: int = 2000,
        fetch_sub: bool = True,
        sub_pages: int = 2,
        progress: Optional[ProgressFn] = None,
        should_stop: Optional[StopFn] = None,
    ) -> CommentFetchResult:
        """抓取一个视频的评论（主评论 + 可选楼中楼）并落库。

        Args:
            bvid: BV 号
            mode: ``MODE_HOT``(3) / ``MODE_TIME``(2) / ``MODE_LATEST``(0)
            max_pages: 主列表最多取多少页（``0`` 表示不限）
            max_comments: 主评论上限（``0`` 表示不限）
            fetch_sub: 是否抓取楼中楼
            sub_pages: 每条主评论最多取多少页楼中楼
            progress: ``progress(done, message)`` 回调（在**非 GUI 线程**调用）
            should_stop: 返回 True 时尽快停止
        """
        self._stop = False
        aid = self.resolve_aid(bvid)
        if not aid:
            return CommentFetchResult(bvid=bvid, aid=0, task_id=0, status=STATUS_ERROR, message="无法解析视频 aid")
        task_id = self._db.create_task(
            bvid, aid, mode, {"max_pages": max_pages, "max_comments": max_comments, "fetch_sub": fetch_sub}
        )
        state = _FetchState(task_id=task_id, bvid=bvid, aid=aid, mode=mode, fetch_sub=fetch_sub, sub_pages=sub_pages)
        offset = ""
        page_index = 0
        message = ""

        while True:
            if self._should_stop(should_stop):
                state.status = STATUS_STOPPED
                message = "已手动停止"
                break
            if max_pages and page_index >= max_pages:
                message = f"已达页数上限 {max_pages}"
                break

            replies, cursor, all_count, error = self._fetch_main_page(aid, mode, offset)
            if error == "challenge" or error == "blocked":
                state.status = STATUS_BLOCKED
                message = (
                    "风控拦截：数据未取回（签名/UA 问题请先重取 WBI 密钥；IP 级风控请稍后重试）"
                    if error == "challenge"
                    else "IP 级风控（412/509）：请稍后重试或更换代理"
                )
                break
            if error:
                state.status = STATUS_ERROR
                message = f"请求失败：{error}"
                break
            if not replies:
                message = message or "已到末页"
                break

            state.all_count = all_count or state.all_count
            page_index += 1
            self._db.save_page(task_id, page_index, mode, bool(cursor.get("is_end")), state.all_count, cursor)
            self._store_page(state, replies, page_index)
            self._report(progress, state, f"第 {page_index} 页：主评论 {state.top_count} / 楼中楼 {state.sub_count}")

            if max_comments and state.top_count >= max_comments:
                message = f"已达评论上限 {max_comments}"
                break
            if cursor.get("is_end"):
                message = "已到末页（is_end）"
                break

            offset = str((cursor.get("pagination_reply") or {}).get("next_offset", "") or "")
            page_index_offset = offset
            self._sleep(self._min_interval, should_stop)
            if not page_index_offset:
                message = "服务端未返回 next_offset，提前结束"
                break

        if not message:
            message = "抓取完成"
        if state.status == STATUS_DONE and (self._stop or self._should_stop(should_stop)):
            state.status = STATUS_STOPPED
        self._db.finish_task(
            task_id,
            status=state.status,
            pages=state.pages,
            top_count=state.top_count,
            sub_count=state.sub_count,
            total_count=state.total_count,
            error="" if state.status in (STATUS_DONE, STATUS_STOPPED) else message,
        )
        logger.info(
            "评论抓取结束 %s: status=%s pages=%s top=%s sub=%s",
            bvid,
            state.status,
            state.pages,
            state.top_count,
            state.sub_count,
        )
        return CommentFetchResult(
            bvid=bvid,
            aid=aid,
            task_id=task_id,
            status=state.status,
            pages=state.pages,
            top_count=state.top_count,
            sub_count=state.sub_count,
            total_count=state.total_count,
            all_count=state.all_count,
            message=message,
        )

    def _store_page(self, state: "_FetchState", replies: List[Dict[str, Any]], page_index: int) -> None:
        """把一页主评论（含楼中楼）规范化后落库。"""
        now = int(time.time())
        rows = [self._row(r, state, is_sub=False, now=now) for r in replies]
        users = [self._user_row(r.get("member") or {}, now) for r in replies]
        if state.fetch_sub:
            for reply in replies:
                rows.extend(self._fetch_sub_rows(state, reply, now))
        state.pages = page_index
        state.top_count += len(replies)
        self._db.save_comments(rows)
        self._db.save_users([u for u in users if u.get("mid")])

    def _fetch_sub_rows(self, state: "_FetchState", reply: Dict[str, Any], now: int) -> List[Dict[str, Any]]:
        """抓取单条主评论的楼中楼（按 ``root`` 分页）。"""
        root = int(reply.get("rpid") or 0)
        if not root:
            return []
        try:
            expected = int(reply.get("rcount", reply.get("count", 0)) or 0)
        except (TypeError, ValueError):
            expected = 0
        if expected <= 0:
            return []
        rows: List[Dict[str, Any]] = []
        for page in range(1, max(1, state.sub_pages) + 1):
            if self._stop:
                break
            sub_replies = self._fetch_sub_page(state.aid, root, page)
            if not sub_replies:
                break
            rows.extend(self._row(r, state, is_sub=True, now=now) for r in sub_replies)
            self._db.save_users([self._user_row(r.get("member") or {}, now) for r in sub_replies])
            if len(sub_replies) < PAGE_SIZE:
                break
            self._sleep(self._min_interval)
        state.sub_count += len(rows)
        return rows

    # ── 规范化 ──────────────────────────────────────────
    def _row(self, reply: Dict[str, Any], state: "_FetchState", *, is_sub: bool, now: int) -> Dict[str, Any]:
        """把一条评论规范化成评论库行（未知字段全部保留在 ``raw_json``）。"""
        member = reply.get("member") or {}
        content = reply.get("content") or {}
        control = reply.get("reply_control") or {}
        up_action = reply.get("up_action") or {}
        level_info = member.get("level_info") or {}
        return {
            "rpid": self._as_int(reply.get("rpid")),
            "rpid_str": str(reply.get("rpid_str") or ""),
            "bvid": state.bvid,
            "aid": state.aid,
            "oid": state.aid,
            "type": 1,
            "is_sub": 1 if is_sub else 0,
            "root": self._as_int(reply.get("root")),
            "parent": self._as_int(reply.get("parent")),
            "dialog": self._as_int(reply.get("dialog")),
            "up_top": 1 if reply.get("_bili_up_top") else 0,
            "message": str(content.get("message") or ""),
            "emote_json": _json_text(content.get("emote")),
            "jump_url": str(content.get("jump_url") or ""),
            "pictures_json": _json_text(content.get("pictures")),
            "content_json": _json_text(content),
            "like_count": self._as_int(reply.get("like")),
            "rcount": self._as_int(reply.get("rcount", reply.get("count"))),
            "ctime": self._as_int(reply.get("ctime")),
            "mid": self._as_int(reply.get("mid") or member.get("mid")),
            "uname": str(member.get("uname") or ""),
            "sex": str(member.get("sex") or ""),
            "sign": str(member.get("sign") or ""),
            "level": self._as_int(level_info.get("current_level")),
            "vip_json": _json_text(member.get("vip")),
            "avatar": str(member.get("avatar") or ""),
            "medal_json": _json_text(member.get("fans_detail") or member.get("medal")),
            "official_json": _json_text(member.get("official")),
            "member_json": _json_text(member),
            "location": _strip_ip(control.get("location")),
            "time_desc": str(control.get("time_desc") or ""),
            "reply_control_json": _json_text(control),
            "up_liked": 1 if up_action.get("like") else 0,
            "up_replied": 1 if up_action.get("reply") else 0,
            "up_action_json": _json_text(up_action),
            "invisible": 1 if reply.get("invisible") else 0,
            "folded": 1 if (reply.get("folded") or control.get("is_folded")) else 0,
            "sort_mode": state.mode,
            "task_id": state.task_id,
            "first_seen_at": now,
            "last_seen_at": now,
            "raw_json": _json_text(reply),
        }

    @staticmethod
    def _user_row(member: Dict[str, Any], now: int) -> Dict[str, Any]:
        """把 ``member`` 规范化成用户行（去重表）。"""
        level_info = member.get("level_info") or {}
        return {
            "mid": CommentFetcher._as_int(member.get("mid")),
            "uname": str(member.get("uname") or ""),
            "sex": str(member.get("sex") or ""),
            "sign": str(member.get("sign") or ""),
            "level": CommentFetcher._as_int(level_info.get("current_level")),
            "vip_json": _json_text(member.get("vip")),
            "avatar": str(member.get("avatar") or ""),
            "medal_json": _json_text(member.get("fans_detail") or member.get("medal")),
            "official_json": _json_text(member.get("official")),
            "member_json": _json_text(member),
            "first_seen_at": now,
            "last_seen_at": now,
        }

    # ── 工具 ────────────────────────────────────────────
    @staticmethod
    def _as_int(value: Any) -> int:
        """尽力转 int（失败返回 0，绝不抛错）。"""
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _should_stop(self, should_stop: Optional[StopFn]) -> bool:
        """综合自身停止标志与外部回调。"""
        if self._stop:
            return True
        return bool(should_stop()) if should_stop else False

    def _sleep(self, seconds: float, should_stop: Optional[StopFn] = None) -> None:
        """分段睡眠（保证停止请求能被及时响应）。"""
        remaining = float(seconds)
        while remaining > 0:
            if self._should_stop(should_stop):
                return
            step = min(0.2, remaining)
            time.sleep(step)
            remaining -= step

    @staticmethod
    def _report(progress: Optional[ProgressFn], state: "_FetchState", message: str) -> None:
        """上报进度（回调异常不应中断抓取）。"""
        if progress is None:
            return
        try:
            progress(state.top_count + state.sub_count, message)
        except Exception as e:  # 回调由 UI 提供，失败不应影响抓取
            logger.debug("进度回调异常: %s", e)


@dataclass
class _FetchState:
    """抓取过程中的可变状态。"""

    task_id: int
    bvid: str
    aid: int
    mode: int
    fetch_sub: bool
    sub_pages: int
    status: str = STATUS_DONE
    pages: int = 0
    top_count: int = 0
    sub_count: int = 0
    total_count: int = 0
    all_count: int = 0
