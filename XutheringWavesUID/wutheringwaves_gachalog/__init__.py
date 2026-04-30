import re
import json
import time
import shutil
import asyncio
from datetime import datetime

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.data_store import get_res_path

from ..utils.cache import TimedCache
from .gacha_handler import fetch_mcgf_data, merge_gacha_data
from .get_gachalogs import save_gachalogs, export_gachalogs, import_gachalogs
from .draw_gachalogs import draw_card, draw_card_help
from ..utils.waves_api import waves_api
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102, WAVES_CODE_103
from ..utils.database.models import WavesBind
from ..wutheringwaves_config import PREFIX
from ..utils.resource.RESOURCE_PATH import PLAYER_PATH
from ..wutheringwaves_rank.draw_gacha_rank_card import draw_gacha_rank_card

sv_gacha_log = SV("waves抽卡记录")
sv_gacha_help_log = SV("waves抽卡记录帮助")
sv_gacha_rank = SV("waves抽卡排行", priority=0)
sv_get_gachalog_by_link = SV("waves导入抽卡链接", area="DIRECT")
sv_import_gacha_log = SV("waves导入抽卡记录", area="DIRECT")
sv_export_json_gacha_log = SV("waves导出抽卡记录")
sv_delete_gacha_log = SV("waves删除抽卡记录")
sv_delete_import_gacha_log = SV("waves删除抽卡导入", pm=0)

DATA_PATH = get_res_path()
GACHA_BACKUP_PATH = DATA_PATH / "backup" / "gacha_backup"

ERROR_MSG_NOTIFY = f"请给出正确的抽卡记录链接, 可发送【{PREFIX}抽卡帮助】"

# 导入抽卡记录的冷却缓存（固定10秒）
gacha_import_cache = TimedCache(timeout=10, maxsize=10000)


def can_import_gacha(user_id: str, uid: str) -> int:
    """检查是否可以导入抽卡记录，返回剩余冷却时间（秒），0表示可以导入"""
    key = f"{user_id}_{uid}"
    now = int(time.time())
    time_stamp = gacha_import_cache.get(key)
    if time_stamp and time_stamp > now:
        return time_stamp - now
    return 0


def set_gacha_import_cache(user_id: str, uid: str):
    """设置导入抽卡记录的缓存"""
    key = f"{user_id}_{uid}"
    gacha_import_cache.set(key, int(time.time()) + 10)


@sv_get_gachalog_by_link.on_command(("导入抽卡链接", "导入抽卡记录"), block=True)
async def get_gacha_log_by_link(bot: Bot, ev: Event):
    # 没有uid 就别导了吧
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    # 检查冷却
    remaining_time = can_import_gacha(ev.user_id, uid)
    if remaining_time > 0:
        return

    raw = ev.text.strip()
    if not raw:
        return await bot.send(ERROR_MSG_NOTIFY)

    # 检查是否为9位UID，若是则尝试从工坊获取并合并数据
    if raw.isdigit() and len(raw) == 9:
        target_uid = raw

        try:
            latest_data = await fetch_mcgf_data(target_uid)
            if not latest_data:
                return await bot.send("获取工坊数据失败或数据为空")

            export_res = await export_gachalogs(uid)
            original_data = {"info": {}, "list": []}

            if export_res["retcode"] == "ok":
                import aiofiles

                async with aiofiles.open(export_res["url"], "r", encoding="utf-8") as f:
                    original_data = json.loads(await f.read())

            if len(original_data.get("list", [])) == 0:
                return await bot.send("当前无抽卡记录，无法合并，请先用链接导入抽卡记录后再尝试合并！")

            # 合并数据
            if not original_data["info"].get("uid") == latest_data["data"].get("uid"):
                return await bot.send("导入数据UID与当前UID不匹配，无法合并！")
            merged_data = await asyncio.to_thread(merge_gacha_data, original_data, latest_data)

            # 导入合并后的数据
            merged_json_str = json.dumps(merged_data, ensure_ascii=False)
            im = await import_gachalogs(ev, merged_json_str, "json", uid, force_overwrite=True)
            await bot.send("导入仅包含早于本地记录的部分，此后请使用链接导入更新数据，或删除抽卡记录后再次链接导入+合并！")
            return await bot.send(im)

        except Exception as e:
            return await bot.send(f"处理过程中发生错误: {e}")

    text = re.sub(r'["\n\t ]+', "", raw)
    if "https://" in text:
        # 使用正则表达式匹配参数
        match_record_id = re.search(r"record_id=([a-zA-Z0-9]+)", text)
        match_player_id = re.search(r"player_id=(\d+)", text)
    elif "{" in text:
        match_record_id = re.search(r"recordId:([a-zA-Z0-9]+)", text)
        match_player_id = re.search(r"playerId:(\d+)", text)
    elif "recordId=" in text:
        match_record_id = re.search(r"recordId=([a-zA-Z0-9]+)", text)
        match_player_id = re.search(r"playerId=(\d+)", text)
    else:
        match_record_id = re.search(r"recordId=([a-zA-Z0-9]+)", "recordId=" + text)
        match_player_id = ""

    # 提取参数值
    record_id = match_record_id.group(1) if match_record_id else None
    player_id = match_player_id.group(1) if match_player_id else None

    if not record_id or len(record_id) != 32:
        return await bot.send(ERROR_MSG_NOTIFY)

    if player_id and player_id != uid:
        ERROR_MSG = f"请保证抽卡链接的特征码与当前正在使用的特征码一致\n\n请使用以下命令核查:\n{PREFIX}查看\n{PREFIX}切换{player_id}"
        return await bot.send(ERROR_MSG)

    is_force = False
    if ev.command.startswith("强制"):
        await bot.logger.info("[WARNING]本次为强制刷新")
        is_force = True
    await bot.send(f"UID{uid}开始执行[刷新抽卡记录],需要一定时间，请稍等!\n官方仅保存近180天抽卡记录，仅更新该部分。")
    im = await save_gachalogs(ev, uid, record_id, is_force)

    # 设置冷却缓存
    set_gacha_import_cache(ev.user_id, uid)

    if im.startswith("🌱"):
        card_img = await draw_card(uid, ev)
        if isinstance(card_img, str):
            await bot.send(im)
        else:
            await bot.send([im, MessageSegment.image(card_img)])
    else:
        await bot.send(im)


