"""gaia-vgate 兜底链（v_voucher → geetest → gaia_vtoken）。

规格见 ``docs/risk_control_playbook.md`` §7（来源：留档 original-backup/misc/sign/v_voucher.md，
参考实现 Oecxuan/2233TicketBuy::src/gaia.py，MIT）：

1. 命中 ``v_voucher``（``code=-352`` 或 ``data.v_voucher`` / 响应头 ``x-bili-gaia-vvoucher``）；
2. ``POST /x/gaia-vgate/v1/register``（body: ``v_voucher`` + ``csrf=bili_jct``）
   → ``data.type`` / ``data.token`` / ``data.geetest{gt, challenge}``；
   **同一个 ``v_voucher`` 只能 register 一次，必须尽快验证**；
3. ``utils.geetest_solver.solve(gt, challenge)`` → ``(validate, seccode)``；
4. ``POST /x/gaia-vgate/v1/validate``（body: ``challenge`` / ``token`` / ``validate`` / ``seccode`` + ``csrf``）
   → ``data.grisk_id``（即 ``gaia_vtoken``）；
5. 原请求带上 URL 参数 ``gaia_vtoken=<grisk_id>`` + Cookie ``x-bili-gaia-vtoken=<grisk_id>``。

约束（都在代码里落实）：

- **必须由 UI 触发**：求解要过人机验证、失败还消耗风控额度 → 本模块只提供能力，绝不自动调用；
- captcha 是**最后手段**，``register`` 返回 ``geetest: null`` 时**不可解**
  → 返回可解释原因，不抛异常；
- ``grisk_id`` 有效期有限 → 只做**会话级**缓存（实例属性 + Cookie），过期自动失效，不写持久化配置。
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

REGISTER_URL = "/x/gaia-vgate/v1/register"
VALIDATE_URL = "/x/gaia-vgate/v1/validate"
GAIA_VTOKEN_PARAM = "gaia_vtoken"
GAIA_VTOKEN_COOKIE = "x-bili-gaia-vtoken"
# 有效期官方未公开，保守按 10 分钟；宁可多验证一次，也别带过期 token 去重试
VTOKEN_TTL = 600.0

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_FAILED = "failed"

SolverFn = Callable[[str, str], Optional[Tuple[str, str]]]


@dataclass
class GaiaResult:
    """一次 gaia 解除尝试的结果。"""

    status: str
    message: str = ""
    vtoken: str = ""

    @property
    def ok(self) -> bool:
        """是否拿到了可用的 ``gaia_vtoken``。"""
        return self.status == STATUS_OK and bool(self.vtoken)


def _csrf(api: Any) -> str:
    """当前会话的 csrf（Cookie 里的 ``bili_jct``）。"""
    return str((getattr(api, "_cookies", {}) or {}).get("bili_jct", "") or "")


def _default_solver() -> Optional[SolverFn]:
    """默认求解器（``utils.geetest_solver.solve``）；依赖缺失时返回 None。"""
    try:
        from utils.geetest_solver import solve
    except Exception as e:  # 求解器依赖缺失不应影响本模块被 import
        logger.debug("验证码求解器不可用: %s", e)
        return None
    return solve


def register(api: Any, v_voucher: str) -> Tuple[Dict[str, Any], str]:
    """第 2 步：用 ``v_voucher`` 注册挑战，返回 ``(data, 错误说明)``。"""
    payload = {"v_voucher": v_voucher, "csrf": _csrf(api)}
    data = api._request("POST", REGISTER_URL, data=payload)
    if not isinstance(data, dict):
        return {}, "register 失败（无响应数据）"
    geetest = data.get("geetest") or {}
    if not isinstance(geetest, dict) or not (geetest.get("gt") and geetest.get("challenge")):
        return data, "该风控无法用验证码解除（register 未返回 geetest），请稍后重试或更换网络"
    return data, ""


def validate(api: Any, challenge: str, token: str, validate_code: str, seccode: str) -> Tuple[str, str]:
    """第 4 步：提交验证结果，返回 ``(grisk_id, 错误说明)``。"""
    payload = {
        "challenge": challenge,
        "token": token,
        "validate": validate_code,
        "seccode": seccode,
        "csrf": _csrf(api),
    }
    data = api._request("POST", VALIDATE_URL, data=payload)
    if not isinstance(data, dict):
        return "", "validate 失败（无响应数据）"
    vtoken = str(data.get("grisk_id") or "")
    if not vtoken:
        message = str(data.get("message", "") or "")
        return "", f"validate 未返回 grisk_id（{message or '未知原因'}）"
    return vtoken, ""


def solve_challenge(api: Any, v_voucher: str = "", *, solver: Optional[SolverFn] = None) -> GaiaResult:
    """执行第 2-4 步；``v_voucher`` 留空时回退到 ``api._risk_last_voucher``。

    只在拿到 ``grisk_id`` 时才会写入会话缓存（成功路径之外零副作用）。
    """
    voucher = str(v_voucher or getattr(api, "_risk_last_voucher", "") or "")
    if not voucher:
        return GaiaResult(STATUS_FAILED, "没有可用的 v_voucher（需先命中一次风控挑战）")
    data, error = register(api, voucher)
    if error:
        return GaiaResult(STATUS_UNAVAILABLE if data else STATUS_FAILED, error)
    geetest = data.get("geetest") or {}
    gt = str(geetest.get("gt") or "")
    challenge = str(geetest.get("challenge") or "")
    token = str(data.get("token") or "")
    solve = solver if solver is not None else _default_solver()
    if solve is None:
        return GaiaResult(STATUS_FAILED, "验证码求解器不可用（缺少 utils.geetest_solver 依赖）")
    try:
        solved = solve(gt, challenge)
    except Exception as e:
        logger.warning("验证码求解异常: %s", e)
        return GaiaResult(STATUS_FAILED, f"验证码求解异常：{e}")
    if not solved:
        return GaiaResult(STATUS_FAILED, "验证码求解失败（可能被识别为自动化），请稍后重试或更换网络")
    validate_code, seccode = solved
    vtoken, error = validate(api, challenge, token, validate_code, seccode)
    if error:
        return GaiaResult(STATUS_FAILED, error)
    store_vtoken(api, vtoken)
    return GaiaResult(STATUS_OK, "风控已解除，可重试原请求", vtoken)


def store_vtoken(api: Any, vtoken: str, *, ttl: float = VTOKEN_TTL) -> None:
    """写入会话级缓存：实例属性 + Cookie（**不持久化**，过期即失效）。"""
    if not vtoken:
        return
    api._gaia_vtoken = vtoken
    api._gaia_vtoken_expire = time.time() + max(0.0, float(ttl))
    cookies = dict(getattr(api, "_cookies", {}) or {})
    cookies[GAIA_VTOKEN_COOKIE] = vtoken
    setter = getattr(api, "set_cookies", None)
    if callable(setter):
        setter(cookies)
    else:
        api._cookies = cookies


def current_vtoken(api: Any) -> str:
    """取当前有效的 ``gaia_vtoken``（过期/不存在返回空串）。"""
    vtoken = str(getattr(api, "_gaia_vtoken", "") or "")
    if not vtoken:
        return ""
    expire = float(getattr(api, "_gaia_vtoken_expire", 0.0) or 0.0)
    if expire and expire <= time.time():
        return ""
    return vtoken


def clear_vtoken(api: Any) -> None:
    """清除会话级 token（排障 / 手动失效）。"""
    api._gaia_vtoken = ""
    api._gaia_vtoken_expire = 0.0
    cookies = dict(getattr(api, "_cookies", {}) or {})
    cookies.pop(GAIA_VTOKEN_COOKIE, None)
    setter = getattr(api, "set_cookies", None)
    if callable(setter):
        setter(cookies)
    else:
        api._cookies = cookies


def with_gaia_vtoken(api: Any, params: Dict[str, Any], *, vtoken: Optional[str] = None) -> Dict[str, Any]:
    """有有效 token 时把 ``gaia_vtoken`` 并入参数；否则**原样返回**（默认零副作用）。"""
    resolved = vtoken if vtoken is not None else current_vtoken(api)
    if not resolved:
        return dict(params)
    merged = dict(params)
    merged[GAIA_VTOKEN_PARAM] = resolved
    return merged


def gaia_state(api: Any) -> Dict[str, Any]:
    """观测：是否持有有效 token 及剩余有效期。"""
    vtoken = current_vtoken(api)
    expire = float(getattr(api, "_gaia_vtoken_expire", 0.0) or 0.0)
    return {
        "has_vtoken": bool(vtoken),
        "remaining": round(max(0.0, expire - time.time()), 1) if vtoken else 0.0,
        "has_voucher": bool(getattr(api, "_risk_last_voucher", "") or ""),
    }
