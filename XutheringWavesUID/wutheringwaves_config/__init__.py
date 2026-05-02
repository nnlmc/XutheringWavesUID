from gsuid_core.sv import SV, get_plugin_available_prefix
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .set_config import set_waves_user_value
from .wutheringwaves_config import WutheringWavesConfig, ShowConfig
from ..utils.constants import WAVES_GAME_ID
from ..utils.database.models import WavesBind, WavesLangSettings, WavesUser

sv_self_config = SV("鸣潮配置")


PREFIX = get_plugin_available_prefix("XutheringWavesUID")


@sv_self_config.on_prefix("设置", block=True)
async def send_config_ev(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False

    # 语言设置不需要绑定uid
    if "语言" in ev.text or "語言" in ev.text:
        VALID_LANGS = {"chs", "cht", "en", "jp", "kr"}
        lang = ev.text.replace("语言", "").replace("語言", "").strip().lower()
        if lang not in VALID_LANGS:
            msg = f"[鸣潮] 语言设置参数无效\n可选: {', '.join(sorted(VALID_LANGS))}"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        db_value = "" if lang == "chs" else lang
        await WavesLangSettings.set_lang(ev.user_id, db_value)
        msg = f"[鸣潮] 语言已设置为 {lang}"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if uid is None:
        msg = f"您还未绑定鸣潮特征码, 请使用【{PREFIX}绑定uid】 完成绑定！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    if "体力背景" in ev.text:
        # 只是写库，存在 WavesUser 行就够（CK 或 launcher SDK 登录均会建行），
        # 没必要走 get_self_waves_ck 的活性校验
        waves_user = await WavesUser.select_waves_user(
            uid, ev.user_id, ev.bot_id, game_id=WAVES_GAME_ID
        )
        if not waves_user:
            from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102

            msg = f"当前特征码：{uid}\n{ERROR_CODE[WAVES_CODE_102].rstrip(chr(10))}"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        func = "体力背景"
        value = ev.text.replace("体力背景", "").strip()
        # if not value:
        #     char_name = ""
        # char_name = alias_to_char_name(value)
        # im = await set_waves_user_value(ev, func, uid, char_name)
        im = await set_waves_user_value(ev, func, uid, value)
    elif "群排行" in ev.text:
        if ev.user_pm > 3:
            msg = "[鸣潮] 群排行设置需要群管理才可设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        if not ev.group_id:
            msg = "[鸣潮] 请使用群聊进行设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        WavesRankUseTokenGroup = set(WutheringWavesConfig.get_config("WavesRankUseTokenGroup").data)
        WavesRankNoLimitGroup = set(WutheringWavesConfig.get_config("WavesRankNoLimitGroup").data)

        if "1" in ev.text:
            # 设置为 无限制
            WavesRankNoLimitGroup.add(ev.group_id)
            # 删除token限制
            WavesRankUseTokenGroup.discard(ev.group_id)
            msg = f"[鸣潮] 【{ev.group_id}】群排行已设置为[无限制上榜]"
        elif "2" in ev.text:
            # 设置为 token限制
            WavesRankUseTokenGroup.add(ev.group_id)
            # 删除无限制
            WavesRankNoLimitGroup.discard(ev.group_id)
            msg = f"[鸣潮] 群【{ev.group_id}】群排行已设置为[登录后上榜]"
        else:
            msg = "[鸣潮] 群排行设置参数失效\n1.无限制上榜\n2.登录后上榜"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        WutheringWavesConfig.set_config("WavesRankUseTokenGroup", list(WavesRankUseTokenGroup))
        WutheringWavesConfig.set_config("WavesRankNoLimitGroup", list(WavesRankNoLimitGroup))
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    
    elif "排除攻略" in ev.text:
        if ev.user_pm > 3:
            msg = "[鸣潮] 排除攻略设置需要群管理才可设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        if not ev.group_id:
            msg = "[鸣潮] 请使用群聊进行设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        from .guide_config import (
            load_guide_config,
            save_guide_config,
            parse_provider_names,
        )

        # 提取攻略提供方名称
        provider_text = ev.text.replace("排除攻略", "").strip()

        guide_config = load_guide_config()

        if not provider_text:
            # 清空当前群的排除设置
            if ev.group_id in guide_config:
                del guide_config[ev.group_id]
                save_guide_config(guide_config)
            msg = f"[鸣潮] 群【{ev.group_id}】已清空排除攻略设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        # 解析提供方名称
        providers = parse_provider_names(provider_text)
        if not providers:
            msg = "[鸣潮] 未识别到有效的攻略提供方名称"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        # 保存配置
        guide_config[ev.group_id] = providers
        save_guide_config(guide_config)

        msg = (
            f"[鸣潮] 群【{ev.group_id}】已设置排除攻略提供方:\n"
            + "\n".join(f"  - {p}" for p in providers)
        )
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    
    elif "抽卡条件" in ev.text:
        if ev.user_pm > 3:
            msg = "[鸣潮] 抽卡条件设置需要群管理才可设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        if not ev.group_id:
            msg = "[鸣潮] 请使用群聊进行设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        from .gacha_config import load_gacha_config, save_gacha_config, parse_gacha_min_value

        value_text = ev.text.replace("抽卡条件", "").strip()
        gacha_config = load_gacha_config()

        if not value_text:
            if str(ev.group_id) in gacha_config:
                del gacha_config[str(ev.group_id)]
                save_gacha_config(gacha_config)
            msg = f"[鸣潮] 群【{ev.group_id}】已清空抽卡条件设置"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        min_pull = parse_gacha_min_value(value_text)
        if min_pull is None:
            msg = "[鸣潮] 未识别到有效的抽卡阈值"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        gacha_config[str(ev.group_id)] = min_pull
        save_gacha_config(gacha_config)
        msg = f"[鸣潮] 群【{ev.group_id}】已设置抽卡条件阈值: {min_pull}"
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    else:
        msg = "请输入正确的设置信息..."
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    msg = im.rstrip("\n") if isinstance(im, str) else im
    await bot.send((" " if at_sender else "") + msg if isinstance(msg, str) else msg, at_sender)
