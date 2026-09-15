"""风控分流回归测试（离线：直接测请求核心的模块级 mixin 函数）。

覆盖：-352 不再被当作空数据 / code:0 夹带 v_voucher / 412 与 352 的处置分流（是否轮换代理）/
冷却升级与封顶 / 掉登录标记的置位与清除 / 凭证提取 / 观测快照只读。
"""

import types
from typing import Any, Dict, List, Optional

from core.bilibili_request import (
    RISK_COOLDOWN_IP,
    RISK_COOLDOWN_MAX,
    _apply_bypass_measures,
    _extract_voucher,
    _handle_successful_response,
    _is_352_error,
    _register_risk_cooldown,
    risk_state,
)


class _StubProxyManager:
    """替身代理管理器：记录是否被要求换绑（352 不应换 IP）。"""

    def __init__(self, proxies: Optional[List[Dict[str, Any]]] = None) -> None:
        self.proxies = proxies or []
        self.binding_calls = 0

    def get_proxy_binding(self) -> tuple[Any, Any, Any]:
        self.binding_calls += 1
        if not self.proxies:
            return None, None, "ua"
        return 0, {"http": "http://127.0.0.1:8080"}, "ua"

    def mask_url(self, url: str) -> str:
        return "http://127.0.0.1:****"


class _Stub:
    """最小请求核心替身：只提供 mixin 函数用到的属性。"""

    USER_AGENTS = ["ua-a", "ua-b"]

    def __init__(self, proxies: Optional[List[Dict[str, Any]]] = None) -> None:
        self._consecutive_412_errors = 0
        self._logged_out = False
        self._voucher_streak = 0
        self._risk_cooldown_until = 0.0
        self._risk_last_kind = ""
        self._risk_scope = ""
        self._risk_last_voucher = ""
        self._min_request_interval = 0.5
        self.base_retry_delay = 0.0
        self.max_retry_delay = 0.0
        self.session = types.SimpleNamespace(headers={})
        self.proxy_manager = _StubProxyManager(proxies)
        self.failure_marks = 0

    def _on_request_failure(self, proxy_idx: Optional[int] = None) -> None:
        self.failure_marks += 1


def _resp(
    stub: _Stub, data: Dict[str, Any], *, attempt: int = 0, max_retries: int = 0, skip_retry: bool = True
) -> tuple[Any, bool]:
    return _handle_successful_response(stub, data, attempt, max_retries, skip_retry, 0)


def test_352_is_not_treated_as_empty_data() -> None:
    """真实缺陷回归：code=-352 且带 data 时，过去会返回 data（看起来像空数据）。"""
    stub = _Stub()
    result, retry = _resp(stub, {"code": -352, "message": "风控校验失败", "data": {"replies": []}})
    assert result is None, "-352 不得再返回 data（调用方会误判为空数据）"
    assert retry is False
    assert stub._risk_last_kind == "sign"
    assert risk_state(stub)["voucher_streak"] == 1
    assert stub._consecutive_412_errors == 1


def test_352_matches_code_or_message() -> None:
    assert _is_352_error(None, {"code": -352}) is True
    assert _is_352_error(None, {"code": -1, "message": "风控校验失败，请稍后再试"}) is True
    assert _is_352_error(None, {"code": -1, "message": "签名校验失败"}) is True
    assert _is_352_error(None, {"code": 0, "message": "0"}) is False
    assert _is_352_error(None, {"code": -412, "message": "请求过于频繁"}) is False
    assert _is_352_error(None, "not-a-dict") is False


def test_412_rotates_proxy_while_352_does_not() -> None:
    proxies = [{"http": "http://127.0.0.1:8080"}]

    ip_stub = _Stub(proxies)
    _, retry = _resp(ip_stub, {"code": -412, "message": "请求过于频繁"}, attempt=0, max_retries=1, skip_retry=False)
    assert retry is True
    assert ip_stub.proxy_manager.binding_calls == 1, "412 应换 IP"
    assert ip_stub._risk_last_kind == "ip"
    assert risk_state(ip_stub)["cooldown_remaining"] > 0

    sign_stub = _Stub(proxies)
    _, retry = _resp(sign_stub, {"code": -352, "message": "风控校验失败"}, attempt=0, max_retries=1, skip_retry=False)
    assert retry is True
    assert sign_stub.proxy_manager.binding_calls == 0, "352 换 IP 无效，不得消耗代理"
    assert sign_stub._risk_last_kind == "sign"
    assert sign_stub.session.headers.get("User-Agent") in _Stub.USER_AGENTS, "352 应更换 UA"


