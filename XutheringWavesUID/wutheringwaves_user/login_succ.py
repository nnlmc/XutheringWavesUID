from typing import Any, List

from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.button import WavesButton
from ..utils.database.models import WavesBind, WavesUser
from ..wutheringwaves_config import PREFIX


async def _build_bind_summary(user_id: str, bot_id: str) -> str:
    """构建两个游戏的绑定概要"""
    waves_uids = await WavesBind.get_uid_list_by_game(user_id, bot_id) or []
    pgr_uids = await WavesBind.get_uid_list_by_game(user_id, bot_id, game_name="pgr") or []

    if not waves_uids and not pgr_uids:
        return ""

    lines = []
    for uid in waves_uids:
        lines.append(f"  [鸣潮] {uid}")
    for uid in pgr_uids:
        lines.append(f"  [战双] {uid}")
    return "\n".join(lines)


async def login_success_msg(bot: Bot, ev: Event, waves_user: WavesUser):
    buttons: List[Any] = [
        WavesButton("体力", "mr"),
        WavesButton("刷新面板", "刷新面板"),
        WavesButton("深塔", "深塔"),
        WavesButton("冥歌海墟", "冥海"),
    ]

    from ..wutheringwaves_charinfo.draw_refresh_char_card import (
        draw_refresh_char_detail_img,
    )

    msg, _, _ = await draw_refresh_char_detail_img(bot, ev, waves_user.user_id, waves_user.uid, buttons)
    if isinstance(msg, bytes):
        return await bot.send_option(msg, buttons)

    # 面板刷新失败，构建绑定概要
    at_sender = True if ev.group_id else False
    bind_summary = await _build_bind_summary(ev.user_id, ev.bot_id)

    if bind_summary:
        text = (
            f"当前已绑定的UID：\n{bind_summary}\n"
            f"发送【{PREFIX}切换】切换到指定鸣潮特征码"
        )
    else:
        uid = str(waves_user.uid or "")
        if uid.isdigit() and len(uid) == 9:
            text = f"[鸣潮] 登录失败，请稍后重试\n请检查库街区能否查询特征码[{uid}]的鸣潮账号数据"
        else:
            text = "[鸣潮] 登录失败，请稍后重试\n"

    return await bot.send((" " if at_sender else "") + text, at_sender=at_sender)
