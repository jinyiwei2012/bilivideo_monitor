"""gaia-vgate 回归测试（离线：假 API + 假求解器，不发网络请求）。

覆盖：五步流程的请求顺序与字段名 / geetest:null 可解释不可解 / 无 voucher 零请求 /
求解失败与异常 / validate 缺 grisk_id / 会话级 token 与过期 / 未注入时参数零副作用。
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from core.bilibili_api import BilibiliAPI
from core.gaia_vgate import (
    GAIA_VTOKEN_COOKIE,
    GAIA_VTOKEN_PARAM,
    REGISTER_URL,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    VALIDATE_URL,
    clear_vtoken,
    current_vtoken,
    gaia_state,
    register,
    solve_challenge,
    store_vtoken,
    validate,
    with_gaia_vtoken,
)

REGISTER_OK: Dict[str, Any] = {
    "type": "geetest",
    "token": "reg-token",
    "geetest": {"gt": "GT-ID", "challenge": "CH-1"},
}
VALIDATE_OK: Dict[str, Any] = {"grisk_id": "VT-1"}


class _StubAPI:
    """替身 API：按 URL 返回预设的 register / validate 数据。"""

    def __init__(
        self,
        *,
        register_data: Any = None,
        validate_data: Any = None,
        voucher: str = "voucher-1",
        cookies: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.register_data = REGISTER_OK if register_data is None else register_data
        self.validate_data = VALIDATE_OK if validate_data is None else validate_data
        self.calls: List[Dict[str, Any]] = []
        self._cookies: Dict[str, Any] = dict(cookies if cookies is not None else {"bili_jct": "csrf-token"})
        self._risk_last_voucher = voucher

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.register_data if url == REGISTER_URL else self.validate_data

    def set_cookies(self, cookies: Dict[str, Any]) -> None:
        self._cookies = dict(cookies)


class _Solver:
    """假求解器：记录收到的 gt/challenge，返回预设结果。"""

    def __init__(self, pair: Optional[Tuple[str, str]] = ("val-1", "sec-1")) -> None:
        self.pair = pair
        self.seen: Tuple[str, str] = ("", "")

    def __call__(self, gt: str, challenge: str) -> Optional[Tuple[str, str]]:
        self.seen = (gt, challenge)
        return self.pair


def _solver(pair: Optional[Tuple[str, str]] = ("val-1", "sec-1")) -> _Solver:
    return _Solver(pair)


def test_full_flow_order_and_fields() -> None:
    api = _StubAPI()
    solver = _solver()
    result = solve_challenge(api, "voucher-1", solver=solver)

    assert result.status == STATUS_OK and result.ok is True
    assert result.vtoken == "VT-1"
    assert len(api.calls) == 2, "应恰好 register + validate 各一次"
    first, second = api.calls
    assert first["method"] == "POST" and first["url"] == REGISTER_URL
    assert first["kwargs"]["data"] == {"v_voucher": "voucher-1", "csrf": "csrf-token"}
    assert second["method"] == "POST" and second["url"] == VALIDATE_URL
    assert second["kwargs"]["data"] == {
        "challenge": "CH-1",
        "token": "reg-token",
        "validate": "val-1",
        "seccode": "sec-1",
        "csrf": "csrf-token",
    }
    assert solver.seen == ("GT-ID", "CH-1"), "求解器应拿到 register 返回的 gt/challenge"
    assert api._cookies[GAIA_VTOKEN_COOKIE] == "VT-1", "token 应写进会话 Cookie"
    assert current_vtoken(api) == "VT-1"


def test_geetest_null_is_unavailable_and_explainable() -> None:
    api = _StubAPI(register_data={"type": "geetest", "token": "t", "geetest": None})
    result = solve_challenge(api, "voucher-1", solver=_solver())
    assert result.status == STATUS_UNAVAILABLE and result.ok is False
    assert "无法用验证码" in result.message
    assert len(api.calls) == 1, "不可解时不得继续调用 validate"


def test_no_voucher_makes_no_requests() -> None:
    api = _StubAPI(voucher="")
    result = solve_challenge(api)
    assert result.status == STATUS_FAILED
    assert "v_voucher" in result.message
    assert api.calls == []


def test_voucher_falls_back_to_risk_state() -> None:
    api = _StubAPI(voucher="from-risk-state")
    assert solve_challenge(api, solver=_solver()).ok is True
    assert api.calls[0]["kwargs"]["data"]["v_voucher"] == "from-risk-state"


def test_solver_failure_and_exception() -> None:
    api = _StubAPI()
    failed = solve_challenge(api, "voucher-1", solver=_solver(None))
    assert failed.status == STATUS_FAILED and len(api.calls) == 1

    def _boom(gt: str, challenge: str) -> Optional[Tuple[str, str]]:
        raise RuntimeError("solver exploded")

    api2 = _StubAPI()
    crashed = solve_challenge(api2, "voucher-1", solver=_boom)
    assert crashed.status == STATUS_FAILED and "异常" in crashed.message
    assert len(api2.calls) == 1


def test_validate_without_grisk_id() -> None:
    api = _StubAPI(validate_data={"message": "bad"})
    result = solve_challenge(api, "voucher-1", solver=_solver())
    assert result.status == STATUS_FAILED
    assert "grisk_id" in result.message and "bad" in result.message
    assert current_vtoken(api) == "", "失败不得写入 token"


def test_register_validate_handle_bad_responses() -> None:
    api = _StubAPI()
    api.register_data = None  # 直接置空（构造参数里的 None 表示"用默认值"）
    data, error = register(api, "v")
    assert data == {} and "register" in error
    api2 = _StubAPI(validate_data="not-a-dict")
    vtoken, error = validate(api2, "c", "t", "v", "s")
    assert vtoken == "" and "validate" in error


def test_token_is_session_scoped_and_expires() -> None:
    api = _StubAPI()
    store_vtoken(api, "VT-1", ttl=0.0)
    assert current_vtoken(api) == "", "ttl=0 应立刻失效"
    store_vtoken(api, "VT-2")
    assert current_vtoken(api) == "VT-2"
    api._gaia_vtoken_expire = time.time() - 1
    assert current_vtoken(api) == ""
    clear_vtoken(api)
    assert GAIA_VTOKEN_COOKIE not in api._cookies
    assert gaia_state(api)["has_vtoken"] is False


def test_with_gaia_vtoken_is_side_effect_free_without_token() -> None:
    api = _StubAPI()
    params = {"oid": 1, "type": 1}
    assert with_gaia_vtoken(api, params) == params, "没有 token 时不得改动参数"
    assert GAIA_VTOKEN_PARAM not in with_gaia_vtoken(api, params)
    store_vtoken(api, "VT-9")
    merged = with_gaia_vtoken(api, params)
    assert merged[GAIA_VTOKEN_PARAM] == "VT-9"
    assert params == {"oid": 1, "type": 1}, "不得就地修改原字典"


def test_gaia_state_shape() -> None:
    api = _StubAPI(voucher="v1")
    state = gaia_state(api)
    assert state["has_vtoken"] is False and state["remaining"] == 0.0
    assert state["has_voucher"] is True
    store_vtoken(api, "VT-1", ttl=60.0)
    state = gaia_state(api)
    assert state["has_vtoken"] is True and 0 < state["remaining"] <= 60.0


def test_real_api_defaults_to_no_op() -> None:
    api = BilibiliAPI()
    api._persist_cookies = lambda cookies: None
    try:
        assert gaia_state(api)["has_vtoken"] is False
        params = {"oid": 1}
        assert with_gaia_vtoken(api, params) == params
    finally:
        api.close()