def test_voucher_streak_escalates_to_global_and_caps() -> None:
    stub = _Stub()
    assert _register_risk_cooldown(stub, "sign") == 180.0
    assert risk_state(stub)["scope"] == "session"
    _register_risk_cooldown(stub, "sign")
    assert _register_risk_cooldown(stub, "sign") == 540.0
    assert risk_state(stub)["scope"] == "global", "连续 3 次应升级为全局冷却"
    for _ in range(10):
        _register_risk_cooldown(stub, "sign")
    assert risk_state(stub)["cooldown_remaining"] <= RISK_COOLDOWN_MAX, "冷却必须封顶"
    assert risk_state(stub)["voucher_streak"] == 13


def test_ip_hit_resets_voucher_streak() -> None:
    stub = _Stub()
    _register_risk_cooldown(stub, "sign")
    _register_risk_cooldown(stub, "sign")
    assert _register_risk_cooldown(stub, "ip") == RISK_COOLDOWN_IP
    state = risk_state(stub)
    assert state["voucher_streak"] == 0
    assert state["scope"] == "session"
    assert state["last_kind"] == "ip"


def test_code0_with_voucher_records_challenge() -> None:
    stub = _Stub()
    payload = {"replies": [{"rpid": 1}]}
    result, retry = _resp(stub, {"code": 0, "data": payload, "v_voucher": "v-abc-123"})
    assert result == payload, "code:0 的数据仍应可用"
    assert retry is False
    state = risk_state(stub)
    assert state["last_voucher"] == "v-abc-123"
    assert state["voucher_streak"] == 1, "code:0 夹带凭证也要记冷却"


def test_logged_out_set_and_cleared() -> None:
    stub = _Stub()
    result, retry = _resp(stub, {"code": -101, "message": "账号未登录"})
    assert result is None and retry is False
    assert risk_state(stub)["logged_out"] is True, "掉登录必须可观测"
    _resp(stub, {"code": 0, "data": {"ok": 1}})
    assert risk_state(stub)["logged_out"] is False, "成功请求应清除掉登录标记"


def test_extract_voucher_nested_and_invalid() -> None:
    assert _extract_voucher({"v_voucher": "top"}) == "top"
    assert _extract_voucher({"code": 0, "data": {"gaia_vtoken": "t-1"}}) == "t-1"
    assert _extract_voucher({"code": 0, "data": {"v_voucher": ""}}) == ""
    assert _extract_voucher("nope") == ""


def test_risk_state_is_read_only_snapshot() -> None:
    stub = _Stub()
    state = risk_state(stub)
    assert state["cooldown_remaining"] == 0.0
    assert state["logged_out"] is False
    assert set(state) == {
        "cooldown_remaining",
        "voucher_streak",
        "scope",
        "last_kind",
        "last_voucher",
        "logged_out",
        "consecutive_412_errors",
    }
    state["scope"] = "global"  # 改快照不影响实例状态
    assert risk_state(stub)["scope"] == ""


def test_apply_bypass_measures_sign_keeps_proxy() -> None:
    proxies = [{"http": "http://127.0.0.1:8080"}]

    sign_stub = _Stub(proxies)
    _apply_bypass_measures(sign_stub, attempt=1, proxy_idx=0, kind="sign")
    assert sign_stub.proxy_manager.binding_calls == 0
    assert sign_stub.failure_marks == 0, "352 不应把代理标记为失败"
    assert sign_stub._min_request_interval > 0.5, "352 仍应放慢请求"

    ip_stub = _Stub(proxies)
    _apply_bypass_measures(ip_stub, attempt=1, proxy_idx=0, kind="ip")
    assert ip_stub.failure_marks == 1
    assert ip_stub.proxy_manager.binding_calls == 1
