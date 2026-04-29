import os
import json
import shutil
import hashlib
from pathlib import Path

from gsuid_core.logger import logger


def count_files(directory: Path, pattern: str = "*") -> int:
    """统计目录下指定模式的文件数量"""
    if not directory.exists():
        return 0
    return sum(1 for file in directory.rglob(pattern) if file.is_file())


def get_file_hash(file_path):
    """计算单个文件的哈希值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        hash_md5.update(f.read())
    return hash_md5.hexdigest()


def get_file_hash_sha256(file_path):
    """计算单个文件的 SHA256 哈希值"""
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        hash_sha256.update(f.read())
    return hash_sha256.hexdigest()


def check_file_hash(path: Path) -> bool:
    hash_file = path / "hash.json"
    if not hash_file.exists():
        return False

    try:
        with open(hash_file, 'r', encoding='utf-8') as f:
            hash_data = json.load(f)
    except Exception as e:
        logger.error(f"[鸣潮] 读取 hash.json 失败: {e}")
        return False

    deleted = False

    for file in path.iterdir():
        if file.is_file() and file.suffix != '.json':
            filename = file.name

            if filename in hash_data:
                try:
                    file_hash = get_file_hash_sha256(file)
                    expected_hash = hash_data[filename]

                    if file_hash != expected_hash:
                        logger.info(f"[鸣潮] 文件 {filename} hash 不匹配，已删除")
                        file.unlink()
                        deleted = True
                except Exception as e:
                    logger.error(f"[鸣潮] 检查文件 {filename} hash 失败: {e}")

    return deleted



def copy_if_different(src, dst, name, soft=False):
    """复制并返回是否有更新"""
    if not os.path.exists(src):
        logger.debug(f"[鸣潮] {name} 源目录不存在")
        return False

    src_path = Path(src)
    dst_path = Path(dst)
    if dst_path.exists() and count_files(dst_path, "*.py") > 0:
        return False

    needs_update = False

    for src_file in sorted(src_path.rglob("*")):
        if src_file.is_file() and not src_file.suffix == ".json":
            rel_path = src_file.relative_to(src)
            dst_file = Path(dst) / rel_path

            if not dst_file.exists():
                needs_update = True
                break

            if get_file_hash(src_file) != get_file_hash(dst_file):
                needs_update = True
                break

    if needs_update:
        try:
            if not soft:
                shutil.copytree(src, dst, dirs_exist_ok=True)
        except Exception as e:
            logger.exception(f"[鸣潮] {name} 更新失败！{e}")
        logger.info(f"[鸣潮] {name} 更新完成！")
        return True
    else:
        logger.debug(f"[鸣潮] {name} 无需更新")
        return False
