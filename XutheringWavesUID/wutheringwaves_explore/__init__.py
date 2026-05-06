from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_explore_card import draw_explore_img
from ..utils.error_reply import WAVES_CODE_103
from ..utils.database.models import WavesBind

waves_get_explore = SV("waves获取探索度")


@waves_get_explore.on_fullmatch(
    (
        "ts",
        "探索",
        "tsd",
        "探索度",
    )
)
async def send_card_info(bot: Bot, ev: Event):
    user_id = ruser_id(ev)

    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    msg = await draw_explore_img(ev, uid, user_id)
    return await bot.send(msg)
