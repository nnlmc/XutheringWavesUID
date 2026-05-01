"""FastAPI 路由入口 — 面板图编辑器。

路径前缀: /waves/panel-edit/
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional

from PIL import Image

from fastapi import Depends, File, HTTPException, Request, UploadFile
from gsuid_core.logger import logger
from gsuid_core.web_app import app
from starlette.responses import FileResponse, HTMLResponse, Response

from .auth import is_enabled, require_auth
from . import storage as st


_STATIC_DIR = Path(__file__).parent / "static"


def _try_update_orb_cache(p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo.card_utils import update_orb_cache
        update_orb_cache(p)
    except Exception as e:
        logger.debug(f"[鸣潮·面板编辑] 更新 ORB 缓存跳过: {e}")


def _try_delete_orb_cache(p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo.card_utils import delete_orb_cache
        delete_orb_cache(p)
    except Exception:
        pass


_DISABLED_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"/>
<title>面板图编辑器未启用</title>
<style>
  html,body{margin:0;height:100%;background:#07090d;color:#c7cdd9;
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;}
  body{display:flex;align-items:center;justify-content:center;}
  .card{max-width:520px;padding:32px 36px;background:#11161e;
    border:1px solid #1d2533;border-radius:8px;line-height:1.6;}
  h1{margin:0 0 6px 0;font-size:14px;letter-spacing:.04em;color:#eef1f6;}
  p{margin:8px 0;color:#8b95a7;font-size:13px;}
  code,pre{font-family:"JetBrains Mono","SF Mono",Consolas,monospace;
    color:#7aa3ff;background:#161c26;padding:2px 6px;border-radius:4px;}
  pre{display:block;padding:12px 14px;color:#c7cdd9;font-size:12px;
    border:1px solid #1d2533;overflow:auto;}
  .tag{display:inline-block;padding:2px 8px;border-radius:999px;
    background:rgba(248,113,113,.12);color:#f87171;font-size:11px;
    letter-spacing:.08em;text-transform:uppercase;
    border:1px solid rgba(248,113,113,.3);}
</style></head><body><div class="card">
  <span class="tag">DISABLED</span>
  <h1>鸣潮 · 面板/背景图编辑台 未启用</h1>
  <p>请在 <code>WutheringWavesConfig</code> 控制台中设置配置项，赋值非空密码以启用该工具：</p>
  <pre>WavesPanelEditPassword = &lt;你的密码&gt;</pre>
  <p>设置完成并重启 / 刷新配置后再次访问本页面，会通过 HTTP Basic Auth 提示输入凭据（用户名固定为 <code>admin</code>）。</p>
</div></body></html>"""


# ------------------------- 前端 -------------------------


@app.get("/waves/panel-edit/")
async def panel_edit_index(request: Request):
    """无需鉴权的入口。

    - 未配置密码时返回提示页, 引导用户去控制台设置 WavesPanelEditPassword。
    - 配置后, 让浏览器走 Basic Auth (二次请求会带 Authorization 进入正常 SPA)。
    """
    if not is_enabled():
        return HTMLResponse(_DISABLED_HTML, status_code=200)
    require_auth(request)  # 触发 401 让浏览器弹出登录框
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Panel editor static files missing.</h1>", status_code=500)
    return FileResponse(index, media_type="text/html; charset=utf-8")


@app.get("/waves/panel-edit/static/{name:path}")
async def panel_edit_static(name: str, _: None = Depends(require_auth)):
    # 只允许扁平文件名, 不接受路径分隔符 / .. 等。
    if not st.is_safe_name(name):
        raise HTTPException(404, "Not found")
    target = st.safe_join(_STATIC_DIR, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "Not found")
    media_type = None
    if target.suffix == ".js":
        media_type = "application/javascript; charset=utf-8"
    elif target.suffix == ".css":
        media_type = "text/css; charset=utf-8"
    return FileResponse(target, media_type=media_type)


# ------------------------- 列表 -------------------------


@app.get("/waves/panel-edit/api/folders")
async def api_folders(type: str, _: None = Depends(require_auth)):
    if not st.is_valid_type(type):
        raise HTTPException(400, "invalid type")
    folders = st.list_folders(type)
    return {"type": type, "folders": folders}


@app.get("/waves/panel-edit/api/images")
async def api_images(type: str, char_id: str, _: None = Depends(require_auth)):
    folder = st.safe_char_dir(type, char_id)
    if folder is None:
        raise HTTPException(400, "invalid type or char_id")
    if not folder.exists():
        return {"type": type, "char_id": char_id, "images": []}
    from ...utils.name_convert import easy_id_to_name
    images = st.list_images(type, char_id)
    return {
        "type": type,
        "char_id": char_id,
        "char_name": easy_id_to_name(char_id, char_id),
        "images": images,
    }


