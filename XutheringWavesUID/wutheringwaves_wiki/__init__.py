from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from .guide import get_guide
from .draw_char import draw_char_wiki
from .draw_echo import draw_wiki_echo
from .draw_list import draw_sonata_list, draw_weapon_list
from .draw_tower import draw_slash_challenge_img, draw_tower_challenge_img, draw_matrix_challenge_img
from .draw_weapon import draw_wiki_weapon
from ..utils import name_convert
from ..utils.name_convert import char_name_to_char_id, ensure_data_loaded
from ..utils.fuzzy_match import fuzzy_suggest, fuzzy_suggest_multi
from ..utils.char_info_utils import PATTERN
from ..wutheringwaves_abyss.period import (
    get_tower_period_number,
    get_slash_period_number,
    get_matrix_period_number,
)

sv_waves_guide = SV("鸣潮攻略", priority=10)
sv_waves_tower = SV("waves查询深塔信息", priority=4)
sv_waves_slash_info = SV("waves查询海墟信息", priority=4)
sv_waves_matrix_info = SV("waves查询矩阵信息", priority=4)


@sv_waves_guide.on_regex(
    rf"^(?P<wiki_name>{PATTERN})(?P<wiki_type>共鸣链|共鳴鏈|gml|命座|天赋|天賦|技能|jn|图鉴|圖鑑|专武|專武|wiki|介绍|介紹|回路|操作|机制|機制|jz)$",
    block=True,
)
async def send_waves_wiki(bot: Bot, ev: Event):
    wiki_name = ev.regex_dict.get("wiki_name", "")
    wiki_type = ev.regex_dict.get("wiki_type", "")

    at_sender = True if ev.group_id else False
    if wiki_type in ("共鸣链", "共鳴鏈", "gml", "命座", "天赋", "天賦", "技能", "jn", "回路", "操作", "机制", "機制", "jz"):
        char_name = wiki_name

        if wiki_type in ("技能", "天赋", "天賦", "jn"):
            query_role_type = "技能"
        elif wiki_type in ("共鸣链", "共鳴鏈", "命座", "gml"):
            query_role_type = "共鸣链"
        elif wiki_type in ("回路", "操作", "机制", "機制", "jz"):
            query_role_type = "机制"
        else:
            query_role_type = wiki_type

        char_id = char_name_to_char_id(char_name)
        if char_id:
            img = await draw_char_wiki(char_id, query_role_type)
            if not isinstance(img, str):
                return await bot.send(img)

        ensure_data_loaded()
        suggestions = fuzzy_suggest(char_name, name_convert.char_alias_data, top_n=3)
        for cand_name, _ in suggestions:
            cand_id = char_name_to_char_id(cand_name)
            if not cand_id:
                continue
            cand_img = await draw_char_wiki(cand_id, query_role_type)
            if isinstance(cand_img, str):
                continue
            from ..wutheringwaves_config import PREFIX
            cmd = f"{PREFIX}{cand_name}{query_role_type}"
            msg = f"[鸣潮] 你可能想查询【{cmd}】，已执行该指令"
            return await bot.send([msg, MessageSegment.image(cand_img)], at_sender=at_sender)

        if suggestions:
            names = "、".join(n for n, _ in suggestions)
            msg = f"[鸣潮] 未找到指定角色。\n你可能想找: {names}"
        else:
            msg = "[鸣潮] 未找到指定角色, 请先检查输入是否正确！"
        return await bot.send(msg, at_sender)
    else:
        if wiki_type in ("专武", "專武"):
            wiki_name = wiki_name + "专武"
        img = await draw_wiki_weapon(wiki_name)
        if isinstance(img, str) or not img:
            echo_name = wiki_name
            await bot.logger.info(f"[鸣潮] 开始获取{echo_name}wiki")
            img = await draw_wiki_echo(echo_name)

        if not (isinstance(img, str) or not img):
            return await bot.send(img)

        ensure_data_loaded()
        suggestions = fuzzy_suggest_multi(
            wiki_name,
            [("武器", name_convert.weapon_alias_data), ("共鸣", name_convert.echo_alias_data)],
            top_n=3,
        )
        for label, cand_name, _ in suggestions:
            if label == "武器":
                cand_img = await draw_wiki_weapon(cand_name)
            else:
                cand_img = await draw_wiki_echo(cand_name)
            if isinstance(cand_img, str) or not cand_img:
                continue
            from ..wutheringwaves_config import PREFIX
            cmd = f"{PREFIX}{cand_name}介绍"
            msg = f"[鸣潮] 你可能想查询【{cmd}】，已执行该指令"
            return await bot.send([msg, MessageSegment.image(cand_img)], at_sender=at_sender)

        if suggestions:
            names = "、".join(n for _, n, _ in suggestions)
            msg = f"[鸣潮] wiki未找到指定内容。\n你可能想找: {names}"
        else:
            msg = "[鸣潮] wiki未找到指定内容, 请先检查输入是否正确！"
        return await bot.send(msg, at_sender)


