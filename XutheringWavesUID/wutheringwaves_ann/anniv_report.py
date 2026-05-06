"""周年庆/周年版/周年回顾 — 调用 xwservice /2nd_report 拉取三张图。"""
from __future__ import annotations
import io
import zipfile
from typing import List, Union

import httpx
from gsuid_core.logger import logger

XWSERVICE_BASE = "https://xwservice.loping151.site"


async def anniv_report(uid: str, waves_token: str) -> Union[str, List[bytes]]:
    """Call /2nd_report; return list of 3 PNG bytes (part1/2 vertical, part3 horizontal) or error msg."""
    if not waves_token:
        return "未配置 WavesToken（总排行 token），请先在配置中填写"
    url = XWSERVICE_BASE + "/2nd_report"
    headers = {
        "Authorization": f"Bearer {waves_token}",
        "Content-Type": "application/json",
    }
    body = {"uid": str(uid)}
    try:
        async with httpx.AsyncClient(timeout=600, verify=True) as c:
            r = await c.post(url, headers=headers, json=body)
    except Exception as e:
        logger.exception(f"[鸣潮] /2nd_report 网络错误: {e}")
        return f"网络错误: {e}"

    ct = r.headers.get("content-type", "")
    if r.status_code != 200 or "zip" not in ct:
        # Plain text error from server
        try:
            return f"[周年庆] 失败: HTTP {r.status_code} — {r.text[:300]}"
        except Exception:
            return f"[周年庆] 失败: HTTP {r.status_code}"

    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        out: List[bytes] = []
        for stem in ("part1", "part2", "part3"):
            # Accept either .jpg or .png in case of future format changes
            match = next((n for n in names if n.startswith(stem + ".")), None)
            if not match:
                return f"[周年庆] 服务返回缺失 {stem}"
            out.append(zf.read(match))
        return out
    except Exception as e:
        logger.exception(f"[鸣潮] 周年庆 ZIP 解析失败: {e}")
        return f"解析返回数据失败: {e}"
