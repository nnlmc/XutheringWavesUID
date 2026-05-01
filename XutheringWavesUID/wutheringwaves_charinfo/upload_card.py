import os
import ssl
import time
import shutil
import asyncio
from pathlib import Path
from typing import List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from PIL import Image

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.download_resource.download_file import download

from ..utils.image import compress_to_webp
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.name_convert import easy_id_to_name
from ..utils.resource.RESOURCE_PATH import CUSTOM_CARD_PATH
from .card_utils import (
    CUSTOM_PATH_MAP,
    CUSTOM_PATH_NAME_MAP,
    delete_orb_cache,
    find_duplicates_for_new_images,
    find_hash_in_all_types,
    get_char_id_and_name,
    get_hash_id,
    get_image,
    get_orb_dir_for_char,
    ORB_BLOCK_THRESHOLD,
    update_orb_cache,
)


def check_image_dimensions(temp_path: Path, target_type: str, index: int) -> Optional[str]:
    try:
        with Image.open(temp_path) as img:
            w, h = img.size
            if target_type in ["card", "stamina"] and w > h:
                return f"第{index}张图片尺寸错误，面板图和体力图需要竖版图片（宽 ≤ 高），可能想上传：背景图"
            if target_type == "bg" and h > w:
                return f"第{index}张图片尺寸错误，背景图需要横版图片（高 ≤ 宽），可能想上传：面板图"
    except Exception as e:
        logger.warning(f"[鸣潮] 检查图片尺寸失败: {e}")
    return None


def collect_blocked_duplicates(
    temp_dir: Path, new_images: List[Path]
) -> Tuple[List[str], Set[Path]]:
    dup_map = find_duplicates_for_new_images(temp_dir, new_images)
    block_msgs: List[str] = []
    blocked_paths: Set[Path] = set()
    for index, new_path in enumerate(new_images, start=1):
        dup_list = dup_map.get(new_path)
        if not dup_list:
            continue
        dup_list = sorted(dup_list, key=lambda x: -x[1])
        top_path, top_sim = dup_list[0]
        top_id = get_hash_id(top_path.name)
        if top_sim >= ORB_BLOCK_THRESHOLD:
            block_msgs.append(f"第{index}张和已有id {top_id} 重复")
            blocked_paths.add(new_path)
    return block_msgs, blocked_paths


async def upload_custom_card(
    bot: Bot,
    ev: Event,
    char: str,
    target_type: str = "card",
    is_force: bool = False,
):
    at_sender = True if ev.group_id else False
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    upload_images = await get_image(ev)
    if not upload_images:
        msg = f"[鸣潮] 上传角色{type_label}图失败\n请同时发送图片及其命令\n支持上传的图片类型：面板图/体力图/背景图"
        return await bot.send(
            (" " if at_sender else "") + msg,
            at_sender,
        )

    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    success = True
    new_images = []
    size_check_failed = []
    for index, upload_image in enumerate(upload_images, start=1):
        name = f"{char_id}_{int(time.time() * 1000)}.jpg"
        temp_path = temp_dir / name

        if not temp_path.exists():
            try:
                if httpx.__version__ >= "0.28.0":
                    ssl_context = ssl.create_default_context()
                    # ssl_context.set_ciphers("AES128-GCM-SHA256")
                    ssl_context.set_ciphers("DEFAULT")
                    sess = httpx.AsyncClient(verify=ssl_context)
                else:
                    sess = httpx.AsyncClient()
            except Exception as e:
                logger.exception(f"{httpx.__version__} - {e}")
                sess = None
            code = await download(upload_image, temp_dir, name, tag="[鸣潮]", sess=sess)
            if not isinstance(code, int) or code != 200:
                # 成功
                success = False
                break

            err_msg = check_image_dimensions(temp_path, target_type, index)
            if err_msg:
                size_check_failed.append(err_msg)
                temp_path.unlink()
                continue

            new_images.append(temp_path)

    if size_check_failed:
        if not new_images:
            return await bot.send(
                (" " if at_sender else "") + "[鸣潮] 上传失败！\n" + "\n".join(size_check_failed),
                at_sender,
            )

    if success:
        msg = f"[鸣潮]【{char}】上传{type_label}图成功！"
        if new_images:
            block_msgs, blocked_paths = collect_blocked_duplicates(temp_dir, new_images)

            if block_msgs and not is_force:
                for img_path in blocked_paths:
                    try:
                        img_path.unlink()
                    except Exception:
                        pass
                    delete_orb_cache(img_path)
                block_text = "；".join(block_msgs)
                msg = f"{msg} 疑似重复: {block_text}，请使用强制上传继续上传"

            success_ids = []
            for img_path in new_images:
                if img_path not in blocked_paths:
                    update_orb_cache(img_path)
                    success_ids.append(get_hash_id(img_path.name))

            if success_ids:
                msg = f"{msg} 上传成功id: {', '.join(success_ids)}"

        await bot.send((" " if at_sender else "") + msg, at_sender)
        return
    else:
        msg = f"[鸣潮]【{char}】上传{type_label}图失败！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)


