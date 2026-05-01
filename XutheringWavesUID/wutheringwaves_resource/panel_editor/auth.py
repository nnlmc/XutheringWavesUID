"""HTTP Basic Auth 鉴权 + per-IP 暴力破解防护。

简单密码: 用户名固定为 admin, 密码读取 WutheringWavesConfig.WavesPanelEditPassword。
密码为空 -> 关闭工具 (返回 503)。
失败 >= LOCKOUT_THRESHOLD 次 / WINDOW 秒 -> 锁该 IP LOCKOUT_SECONDS 秒 (返 429)。
"""

import base64
import secrets
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status
from gsuid_core.logger import logger

from ...wutheringwaves_config import WutheringWavesConfig


REALM = "WutheringWaves Panel Editor"

# 每 IP 在 WINDOW 秒内最多失败 THRESHOLD 次, 触发后冷却 LOCKOUT_SECONDS。
_BF_WINDOW = 600          # 10 分钟滑动窗口
_BF_THRESHOLD = 5         # 5 次失败
_BF_LOCKOUT = 900         # 锁定 15 分钟
_BF_GC_INTERVAL = 300     # 每 5 分钟扫一次, 清掉无活动的旧条目

_bf_failures: Dict[str, Deque[float]] = {}
_bf_locks: Dict[str, float] = {}
_bf_last_gc = 0.0


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。仅当上游是回环时才信任 X-Real-IP / X-Forwarded-For,
    否则可被攻击者伪造。"""
    direct = request.client.host if request.client else ""
    if direct in ("127.0.0.1", "::1", "localhost"):
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return direct or "?"


def _bf_gc(now: float) -> None:
    global _bf_last_gc
    if now - _bf_last_gc < _BF_GC_INTERVAL:
        return
    _bf_last_gc = now
    expire_locks = [ip for ip, until in _bf_locks.items() if until <= now]
    for ip in expire_locks:
        _bf_locks.pop(ip, None)
    for ip, dq in list(_bf_failures.items()):
        while dq and now - dq[0] > _BF_WINDOW:
            dq.popleft()
        if not dq:
            _bf_failures.pop(ip, None)


def _bf_check_locked(ip: str, now: float) -> Optional[int]:
    until = _bf_locks.get(ip)
    if until is None:
        return None
    if until <= now:
        _bf_locks.pop(ip, None)
        _bf_failures.pop(ip, None)
        return None
    return int(until - now)


def _bf_record_failure(ip: str, now: float) -> None:
    dq = _bf_failures.setdefault(ip, deque())
    dq.append(now)
    while dq and now - dq[0] > _BF_WINDOW:
        dq.popleft()
    if len(dq) >= _BF_THRESHOLD:
        _bf_locks[ip] = now + _BF_LOCKOUT
        logger.warning(
            f"[鸣潮·面板编辑] auth lockout ip={ip} "
            f"(连续 {len(dq)} 次失败, 冷却 {_BF_LOCKOUT}s)"
        )


def _bf_record_success(ip: str) -> None:
    _bf_failures.pop(ip, None)
    _bf_locks.pop(ip, None)


# ------------------------- 预览限速 (per-IP rolling window) -------------------------
# 预览端点目前仅 admin 可达, 访客早被 require_auth 顶回。
# 这里只保护已登录管理员被脚本/笔误打爆 Playwright/CPU。

_PREVIEW_WINDOW = 60.0     # 秒
_PREVIEW_LIMIT = 30        # 60s 内最多 N 次
_preview_calls: Dict[str, Deque[float]] = {}


def check_preview_rate(request: Request) -> None:
    """命中预览端点前调用。超额抛 429。"""
    now = time.monotonic()
    ip = _client_ip(request)
    dq = _preview_calls.setdefault(ip, deque())
    while dq and now - dq[0] > _PREVIEW_WINDOW:
        dq.popleft()
    if len(dq) >= _PREVIEW_LIMIT:
        retry = int(_PREVIEW_WINDOW - (now - dq[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Preview rate limit exceeded ({_PREVIEW_LIMIT}/min). Retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    dq.append(now)
    if len(_preview_calls) > 256:
        for k in list(_preview_calls.keys()):
            if not _preview_calls[k]:
                _preview_calls.pop(k, None)


def _configured_password() -> Optional[str]:
    pwd = WutheringWavesConfig.get_config("WavesPanelEditPassword").data
    if pwd is None:
        return None
    pwd = str(pwd).strip()
    return pwd or None


def is_enabled() -> bool:
    return _configured_password() is not None


def is_guest_view_enabled() -> bool:
    """配置开关: 允许未登录的访客只读浏览。"""
    try:
        return bool(WutheringWavesConfig.get_config("WavesPanelEditGuestView").data)
    except Exception:
        return False


def _validate_basic(header: str, pwd: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8", errors="ignore")
        user, _, given = decoded.partition(":")
    except Exception:
        return False
    return secrets.compare_digest(user, "admin") and secrets.compare_digest(given, pwd)


_UNAUTH_HEADERS = {"WWW-Authenticate": f'Basic realm="{REALM}"'}


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers=_UNAUTH_HEADERS,
    )


def require_auth(request: Request) -> None:
    """FastAPI dependency: 仅 admin 可通过, 其它一律 401/429。"""
    role = _resolve_role(request, allow_guest=False)
    if role != "admin":
        raise _unauthorized()


def auth_or_guest(request: Request) -> str:
    """读类接口的鉴权 dependency。返回 'admin' 或 'guest'。
    - 已配置密码且配置允许访客 + 请求无 Authorization → 'guest'
    - 已配置密码且 Authorization 正确 → 'admin'
    - 其它 → 401 / 429 / 503。
    """
    return _resolve_role(request, allow_guest=is_guest_view_enabled())


def _resolve_role(request: Request, *, allow_guest: bool) -> str:
    pwd = _configured_password()
    if not pwd:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="面板图编辑工具未启用 (请在配置中设置 WavesPanelEditPassword)",
        )

    now = time.monotonic()
    _bf_gc(now)
    ip = _client_ip(request)
    header = request.headers.get("authorization", "")

    # 无凭据: 访客模式直接放行只读, 否则要求登录。
    if not header.lower().startswith("basic "):
        if allow_guest:
            return "guest"
        raise _unauthorized()

    # 有凭据 → 进入登录路径, 受暴力破解保护
    locked = _bf_check_locked(ip, now)
    if locked is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Retry in {locked}s.",
            headers={"Retry-After": str(locked)},
        )

    if _validate_basic(header, pwd):
        _bf_record_success(ip)
        return "admin"

    _bf_record_failure(ip, now)
    raise _unauthorized()
