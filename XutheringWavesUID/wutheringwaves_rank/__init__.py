from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .darw_rank_card import draw_rank_img
from .draw_all_rank_card import draw_all_rank_card
from .draw_rank_list_card import draw_rank_list
from .draw_total_rank_card import draw_total_rank
from ..utils.char_info_utils import PATTERN
from ..utils.name_resolve import resolve_char

sv_waves_rank_list = SV("ww角色排行", priority=3)
sv_waves_rank_all_list = SV("ww角色总排行", priority=1)
sv_waves_rank_total_list = SV("ww练度总排行", priority=0)
sv_waves_rank_local_list = SV("ww练度排行", priority=0)


@sv_waves_rank_list.on_regex(rf"^(?P<char>{PATTERN})(?:排行|排行榜|排名|ph|pm)$", block=True)
async def send_rank_card(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")

    char = ev.regex_dict.get("char")

    rank_type = "伤害"
    if "评分" in char or "pf" in char or "练度" in char:
        rank_type = "评分"

    char = (
        char.replace("伤害", "").replace("评分", "").replace("pf", "")
        .replace("练度", "").replace("本群", "").replace("群", "")
    )

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        from ..wutheringwaves_config import PREFIX
        if rank_type == "评分":
            canonical_cmd = f"{PREFIX}{char}评分排行"
        else:
            canonical_cmd = f"{PREFIX}{char}排行"

    im = await draw_rank_img(bot, ev, char, rank_type)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


@sv_waves_rank_all_list.on_regex(rf"^(?P<char>{PATTERN})(?:总排行|总排行榜|总排名|zph|zpm)(?P<pages>\d+)?$", block=True)
async def send_all_rank_card(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    pages = ev.regex_dict.get("pages")

    if pages:
        pages = int(pages)
    else:
        pages = 1

    if pages > 5:
        pages = 5
    elif pages < 1:
        pages = 1

    rank_type = "伤害"
    if "评分" in char or "练度" in char:
        rank_type = "评分"
    char = char.replace("伤害", "").replace("评分", "").replace("练度", "")

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        from ..wutheringwaves_config import PREFIX
        if rank_type == "评分":
            canonical_cmd = f"{PREFIX}{char}评分总排行"
        else:
            canonical_cmd = f"{PREFIX}{char}总排行"

    im = await draw_all_rank_card(bot, ev, char, rank_type, pages)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


@sv_waves_rank_total_list.on_regex(r"^(练度总排行|练度总排行榜|练度总排名|ldzph|ldzpm)(?P<pages>\d+)?$", block=True)
async def send_total_rank_card(bot: Bot, ev: Event):
    pages = ev.regex_dict.get("pages")

    if pages:
        pages = int(pages)
    else:
        pages = 1

    if pages > 5:
        pages = 5
    elif pages < 1:
        pages = 1

    im = await draw_total_rank(bot, ev, pages)
    await bot.send(im)


@sv_waves_rank_local_list.on_command(
    ("练度排行", "群练度排行", "练度群排行", "练度群排行榜", "练度排名", "群练度排名", "练度群排名", "ldph", "ldpm"), block=True
)
async def send_rank_list_card(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")

    im = await draw_rank_list(bot, ev)
    await bot.send(im)
