"""Web 端设备标识：生成 / 持久化 / 注入（规格见 ``docs/risk_control_playbook.md`` §4）。

要点：

- ``buvid3`` / ``buvid4``：**优先用服务端下发值**（``GET /x/frontend/finger/spi``），
  本地伪造（``BilibiliAPI._gen_buvid``）只作最后兜底；
- ``_uuid``（32 位 hex）与 ``b_lsid``（8 位 hex + ``_`` + 毫秒 hex）本地生成，
  与其他标识一起**作为 Cookie 走既有加密出口持久化**；
  **不要每次启动重新生成**——频繁变化的指纹本身就是风险信号；
- ``b_nut``：有服务端下发值时用它，否则记当前秒级时间戳；
- UA 硬约束（文档明令）：UA 不得含 ``curl`` / ``python`` / ``awa``，且同一 UA 不得短时重复，
  由 :func:`sanitize_user_agent` / :func:`pick_user_agent` 保证。

**未实现**（需要可验证的参考实现/测试向量后再做）：``buvid_fp``（murmur3_x64_128）与
``ExClimbWuzhi`` 设备激活；当前请求本来也没发送这两个字段，故不引入无法验证的指纹计算。
"""

import logging
import random
import re
import time
import uuid
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

SPI_URL = "/x/frontend/finger/spi"
BUVID3_COOKIE = "buvid3"
BUVID4_COOKIE = "buvid4"
UUID_COOKIE = "_uuid"
B_LSID_COOKIE = "b_lsid"
B_NUT_COOKIE = "b_nut"

# 文档明令：UA 中出现这些字样即视为伪造客户端，直接触发风控
UA_FORBIDDEN = ("curl", "python", "awa")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_B_LSID_RE = re.compile(r"^[0-9A-F]{8}_[0-9A-F]+$")


def gen_uuid() -> str:
    """生成 32 位 hex 的 ``_uuid``（小写）。"""
    return uuid.uuid4().hex


def gen_b_lsid() -> str:
    """生成 ``b_lsid``：8 位大写 hex + ``_`` + 毫秒时间戳的十六进制（大写）。"""
    return f"{uuid.uuid4().hex[:8].upper()}_{int(time.time() * 1000):X}"


def is_valid_uuid(value: str) -> bool:
    """``_uuid`` 是否合法（32 位 hex）。"""
    return bool(_UUID_RE.fullmatch(str(value or "")))


def is_valid_b_lsid(value: str) -> bool:
    """``b_lsid`` 是否合法（``XXXXXXXX_XXX...`` 大写 hex）。"""
    return bool(_B_LSID_RE.fullmatch(str(value or "")))


def sanitize_user_agent(user_agent: str, fallback: str = "") -> str:
    """过滤不合规 UA：空串或含 ``curl``/``python``/``awa`` 时返回 ``fallback``。"""
    if not str(user_agent or "").strip():
        return fallback
    lowered = str(user_agent).lower()
    if any(bad in lowered for bad in UA_FORBIDDEN):
        logger.debug("UA 命中禁用字样，已替换: %.40s", user_agent)
        return fallback
    return user_agent


def pick_user_agent(agents: Iterable[str], previous: str = "", rng: Optional[random.Random] = None) -> str:
    """从池中挑一个合规且**与上一次不同**的 UA；池内全不合规时返回空串。"""
    candidates = [ua for ua in agents if sanitize_user_agent(ua, "")]
    if not candidates:
        return ""
    pool = [ua for ua in candidates if ua != previous] or candidates
    return (rng or random).choice(pool)


def extract_spi_buvids(data: Any) -> Tuple[str, str]:
    """从 ``/x/frontend/finger/spi`` 响应中取 ``(buvid3, buvid4)``。"""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("buvid3") or ""), str(data.get("buvid4") or "")


def fetch_buvids(api: Any) -> Tuple[str, str]:
    """请求服务端下发的 buvid3/buvid4（失败返回空串，绝不抛错）。"""
    try:
        data = api._request("GET", SPI_URL)
    except Exception as e:
        logger.warning("获取 buvid 失败: %s", e)
        return "", ""
    buvid3, buvid4 = extract_spi_buvids(data)
    if not (buvid3 and buvid4):
        logger.debug("buvid 接口未返回完整数据，继续使用本地值")
    return buvid3, buvid4