# ------------------------- 缩略图 / 原图 -------------------------


@app.get("/waves/panel-edit/api/thumb")
async def api_thumb(
    type: str,
    char_id: str,
    name: str,
    size: int = 360,
    _: None = Depends(require_auth),
):
    if size <= 0 or size > 800:
        size = 360
    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    cache = st.get_or_make_thumb(target, size)
    if cache is None:
        return FileResponse(target)
    return FileResponse(cache, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


@app.get("/waves/panel-edit/api/image")
async def api_image(
    type: str,
    char_id: str,
    name: str,
    _: None = Depends(require_auth),
):
    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    return FileResponse(target)


# ------------------------- 临时上传 / 裁剪 -------------------------


async def _stage_upload(file: UploadFile) -> Optional[dict]:
    """读 + 校验 + 落盘一份 tmp; 失败返回 None。"""
    raw = await file.read()
    if not raw:
        return None
    try:
        with Image.open(BytesIO(raw)) as im:
            im.load()
            w, h = im.size
    except Exception:
        return None
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in st.IMAGE_EXTS:
        suffix = ".jpg"
    token = st.new_tmp_token()
    st.write_tmp_image(token, suffix, raw)
    st.write_tmp_image(f"{token}.orig", suffix, raw)
    return {
        "token": token, "name": filename, "suffix": suffix,
        "width": w, "height": h, "size": len(raw),
    }


@app.post("/waves/panel-edit/api/tmp/upload")
async def api_tmp_upload(
    file: UploadFile = File(...),
    _: None = Depends(require_auth),
):
    """上传单文件到 tmp。返回 token, 后续操作 (裁剪/确认) 用它。"""
    st.gc_tmp()
    item = await _stage_upload(file)
    if not item:
        raise HTTPException(400, "not an image or empty file")
    return item


@app.post("/waves/panel-edit/api/tmp/upload-batch")
async def api_tmp_upload_batch(
    files: List[UploadFile] = File(...),
    _: None = Depends(require_auth),
):
    """批量上传到 tmp, 返回 token 列表。"""
    st.gc_tmp()
    out = []
    for f in files:
        item = await _stage_upload(f)
        if item:
            out.append(item)
    if not out:
        raise HTTPException(400, "no valid images")
    return {"items": out}


@app.get("/waves/panel-edit/api/tmp/image")
async def api_tmp_image(token: str, _: None = Depends(require_auth)):
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, _orig = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    return FileResponse(current, headers={"Cache-Control": "no-store"})


@app.post("/waves/panel-edit/api/tmp/crop")
async def api_tmp_crop(
    payload: dict,
    _: None = Depends(require_auth),
):
    """对 tmp 图执行裁剪。
    payload:
      token: str
      x, y, w, h: float (源图像素, 允许越界后会 clamp)
    保留原图副本; 当前文件被裁剪结果覆盖。
    """
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    try:
        x = int(round(float(payload["x"])))
        y = int(round(float(payload["y"])))
        w = int(round(float(payload["w"])))
        h = int(round(float(payload["h"])))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "x/y/w/h required and numeric")
    if w <= 0 or h <= 0:
        raise HTTPException(400, "invalid crop size")

    current, original = st.find_tmp_files(token)
    if current is None or original is None:
        raise HTTPException(404, "tmp not found")

    with Image.open(original) as im:
        im.load()
        ow, oh = im.size
        x = max(0, min(x, ow - 1))
        y = max(0, min(y, oh - 1))
        w = max(1, min(w, ow - x))
        h = max(1, min(h, oh - y))
        cropped = im.crop((x, y, x + w, y + h))

    suffix = current.suffix
    out = BytesIO()
    if suffix.lower() in (".jpg", ".jpeg"):
        cropped.convert("RGB").save(out, "JPEG", quality=92)
    elif suffix.lower() == ".webp":
        cropped.save(out, "WEBP", quality=90)
    else:
        cropped.save(out, "PNG")
    current.write_bytes(out.getvalue())

    with Image.open(current) as im:
        nw, nh = im.size
    return {"token": token, "width": nw, "height": nh, "size": current.stat().st_size}


@app.post("/waves/panel-edit/api/tmp/restore")
async def api_tmp_restore(payload: dict, _: None = Depends(require_auth)):
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, original = st.find_tmp_files(token)
    if current is None or original is None:
        raise HTTPException(404, "tmp not found")
    current.write_bytes(original.read_bytes())
    with Image.open(current) as im:
        w, h = im.size
    return {"token": token, "width": w, "height": h, "size": current.stat().st_size}