@sv_gacha_log.on_fullmatch(("抽卡记录", "查看抽卡记录", "gacha", "ckjl"))
async def send_gacha_log_card_info(bot: Bot, ev: Event):
    await bot.logger.info("[鸣潮]开始执行 抽卡记录")
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        return await bot.send(ERROR_CODE[WAVES_CODE_102])

    im = await draw_card(uid, ev)
    await bot.send(im)


@sv_gacha_help_log.on_fullmatch("抽卡帮助")
async def send_gacha_log_help(bot: Bot, ev: Event):
    im = await draw_card_help()
    await bot.send(im)


@sv_import_gacha_log.on_file("json")
async def get_gacha_log_by_file(bot: Bot, ev: Event):
    # 没有uid 就别导了吧
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        await bot.logger.info(f"[JSON导入抽卡] 用户 {ev.user_id} 未绑定UID，忽略此次导入")
        return
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        await bot.logger.info(f"[JSON导入抽卡] 用户 {ev.user_id} (UID:{uid}) 未登录或Cookie失效，忽略此次导入")
        return

    # 检查冷却
    remaining_time = can_import_gacha(ev.user_id, uid)
    if remaining_time > 0:
        return

    if ev.file and ev.file_type:
        # 误触就不说话了
        # await bot.send("正在尝试导入抽卡记录中，请耐心等待……")
        im = await import_gachalogs(ev, ev.file, ev.file_type, uid)

        # 设置冷却缓存
        set_gacha_import_cache(ev.user_id, uid)

        return await bot.send(im)
    else:
        return await bot.send("导入抽卡记录异常...")


@sv_export_json_gacha_log.on_fullmatch(("导出抽卡记录"))
async def send_export_gacha_info(bot: Bot, ev: Event):
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        return await bot.send(ERROR_CODE[WAVES_CODE_102])

    # await bot.send("🔜即将为你导出XutheringWavesUID抽卡记录文件，请耐心等待...")
    export = await export_gachalogs(uid)
    if export["retcode"] == "ok":
        file_name = export["name"]
        file_path = export["url"]
        await bot.send(MessageSegment.file(file_path, file_name))
        await bot.send("✅导出抽卡记录成功！")
    else:
        await bot.send("导出抽卡记录失败...")


@sv_delete_gacha_log.on_command("删除抽卡记录", block=True)
async def delete_gacha_history(bot: Bot, ev: Event):
    uid = ev.text.strip()
    if not uid.isdigit() or len(uid) != 9:
        return await bot.send(f"请附带特征码，例如【{PREFIX}删除抽卡记录123456789】")

    is_self, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if (not ck or not is_self) and not ev.user_pm == 0:
        return await bot.send(f"UID{uid}未登录或Cookie失效，不允许删除抽卡记录")

    player_dir = PLAYER_PATH / uid
    gacha_log_file = player_dir / "gacha_logs.json"
    if not gacha_log_file.exists():
        return await bot.send(f"UID{uid}暂无抽卡记录文件")

    GACHA_BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    backup_dir = GACHA_BACKUP_PATH / uid
    backup_dir.mkdir(parents=True, exist_ok=True)

    dst_file = backup_dir / "gacha_logs.json"
    if dst_file.exists():
        dst_file = backup_dir / f"gacha_logs_{datetime.now().strftime('%Y-%m-%d.%H%M%S')}.json"

    try:
        # 备份抽卡记录到 backup/gacha_backup/{uid}/ 目录
        shutil.move(str(gacha_log_file), dst_file)
    except Exception as e:
        return await bot.send(f"移动抽卡记录失败：{e}")

    await bot.send(f"UID{uid}抽卡记录已删除！")


@sv_delete_import_gacha_log.on_command(("删除抽卡导入", "删除导入记录", "删除导入抽卡"), block=True)
async def delete_import_gacha_files(bot: Bot, ev: Event):
    delete_count = 0
    for player_dir in PLAYER_PATH.iterdir():
        if not player_dir.is_dir():
            continue
        for file_path in player_dir.glob("import_gacha_logs_*.json"):
            try:
                file_path.unlink()
                delete_count += 1
            except Exception as e:
                await bot.logger.warning(f"删除导入记录失败 {file_path}: {e}")

    await bot.send(f"删除导入记录{delete_count}个")


@sv_gacha_rank.on_command(
    ("抽卡排行", "抽卡排名", "群抽卡排行", "群抽卡排名", "ckph", "ckpm"),
    block=True,
)
async def send_gacha_rank_info(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用本功能！")

    await bot.logger.info("[鸣潮]开始执行 抽卡排行")
    im = await draw_gacha_rank_card(bot, ev)
    await bot.send(im)