def _store(api: Any, values: Dict[str, str]) -> None:
    """把标识并回 Cookie（与账号 Cookie、bili_ticket 同一加密出口）。"""
    cookies = dict(getattr(api, "_cookies", {}) or {})
    cookies.update({k: v for k, v in values.items() if v})
    setter = getattr(api, "set_cookies", None)
    if callable(setter):
        setter(cookies)
    else:
        api._cookies = cookies
    persist = getattr(api, "_persist_cookies", None)
    if callable(persist):
        try:
            persist(cookies)
        except Exception as e:
            logger.debug("持久化设备标识失败: %s", e)


def load_identity(api: Any) -> Dict[str, str]:
    """读取当前标识（**Cookie 优先**，其次实例属性）。

    Cookie 优先是刻意的：标识一经持久化就应跨重启复用，实例属性里的本地兜底值
    （如 ``_gen_buvid()`` 每次启动新生成）不得覆盖已持久化的指纹。
    """
    cookies = getattr(api, "_cookies", {}) or {}

    def _pick(cookie: str, attr: str) -> str:
        return str(cookies.get(cookie, "") or "") or str(getattr(api, attr, "") or "")

    return {
        BUVID3_COOKIE: _pick(BUVID3_COOKIE, "_buvid3"),
        BUVID4_COOKIE: _pick(BUVID4_COOKIE, "_buvid4"),
        UUID_COOKIE: _pick(UUID_COOKIE, "_uuid"),
        B_LSID_COOKIE: _pick(B_LSID_COOKIE, "_b_lsid"),
        B_NUT_COOKIE: _pick(B_NUT_COOKIE, "_b_nut"),
    }


def _buvid_is_persisted(api: Any) -> bool:
    """buvid3/4 是否来自服务端/持久化（而不是每次启动随机伪造的）。"""
    cookies = getattr(api, "_cookies", {}) or {}
    return bool(cookies.get(BUVID3_COOKIE) and cookies.get(BUVID4_COOKIE))


def ensure_identity(api: Any, *, fetch_remote: bool = True) -> Dict[str, str]:
    """补齐设备标识：缺 buvid 时向服务端取，缺 ``_uuid``/``b_lsid``/``b_nut`` 时本地生成并持久化。

    已存在的值一律保留（避免指纹频繁变化），只有缺失/非法时才补。

    Args:
        api: ``BilibiliAPI`` 实例（或等价替身）
        fetch_remote: 是否允许发一次 ``/x/frontend/finger/spi`` 请求补 buvid

    Returns:
        当前标识字典
    """
    current = load_identity(api)
    if fetch_remote and not _buvid_is_persisted(api):
        buvid3, buvid4 = fetch_buvids(api)
        if buvid3 and buvid4:
            current[BUVID3_COOKIE], current[BUVID4_COOKIE] = buvid3, buvid4
    if not current[BUVID3_COOKIE]:
        current[BUVID3_COOKIE] = str(getattr(api, "_buvid3", "") or "")
    if not current[BUVID4_COOKIE]:
        current[BUVID4_COOKIE] = str(getattr(api, "_buvid4", "") or "")
    if not is_valid_uuid(current[UUID_COOKIE]):
        current[UUID_COOKIE] = gen_uuid()
    if not is_valid_b_lsid(current[B_LSID_COOKIE]):
        current[B_LSID_COOKIE] = gen_b_lsid()
    if not current[B_NUT_COOKIE]:
        current[B_NUT_COOKIE] = str(int(time.time()))

    api._buvid3 = current[BUVID3_COOKIE]
    api._buvid4 = current[BUVID4_COOKIE]
    api._uuid = current[UUID_COOKIE]
    api._b_lsid = current[B_LSID_COOKIE]
    api._b_nut = current[B_NUT_COOKIE]

    # 与 Cookie 里的持久化值比对：任何差异都要落盘，否则下次启动会重新生成指纹
    persisted = getattr(api, "_cookies", {}) or {}
    changed = {k: v for k, v in current.items() if v and v != str(persisted.get(k, "") or "")}
    if changed:
        _store(api, changed)
        logger.info("设备标识已更新: %s", ", ".join(sorted(changed)))
    return current
