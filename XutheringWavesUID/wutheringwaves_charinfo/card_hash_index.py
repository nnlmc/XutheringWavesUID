"""自定义图 (面板/背景/体力) hash → 路径 内存索引。

启动时全量扫 card / bg / stamina 三类目录, 建立两份索引:
  - (type, char_id) -> {hash_id: Path}
  - hash_id          -> [(type, char_id, Path), ...]

之后所有按 hash 查图走内存; 上传 / 前端编辑 / 删除处由调用方
同步调 add / remove / clear_dir / build 维护。

模块外不要自己拼 sha256, 一律 compute_hash(name)。
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gsuid_core.logger import logger

from ..utils.resource.RESOURCE_PATH import CUSTOM_DIRS as TYPE_BASES, IMAGE_EXTS as _IMAGE_EXTS

_lock = threading.RLock()
_by_dir: Dict[Tuple[str, str], Dict[str, Path]] = {}
_by_hash: Dict[str, List[Tuple[str, str, Path]]] = {}


def compute_hash(name: str) -> str:
    """整个插件唯一的 hash 算法实现。输入是文件名, 不是路径不是内容。"""
    return hashlib.sha256(name.encode()).hexdigest()[:8]


def detect_type(path: Path) -> Optional[str]:
    """用 path 反查它属于哪一类自定义图; 不在三类目录下返回 None。"""
    for t, base in TYPE_BASES.items():
        try:
            path.relative_to(base)
            return t
        except ValueError:
            continue
    return None


def build() -> None:
    """全量重建。启动时调一次, 外部改盘后可手动再调。"""
    with _lock:
        _by_dir.clear()
        _by_hash.clear()
        total = 0
        for t, base in TYPE_BASES.items():
            if not base.exists():
                continue
            for char_dir in base.iterdir():
                if not char_dir.is_dir():
                    continue
                char_id = char_dir.name
                bucket = _by_dir.setdefault((t, char_id), {})
                for p in char_dir.iterdir():
                    if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS:
                        continue
                    h = compute_hash(p.name)
                    bucket[h] = p
                    _by_hash.setdefault(h, []).append((t, char_id, p))
                    total += 1
    logger.info(f"[鸣潮] 自定义图 hash 索引已构建: {total} 张")


def add(t: str, char_id: str, path: Path) -> None:
    """新增一张图入索引。重复调用幂等。"""
    h = compute_hash(path.name)
    with _lock:
        _by_dir.setdefault((t, char_id), {})[h] = path
        bucket = _by_hash.setdefault(h, [])
        for entry in bucket:
            if entry[0] == t and entry[1] == char_id and entry[2] == path:
                return
        bucket.append((t, char_id, path))


def remove(t: str, char_id: str, path: Path) -> None:
    """删除一张图。path 不存在时静默 no-op。"""
    h = compute_hash(path.name)
    with _lock:
        bucket = _by_dir.get((t, char_id))
        if bucket and bucket.get(h) == path:
            del bucket[h]
            if not bucket:
                _by_dir.pop((t, char_id), None)
        entries = _by_hash.get(h)
        if not entries:
            return
        survivors = [
            e for e in entries
            if not (e[0] == t and e[1] == char_id and e[2] == path)
        ]
        if survivors:
            _by_hash[h] = survivors
        else:
            _by_hash.pop(h, None)


def clear_dir(t: str, char_id: str) -> None:
    """清掉某 (类型, 角色) 下所有条目。给 rmtree 整个目录后用。"""
    with _lock:
        bucket = _by_dir.pop((t, char_id), None)
        if not bucket:
            return
        for h, path in bucket.items():
            entries = _by_hash.get(h)
            if not entries:
                continue
            survivors = [
                e for e in entries
                if not (e[0] == t and e[1] == char_id and e[2] == path)
            ]
            if survivors:
                _by_hash[h] = survivors
            else:
                _by_hash.pop(h, None)


def find(hash_id: str) -> List[Tuple[str, str, Path]]:
    """跨三类目录按 hash 查; 主接口, O(1)。"""
    with _lock:
        return list(_by_hash.get(hash_id, ()))


def is_valid_hash(hash_id: str, types: Optional[Tuple[str, ...]] = None) -> bool:
    """格式校验 (8 位十六进制); types 提供时还要存在于指定类型子集 (card/bg/stamina)。"""
    if not isinstance(hash_id, str) or len(hash_id) != 8:
        return False
    if not all(c in "0123456789abcdef" for c in hash_id):
        return False
    if types is None:
        return True
    return any(t in types for t, _, _ in find(hash_id))


def lookup_in(t: str, char_id: str, hash_id: str) -> Optional[Path]:
    """限定 (类型, 角色) 范围内查 hash, 命中返回 Path。"""
    with _lock:
        bucket = _by_dir.get((t, char_id))
        return None if bucket is None else bucket.get(hash_id)


def lookup_in_pair(t: str, char_id: str, hash_id: str) -> Optional[Path]:
    """像 lookup_in, 但若 char_id 是主角变体 (SPECIAL_CHAR), 在同 pair 内查 (不跨 pair)。"""
    from ..utils.resource.constant import SPECIAL_CHAR
    for cid in SPECIAL_CHAR.get(str(char_id), [str(char_id)]):
        p = lookup_in(t, cid, hash_id)
        if p is not None:
            return p
    return None


def list_dir(t: str, char_id: str) -> Dict[str, Path]:
    """返回 (类型, 角色) 下 hash → Path 的快照副本。"""
    with _lock:
        bucket = _by_dir.get((t, char_id))
        return dict(bucket) if bucket else {}
