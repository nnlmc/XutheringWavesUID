"""每用户级面板图绑定: PLAYER_PATH/<uid>/panel_card_pref.json, 角色名 → hash。

只放写读, 不做角色名校验也不查 hash 是否存在 — 那是调用方的事。
故意不进库: 这是用户在他自己存档目录下的偏好文件, 跟随 uid 备份/迁移最自然。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from gsuid_core.logger import logger

from .resource.RESOURCE_PATH import PLAYER_PATH
from .resource.constant import ID_FULL_CHAR_NAME


_FILENAME = "panel_card_pref.json"


def pair_pin_key(char_id: object, fallback: str) -> str:
    """主角变体 pair 共享键: 1501/1502 同走"漂泊者·衍射"; 非主角回退 fallback (角色名)。"""
    return ID_FULL_CHAR_NAME.get(str(char_id) if char_id is not None else "", fallback)


def _path(uid: str) -> Path:
    return PLAYER_PATH / str(uid) / _FILENAME


def load(uid: str) -> Dict[str, str]:
    p = _path(uid)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[鸣潮·面板图绑定] 读取失败 {p}: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _save(uid: str, data: Dict[str, str]) -> None:
    p = _path(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def set_pin(uid: str, char_name: str, hash_id: str) -> None:
    data = load(uid)
    data[char_name] = hash_id
    _save(uid, data)


def clear_pin(uid: str, char_name: str) -> bool:
    data = load(uid)
    if char_name not in data:
        return False
    data.pop(char_name)
    _save(uid, data)
    return True


def get_pin(uid: str, char_name: str) -> Optional[str]:
    return load(uid).get(char_name)