@sv_waves_guide.on_regex(rf"^(?P<char>{PATTERN})(?:攻略|gl)$", block=True)
async def send_role_guide_pic(bot: Bot, ev: Event):
    char_name = ev.regex_dict.get("char", "")
    if "设置排除" in char_name:
        return

    await get_guide(bot, ev, char_name)


@sv_waves_guide.on_regex(rf"^(?P<type>{PATTERN})?(?:(?:武器)?列表|武器|wq(?:lb)?)$", block=True)
async def send_weapon_list(bot: Bot, ev: Event):
    weapon_type = ev.regex_dict.get("type", "")
    img = await draw_weapon_list(weapon_type)
    await bot.send(img)


@sv_waves_guide.on_regex(r"^(?:(?P<version_pre>\d+\.\d+))?(?:套装|套裝)(列表)?(?:(?P<version_post>\d+\.\d+))?$", block=True)
async def send_sonata_list(bot: Bot, ev: Event):
    # 版本号可以在前面或后面
    version = ev.regex_dict.get("version_pre") or ev.regex_dict.get("version_post") or ""
    await bot.send(await draw_sonata_list(version))


@sv_waves_tower.on_regex(
    r"^(?:深塔|st)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?$",
    block=True,
)
async def send_tower_challenge_info(bot: Bot, ev: Event):
    """查询深塔挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "")
    
    current_period = get_tower_period_number()
    target_period = current_period
    
    if period_val:
        if period_val.isdigit():
            target_period = int(period_val)
        elif period_val in ("下一期", "下期"):
            target_period = current_period + 1
        elif period_val == "下下期":
            target_period = current_period + 2
        elif period_val in ("上一期", "上期"):
            target_period = current_period - 1
        elif period_val == "上上期":
            target_period = current_period - 2
    # If period_val is empty, target_period remains current_period, which is the desired default.

    im = await draw_tower_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)

@sv_waves_slash_info.on_regex(
    r"^(?:海墟|冥海|无尽|無盡|hx|wj)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?$",
    block=True,
)
async def send_slash_challenge_info(bot: Bot, ev: Event):
    """查询海墟挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "")
    
    current_period = get_slash_period_number()
    target_period = current_period
    
    if period_val:
        if period_val.isdigit():
            target_period = int(period_val)
        elif period_val in ("下一期", "下期"):
            target_period = current_period + 1
        elif period_val == "下下期":
            target_period = current_period + 2
        elif period_val in ("上一期", "上期"):
            target_period = current_period - 1
        elif period_val == "上上期":
            target_period = current_period - 2

    im = await draw_slash_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)


@sv_waves_matrix_info.on_regex(
    r"^(?:矩阵|矩陣|jz信息|matrix)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?$",
    block=True,
)
async def send_matrix_challenge_info(bot: Bot, ev: Event):
    """查询矩阵挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "")

    current_period = get_matrix_period_number()
    target_period = current_period

    if period_val:
        if period_val.isdigit():
            target_period = int(period_val)
        elif period_val in ("下一期", "下期"):
            target_period = current_period + 1
        elif period_val == "下下期":
            target_period = current_period + 2
        elif period_val in ("上一期", "上期"):
            target_period = current_period - 1
        elif period_val == "上上期":
            target_period = current_period - 2

    im = await draw_matrix_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)
