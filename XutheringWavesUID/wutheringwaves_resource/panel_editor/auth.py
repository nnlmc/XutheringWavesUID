"""HTTP Basic Auth 鉴权。

简单密码: 用户名固定为 admin, 密码读取 WutheringWavesConfig.WavesPanelEditPassword。
密码为空 -> 关闭工具 (返回 503)。
"""

import base64
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status
from starlette.responses import Response

from ...wutheringwaves_config import WutheringWavesConfig


REALM = "WutheringWaves Panel Editor"


def _configured_password() -> Optional[str]:
    pwd = WutheringWavesConfig.get_config("WavesPanelEditPassword").data
    if pwd is None:
        return None
    pwd = str(pwd).strip()
    return pwd or None


def is_enabled() -> bool:
    return _configured_password() is not None


def _challenge() -> Response:
    return Response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        content="Unauthorized",
    )


def require_auth(request: Request) -> None:
    """FastAPI dependency: 校验 HTTP Basic Auth, 失败 raise HTTPException。"""
    pwd = _configured_password()
    if not pwd:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="面板图编辑工具未启用 (请在配置中设置 WavesPanelEditPassword)",
        )

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        )

    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8", errors="ignore")
        user, _, given = decoded.partition(":")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        )

    if not (secrets.compare_digest(user, "admin") and secrets.compare_digest(given, pwd)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        )