@app.post("/waves/panel-edit/api/tmp/discard")
async def api_tmp_discard(payload: dict, _: None = Depends(require_auth)):
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    st.cleanup_tmp(token)
    return {"ok": True}


# ------------------------- 确认入库 / 编辑现有 -------------------------


@app.post("/waves/panel-edit/api/confirm")
async def api_confirm(payload: dict, _: None = Depends(require_auth)):
    """确认 tmp 文件入库。
    payload: { token, type, char_id }
    """
    token = payload.get("token")
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    if not st.is_valid_type(target_type or ""):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")

    current, original = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")

    final = st.relocate_to_target(target_type, char_id, current, suffix_hint=current.suffix)
    _try_update_orb_cache(final)
    if original is not None:
        try:
            original.unlink()
        except OSError:
            pass
    return {"ok": True, "name": final.name, "hash_id": st.hash_id_for(final.name)}


@app.post("/waves/panel-edit/api/replace-existing")
async def api_replace_existing(payload: dict, _: None = Depends(require_auth)):
    """用裁剪后的 tmp 内容覆盖一张已有图。删除旧图的 ORB 缓存, 重新生成。"""
    token = payload.get("token")
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    name = payload.get("name")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    if not st.is_valid_type(target_type or ""):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")
    if not st.is_safe_name(name):
        raise HTTPException(400, "invalid name")

    current, _ = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    target = st.safe_target_image(target_type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "target image not found")

    _try_delete_orb_cache(target)
    target.write_bytes(current.read_bytes())
    _try_update_orb_cache(target)

    st.cleanup_tmp(token)
    return {"ok": True, "name": target.name, "hash_id": st.hash_id_for(target.name)}


# ------------------------- 删除 (单/全部) -------------------------


@app.post("/waves/panel-edit/api/delete")
async def api_delete(payload: dict, _: None = Depends(require_auth)):
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    name = payload.get("name")
    target = st.safe_target_image(target_type or "", char_id or "", name or "")
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    _try_delete_orb_cache(target)
    target.unlink()
    return {"ok": True}


# ------------------------- 预览 -------------------------


@app.get("/waves/panel-edit/api/preview")
async def api_preview(
    type: str,
    char_id: str,
    name: str,
    renderer: str = "html",
    _: None = Depends(require_auth),
):
    """type=card -> 角色面板预览; type=bg/stamina -> MR 预览。
    name = 已入库图片的文件名。
    """
    from .preview import render_panel_preview, render_mr_preview

    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")

    try:
        if type == "card":
            data = await render_panel_preview(char_id, target)
        else:
            use_html = renderer != "pil"
            role_kind = "bg" if type == "bg" else "stamina"
            data = await render_mr_preview(char_id, target, use_html=use_html, role_kind=role_kind)
    except Exception as e:
        logger.exception(f"[鸣潮·面板编辑] 预览渲染失败: {e}")
        raise HTTPException(500, f"render failed: {e}")
    if not data:
        raise HTTPException(500, "preview empty")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/waves/panel-edit/api/preview-tmp")
async def api_preview_tmp(
    type: str,
    char_id: str,
    token: str,
    renderer: str = "html",
    _: None = Depends(require_auth),
):
    """裁剪/上传过程中, 用 tmp 图渲染预览。"""
    from .preview import render_panel_preview, render_mr_preview

    if not st.is_valid_type(type):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, _orig = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    try:
        if type == "card":
            data = await render_panel_preview(char_id, current)
        else:
            use_html = renderer != "pil"
            role_kind = "bg" if type == "bg" else "stamina"
            data = await render_mr_preview(char_id, current, use_html=use_html, role_kind=role_kind)
    except Exception as e:
        logger.exception(f"[鸣潮·面板编辑] tmp 预览渲染失败: {e}")
        raise HTTPException(500, f"render failed: {e}")
    if not data:
        raise HTTPException(500, "preview empty")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------- 元数据: 类型 / 角色名 -------------------------


@app.get("/waves/panel-edit/api/meta")
async def api_meta(_: None = Depends(require_auth)):
    """前端启动时拉取: 类型列表 / 各类型路径标签 / id->name 字典。"""
    from ...utils.name_convert import ensure_data_loaded, id2name
    try:
        ensure_data_loaded()
    except Exception:
        pass
    return {
        "types": [
            {"key": "card", "label": "面板图 (custom_role_pile)", "preview": "panel"},
            {"key": "bg", "label": "MR 背景图 (custom_mr_bg)", "preview": "mr"},
            {"key": "stamina", "label": "MR 立绘 (custom_mr_role_pile)", "preview": "mr"},
        ],
        "id2name": dict(id2name),
    }