async def get_custom_card_list(bot: Bot, ev: Event, char: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    if not temp_dir.exists():
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    # 获取角色文件夹图片数量, 只要图片
    files = [f for f in temp_dir.iterdir() if f.is_file() and f.suffix in [".jpg", ".png", ".jpeg", ".webp"]]

    imgs = []
    for _, f in enumerate(files, start=1):
        img = await convert_img(f)
        hash_id = get_hash_id(f.name)
        imgs.append(f"{char}{type_label}图id : {hash_id}")
        imgs.append(img)

    card_num = WutheringWavesConfig.get_config("CharCardNum").data
    card_num = max(5, min(card_num, 30))

    for i in range(0, len(imgs), card_num * 2):
        send = imgs[i : i + card_num * 2]
        await bot.send(send)
        await asyncio.sleep(0.5)


async def delete_custom_card(bot: Bot, ev: Event, char: str, hash_id: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    if not temp_dir.exists():
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    files_map = {
        get_hash_id(f.name): f
        for f in temp_dir.iterdir()
        if f.is_file() and f.suffix in [".jpg", ".png", ".jpeg", ".webp"]
    }

    # 支持逗号分隔的多个ID
    hash_ids = [id.strip() for id in hash_id.replace("，", ",").split(",") if id.strip()]

    if not hash_ids:
        msg = f"[鸣潮] 未提供有效的{type_label}图ID！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    not_found_ids = []
    found_in_other = []
    deleted_ids = []

    for single_hash_id in hash_ids:
        if single_hash_id not in files_map:
            not_found_ids.append(single_hash_id)
        else:
            try:
                target_file = files_map[single_hash_id]
                target_file.unlink()
                delete_orb_cache(target_file)
                deleted_ids.append(single_hash_id)
            except Exception as e:
                logger.exception(f"删除文件失败: {target_file} - {e}")
                not_found_ids.append(single_hash_id)

    # 构建返回消息
    msg_parts = []
    if deleted_ids:
        msg_parts.append(f"成功删除id: {', '.join(deleted_ids)}")
    else:
        if not_found_ids:
            for single_hash_id in not_found_ids:
                matches = find_hash_in_all_types(single_hash_id)
                if matches:
                    for t, other_char_id, _ in matches:
                        char_name = easy_id_to_name(other_char_id, other_char_id)
                        type_name = CUSTOM_PATH_NAME_MAP.get(t, t)
                        found_in_other.append(
                            f"{single_hash_id} 在{char_name}的{type_name}图中找到"
                        )
                else:
                    msg_parts.append(f"未找到id: {single_hash_id}")
        if found_in_other:
            msg_parts.append("；".join(found_in_other))

    msg = f"[鸣潮] 角色【{char}】{type_label}图 " + "；".join(msg_parts)
    return await bot.send((" " if at_sender else "") + msg, at_sender)


async def delete_all_custom_card(bot: Bot, ev: Event, char: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    if not temp_dir.exists():
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    files_map = {
        get_hash_id(f.name): f
        for f in temp_dir.iterdir()
        if f.is_file() and f.suffix in [".jpg", ".png", ".jpeg", ".webp"]
    }

    if len(files_map) == 0:
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    # 删除文件夹包括里面的内容
    try:
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir)
        orb_dir = get_orb_dir_for_char(target_type, char_id)
        if orb_dir.exists() and orb_dir.is_dir():
            shutil.rmtree(orb_dir)
    except Exception:
        pass

    msg = f"[鸣潮] 删除角色【{char}】的所有{type_label}图成功！"
    return await bot.send((" " if at_sender else "") + msg, at_sender)


async def compress_all_custom_card(bot: Bot, ev: Event):
    count = 0
    rename_count = 0
    use_cores = max(os.cpu_count() - 2 if os.cpu_count() else 0, 1)  # 避免2c服务器卡死
    await bot.send(f"[鸣潮] 开始压缩面板、体力、背景图, 使用 {use_cores} 核心")

    # 重命名含中文的文件名为 char_id 格式，避免 opencv 不兼容中文路径
    for PATH in CUSTOM_PATH_MAP.values():
        for char_id_path in PATH.iterdir():
            if not char_id_path.is_dir():
                continue
            char_id = char_id_path.name
            for img_path in list(char_id_path.iterdir()):
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() not in [".jpg", ".png", ".jpeg", ".webp"]:
                    continue
                if img_path.stem.isascii():
                    continue
                base_ts = int(time.time() * 1000)
                new_name = f"{char_id}_{base_ts}{img_path.suffix}"
                new_path = char_id_path / new_name
                counter = 1
                while new_path.exists():
                    new_name = f"{char_id}_{base_ts + counter}{img_path.suffix}"
                    new_path = char_id_path / new_name
                    counter += 1
                try:
                    delete_orb_cache(img_path)
                    img_path.rename(new_path)
                    if new_path.suffix.lower() == ".webp":
                        update_orb_cache(new_path)
                    rename_count += 1
                except Exception as e:
                    logger.error(f"[鸣潮] 重命名失败 {img_path}: {e}")

    task_list = []
    for PATH in CUSTOM_PATH_MAP.values():
        for char_id_path in PATH.iterdir():
            if not char_id_path.is_dir():
                continue
            for img_path in char_id_path.iterdir():
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() in [".jpg", ".png", ".jpeg"]:
                    task_list.append((img_path, 80, True))

    with ThreadPoolExecutor(max_workers=use_cores) as executor:
        future_to_file = {executor.submit(compress_to_webp, *task): task for task in task_list}

        for future in as_completed(future_to_file):
            file_info = future_to_file[future]
            try:
                success, _ = future.result()
                if success:
                    count += 1
                    delete_orb_cache(file_info[0])
                    update_orb_cache(file_info[0].with_suffix(".webp"))

            except Exception as exc:
                logger.error(f"Error processing {file_info[0]}: {exc}")

    msgs = []
    if rename_count > 0:
        msgs.append(f"重命名【{rename_count}】张中文命名图片")
    if count > 0:
        msgs.append(f"压缩【{count}】张图")
    if msgs:
        return await bot.send(f"[鸣潮] {'，'.join(msgs)}成功！")
    else:
        return await bot.send("[鸣潮] 暂未找到需要压缩或重命名的资源！")
