"""抽卡记录网页查看：FastAPI 路由 + 链接生成。

启用方式: 配置 WavesGachaWebPage=True 后, 用户发送
[抽卡页面/抽卡网页/网页抽卡记录/抽卡记录网页] 即可获得 10 分钟内有效的链接。
"""

from __future__ import annotations

import json
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import aiofiles
import httpx
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.web_app import app

from ..utils.api.model import AccountBaseInfo
from ..utils.cache import TimedCache
from ..utils.resource.RESOURCE_PATH import (
    AVATAR_PATH,
    MAIN_PATH,
    PLAYER_PATH,
    WEAPON_PATH,
)
from ..utils.resource.constant import NORMAL_LIST
from ..utils.waves_api import waves_api
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from .get_gachalogs import gacha_type_meta_data

GACHA_WEB_TTL = 600  # 10 分钟

_token_cache = TimedCache(
    timeout=GACHA_WEB_TTL,
    maxsize=2000,
    persist_path=MAIN_PATH / "url_cache.db",
)

_TEMPLATE_PATH = Path(__file__).parent / "page.html"


def _is_feature_enabled() -> bool:
    return bool(WutheringWavesConfig.get_config("WavesGachaWebPage").data)


def feature_disabled_msg() -> str:
    return "该功能未开启，请联系主人开启该功能"


async def _build_account_info(uid: str, ev: Event) -> Dict:
    """尽力获取账号基础信息，失败回退到仅 uid。"""
    info: Dict = {"uid": uid}
    # QQ 头像 URL（仅 onebot + 纯数字 user_id）；用 // 协议相对，避免 mixed-content
    if ev.bot_id == "onebot" and str(ev.user_id).isdigit():
        info["qq_avatar"] = f"//q1.qlogo.cn/g?b=qq&nk={ev.user_id}&s=640"
    if waves_api.is_net(uid):
        info["name"] = f"漂泊者·{uid}"
        info["is_net"] = True
        return info
    info["is_net"] = False
    try:
        _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
        if not ck:
            return info
        base = await waves_api.get_base_info(uid, ck)
        if not base.success or not base.data:
            return info
        acc = AccountBaseInfo.model_validate(base.data)
        info["name"] = acc.name
        info["level"] = acc.level
        info["worldLevel"] = acc.worldLevel
        info["activeDays"] = acc.activeDays
        info["roleNum"] = acc.roleNum
    except Exception as e:
        logger.debug(f"[鸣潮·抽卡网页] 获取账号信息失败: {e}")
    return info


async def make_gacha_web_url(uid: str, ev: Event) -> Tuple[Optional[str], str]:
    """生成 10 分钟内有效的查看链接。返回 (url, message)。"""
    if not _is_feature_enabled():
        return None, feature_disabled_msg()

    gacha_path = PLAYER_PATH / str(uid) / "gacha_logs.json"
    if not gacha_path.exists():
        return None, f"[鸣潮] 你还没有抽卡记录噢!\n 请发送 {PREFIX}导入抽卡链接 后重试!"

    base = await _build_account_info(uid, ev)
    token = secrets.token_urlsafe(16)
    _token_cache.set(token, {"uid": uid, "user_id": ev.user_id, "bot_id": ev.bot_id, "base": base})

    # 延迟导入避免插件加载顺序导致的循环依赖
    from ..wutheringwaves_login.login import get_url
    url, _is_local = await get_url()
    return f"{url}/waves/gacha/{token}", "ok"


# ----------------------------- 数据计算 -----------------------------


def _build_pool_view(name: str, logs: List[Dict]) -> Dict:
    """把单池抽卡日志整理成前端使用的结构。

    分组: 把每两个 5 星之间的所有抽卡视为"一个 5 星周期",
    周期内按抽到次数最多的 4 星排序后取 top4。
    输出按 5 星倒序（最近的在前）。
    """
    total = len(logs)
    asc = list(reversed(logs))  # 老到新

    five_stars: List[Dict] = []
    period_4stars: Dict[int, Dict[str, Dict]] = {}
    pity = 0
    fs_index = 0
    cur_period: Dict[str, Dict] = {}

    five_pos: List[int] = []  # 5 星出现位置（按从老到新计算）

    for log in asc:
        pity += 1
        ql = log.get("qualityLevel")
        if ql == 4:
            key = log.get("name", "?")
            cur_period.setdefault(
                key,
                {
                    "name": key,
                    "resourceId": log.get("resourceId"),
                    "resourceType": log.get("resourceType"),
                    "count": 0,
                },
            )
            cur_period[key]["count"] += 1
        elif ql == 5:
            five_pos.append(pity)
            is_up = log.get("name") not in NORMAL_LIST
            five_stars.append(
                {
                    "name": log.get("name"),
                    "resourceId": log.get("resourceId"),
                    "resourceType": log.get("resourceType"),
                    "time": log.get("time"),
                    "pity": pity,
                    "is_up": is_up,
                }
            )
            period_4stars[fs_index] = cur_period
            fs_index += 1
            cur_period = {}
            pity = 0

    remain_since_last = pity  # 末尾未出 5 星的累积
    # 打包 4 星（top 4 by count）
    # 注: 库洛接口 2025-11 之前未区分 4★, 旧记录全部 qualityLevel=3。
    # 周期内累计 ≥10 抽却 0 个 4★, 视为旧 API 的占位周期, 前端展示提示。
    fives_with_4 = []
    for i, fs in enumerate(five_stars):
        items = list(period_4stars.get(i, {}).values())
        items.sort(key=lambda x: -x["count"])
        fs2 = dict(fs)
        fs2["top_4stars"] = items[:4]
        fs2["is_stub"] = (len(items) == 0 and fs.get("pity", 0) >= 10)
        fives_with_4.append(fs2)
    fives_with_4.reverse()  # 新到老

    avg_5 = (sum(five_pos) / len(five_pos)) if five_pos else 0
    up_count = sum(1 for f in fives_with_4 if f["is_up"])
    avg_up = (sum(five_pos) / up_count) if up_count else 0

    time_range = ""
    if logs:
        time_range = f"{logs[-1]['time']} ~ {logs[0]['time']}"

    return {
        "name": name,
        "total": total,
        "five_count": len(fives_with_4),
        "up_count": up_count,
        "avg_5": round(avg_5, 2),
        "avg_up": round(avg_up, 2),
        "remain": remain_since_last,
        "time_range": time_range,
        "five_stars": fives_with_4,
    }


