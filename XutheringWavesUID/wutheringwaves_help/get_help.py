import json
from typing import Dict
from pathlib import Path

from PIL import Image

from gsuid_core.help.model import PluginHelp
from gsuid_core.help.draw_new_plugin_help import get_new_help

from ..version import XutheringWavesUID_version
from ..utils.image import get_footer
from ..wutheringwaves_config import PREFIX, ShowConfig, WutheringWavesConfig

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "help.json"
ICON_PATH = Path(__file__).parent / "icon_path"
TEXT_PATH = Path(__file__).parent / "texture2d"

def get_help_data() -> Dict[str, PluginHelp]:
    # 读取文件内容
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        help_content = json.load(file)

    # 获取额外模块配置
    extra_modules = WutheringWavesConfig.get_config("HelpExtraModules").data

    sign_help_items = [
        {
            "name": "签到",
            "desc": "鸣潮签到",
            "eg": "签到",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "签到日历",
            "desc": "鸣潮签到日历",
            "eg": "签到日历",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "开启自动签到",
            "desc": "开启每天的自动签到功能",
            "eg": "开启自动签到",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
    ]

    sign_admin_help_items = [
        {
            "name": "全部重新签到",
            "desc": "全部重新签到所有人",
            "eg": "全部签到",
            "need_ck": False,
            "need_sk": False,
            "need_admin": True,
        },
        {
            "name": "订阅自动签到结果",
            "desc": "订阅自动签到结果",
            "eg": "订阅签到结果",
            "need_ck": False,
            "need_sk": False,
            "need_admin": True,
        },
    ]
    
    todayecho_help = {
        "name": "梭哈",
        "desc": "模拟梭哈声骸",
        "eg": "梭哈10次",
        "need_ck": False,
        "need_sk": False,
        "need_admin": False,
    }

    scoreecho_help_items = [
        {
            "name": "评分",
            "desc": "图片获得评分",
            "eg": "评分 卡提1c(生命)",
            "need_ck": False,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "国际服使用",
            "desc": "国际服子模块",
            "eg": "分析帮助",
            "need_ck": False,
            "need_sk": False,
            "need_admin": False,
        },
    ]
    
    roverreminder_help_items = [
        {
            "name": "推送邮箱",
            "desc": "设置体力推送的邮箱",
            "eg": "推送邮箱 邮箱名",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "开启推送",
            "desc": "开启体力推送",
            "eg": "开启/关闭体力推送",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "推送阈值",
            "desc": "设置体力推送阈值",
            "eg": "推送阈值 120",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
    ]

    # 根据配置追加额外帮助
    if "todayecho" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].append(todayecho_help)

    if "scoreecho" in extra_modules or "all" in extra_modules:
        if "信息查询" in help_content:
            help_content["信息查询"]["data"].extend(scoreecho_help_items)

    if "roversign" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].extend(sign_help_items)
        if "bot主人功能" in help_content:
            help_content["bot主人功能"]["data"].extend(sign_admin_help_items)
            
    if "roverreminder" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].extend(roverreminder_help_items)

    return help_content


plugin_help = get_help_data()


async def get_help(pm: int):
    # 从 ShowConfig 获取自定义配置，如果未配置或路径不存在则使用默认值
    banner_bg_config = ShowConfig.get_config("HelpBannerBgUpload").data
    help_bg_config = ShowConfig.get_config("HelpBgUpload").data
    plugin_icon_config = ShowConfig.get_config("HelpIconUpload").data
    column_config = ShowConfig.get_config("HelpColumn").data

    # 使用配置的路径（如果存在且配置了）或默认路径
    if banner_bg_config and Path(banner_bg_config).exists():
        banner_bg_path = Path(banner_bg_config)
    else:
        banner_bg_path = TEXT_PATH / "banner_bg.jpg"

    if help_bg_config and Path(help_bg_config).exists():
        help_bg_path = Path(help_bg_config)
    else:
        help_bg_path = TEXT_PATH / "bg.jpg"

    # plugin_icon: 插件主图标
    if plugin_icon_config and Path(plugin_icon_config).exists():
        plugin_icon_path = Path(plugin_icon_config)
    else:
        plugin_icon_path = ICON

    return await get_new_help(
        plugin_name="XutheringWavesUID",
        plugin_info={f"v{XutheringWavesUID_version}": ""},
        plugin_icon=Image.open(plugin_icon_path).convert("RGBA"),
        plugin_help=plugin_help,
        plugin_prefix=PREFIX,
        help_mode="dark",
        banner_bg=Image.open(banner_bg_path).convert("RGBA"),
        banner_sub_text="漂泊者，欢迎在这个时代醒来。",
        help_bg=Image.open(help_bg_path).convert("RGBA"),
        cag_bg=Image.open(TEXT_PATH / "cag_bg.png").convert("RGBA"),
        item_bg=Image.open(TEXT_PATH / "item.png").convert("RGBA"),
        icon_path=ICON_PATH,
        footer=get_footer(),
        enable_cache=False,
        column=column_config,
        pm=pm,
    )
