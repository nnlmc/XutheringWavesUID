"""launcher SDK 高层调用链：从 DB 读凭据 → 走 SDK 拿 PlayerPanelData。

提供给 mr 体力 / ScoreEcho 等多处复用，统一处理凭据续期与回写。
"""

from __future__ import annotations

from typing import Optional

from gsuid_core.logger import logger

from ..constants import WAVES_GAME_ID
from ..database.models import WavesUser, WavesUserSdk
from .api_sdk import PlayerPanelData, launcher_sdk


async def fetch_launcher_panel(
    user_id: str, bot_id: str, uid: str
) -> Optional[PlayerPanelData]:
    """对指定 launcher SDK uid 拉取 ``PlayerPanelData``。

    自动处理凭据续期：先用现有 ``access_token`` 试一次，过期再用 ``auto_token``
    跑 ``auto_login`` + ``exchange_access_token`` 续登并把新凭据回写 ``WavesUser``。
    """
    waves_user = await WavesUser.select_waves_user(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
    if not waves_user:
        logger.info(f"[launcher_chain] 没有 WavesUser uid={uid} user_id={user_id}")
        return None
    if not waves_user.cookie:
        logger.info(f"[launcher_chain] WavesUser.cookie 为空 uid={uid}")
        return None
    if waves_user.status == "无效":
        logger.info(f"[launcher_chain] WavesUser 已被标记为无效 uid={uid}")
        return None

    region = await WavesUserSdk.get_region(user_id, bot_id, uid)
    if not region:
        logger.info(f"[launcher_chain] WavesUserSdk 没有 region 记录 uid={uid}")
        return None

    return await _fetch_with_refresh(
        uid=uid,
        region=region,
        auto_token=waves_user.cookie,
        access_token=waves_user.bat or "",
        device_no=waves_user.did or "",
        user_id=user_id,
        bot_id=bot_id,
    )


async def _fetch_with_refresh(
    *,
    uid: str,
    region: str,
    auto_token: str,
    access_token: str,
    device_no: str,
    user_id: str,
    bot_id: str,
) -> Optional[PlayerPanelData]:
    async def _query(at: str) -> Optional[PlayerPanelData]:
        oc = await launcher_sdk.make_oauth_code(at, device_no=device_no)
        if not oc.success or not oc.data:
            return None
        panel = await launcher_sdk.query_player_panel(oc.data, uid, region)
        return panel.data if panel.success and panel.data else None

    if access_token:
        data = await _query(access_token)
        if data is not None:
            return data

    login = await launcher_sdk.auto_login(auto_token, device_no=device_no)
    if not login.success or not login.data:
        logger.warning(f"[launcher_chain] auto_login 失败 uid={uid} msg={login.msg!r}")
        return None

    tok = await launcher_sdk.exchange_access_token(login.data.code, device_no=device_no)
    if not tok.success or not tok.data:
        logger.warning(f"[launcher_chain] exchange_token 失败 uid={uid} msg={tok.msg!r}")
        return None

    new_auto = login.data.auto_token
    new_access = tok.data.access_token
    try:
        await WavesUser.update_data_by_data(
            select_data={
                "user_id": user_id,
                "bot_id": bot_id,
                "uid": uid,
                "game_id": WAVES_GAME_ID,
            },
            update_data={"cookie": new_auto, "bat": new_access, "status": ""},
        )
    except Exception:
        logger.exception(f"[launcher_chain] 凭据回写失败 uid={uid}")

    return await _query(new_access)