async def _load_gacha_data(uid: str) -> Dict:
    path = PLAYER_PATH / str(uid) / "gacha_logs.json"
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


# ----------------------------- 路由 -----------------------------


def _check_token(token: str) -> Optional[Dict]:
    state = _token_cache.get(token)
    if not isinstance(state, dict):
        return None
    return state


_NOT_FOUND_HTML = """<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8><title>页面已过期</title>
<style>html,body{height:100%;margin:0;background:#0a0d12;color:#dfe4ee;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;}
.box{padding:32px 36px;border:1px solid #1f2733;border-radius:14px;background:#11161e;max-width:420px;text-align:center;}
h1{font-size:18px;margin:0 0 8px;color:#f0c463}
p{font-size:13px;color:#8b95a7;line-height:1.7;margin:6px 0}</style>
<div class=box><h1>页面已过期或不存在</h1>
<p>抽卡记录网页仅在 10 分钟内有效。</p>
<p>请重新发送 <code>抽卡页面</code> 获取新链接。</p></div></html>"""


@app.get("/waves/gacha/{token}")
async def gacha_web_index(token: str):
    if not _is_feature_enabled():
        return HTMLResponse(_NOT_FOUND_HTML, status_code=404)
    state = _check_token(token)
    if not state:
        return HTMLResponse(_NOT_FOUND_HTML, status_code=404)
    if not _TEMPLATE_PATH.exists():
        return HTMLResponse("<h1>page template missing</h1>", status_code=500)
    return FileResponse(_TEMPLATE_PATH, media_type="text/html; charset=utf-8")


@app.get("/waves/gacha/{token}/data")
async def gacha_web_data(token: str):
    if not _is_feature_enabled():
        return JSONResponse({"error": "disabled"}, status_code=404)
    state = _check_token(token)
    if not state:
        return JSONResponse({"error": "expired"}, status_code=404)

    uid = state["uid"]
    base = state.get("base", {"uid": uid})

    try:
        raw = await _load_gacha_data(uid)
    except Exception as e:
        logger.warning(f"[鸣潮·抽卡网页] 读取数据失败 uid={uid}: {e}")
        return JSONResponse({"error": "load_failed"}, status_code=500)

    data = raw.get("data", {})
    pools = []
    for name in gacha_type_meta_data.keys():
        logs = data.get(name, [])
        pools.append(_build_pool_view(name, logs))

    return JSONResponse(
        {
            "base": base,
            "data_time": raw.get("data_time", ""),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pools": pools,
        }
    )


def _safe_resource_id(rid: str) -> bool:
    return rid.isdigit() and len(rid) <= 10


@app.get("/waves/gacha/{token}/avatar/{rid}.png")
async def gacha_web_avatar(token: str, rid: str):
    if not _check_token(token) or not _safe_resource_id(rid):
        return JSONResponse({"error": "not_found"}, status_code=404)
    p = AVATAR_PATH / f"role_head_{rid}.png"
    if not p.exists():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/waves/gacha/{token}/weapon/{rid}.png")
async def gacha_web_weapon(token: str, rid: str):
    if not _check_token(token) or not _safe_resource_id(rid):
        return JSONResponse({"error": "not_found"}, status_code=404)
    p = WEAPON_PATH / f"weapon_{rid}.png"
    if not p.exists():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


def _random_char_avatar(seed: str) -> Optional[Path]:
    """挑一张本地角色头像作为兜底, 用 token 做种避免每次刷新都换。"""
    candidates = sorted(AVATAR_PATH.glob("role_head_*.png"))
    if not candidates:
        return None
    return candidates[hash(seed) % len(candidates)]


@app.get("/waves/gacha/{token}/userpic")
async def gacha_web_userpic(token: str):
    """用户头像代理: 优先 QQ 头像, 抓取失败/404 则回退到随机角色头像。
    走服务端代理避免 q1.qlogo.cn 的 CORS 限制, 同时保证 html2canvas 能正常导出。
    """
    state = _check_token(token)
    if not state:
        return JSONResponse({"error": "expired"}, status_code=404)

    qq_avatar = (state.get("base") or {}).get("qq_avatar") or ""
    if qq_avatar:
        full = "https:" + qq_avatar if qq_avatar.startswith("//") else qq_avatar
        try:
            async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
                r = await client.get(full, headers={"Referer": ""})
                # QQ 头像不存在时仍返回 200 + 默认占位; 没有可靠的"真 404"特征,
                # 仅当响应非 200 或 body 为空 时才走兜底。
                if r.status_code == 200 and r.content:
                    return Response(
                        r.content,
                        media_type=r.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "max-age=600"},
                    )
        except Exception as e:
            logger.debug(f"[鸣潮·抽卡网页] QQ头像抓取失败: {e}")

    fallback = _random_char_avatar(token)
    if fallback and fallback.exists():
        return FileResponse(fallback, media_type="image/png", headers={"Cache-Control": "max-age=600"})

    return JSONResponse({"error": "no_avatar"}, status_code=404)
