"""基于拼音 + 字面相似度的"你可能想找"通用模糊匹配。

- 处理打错字: 拼音化后用 SequenceMatcher 算相似度
- 处理顺序颠倒: 拼音字符排序后再比较
- 处理英文输入: 直接走字面相似度
- 处理子串: 短输入是候选子串时给出加分

pypinyin 是可选依赖；未安装时降级为纯字面匹配（打错字情况会变弱但仍可用）。
"""

from __future__ import annotations

import difflib
from typing import Dict, List, Tuple, Iterable

from gsuid_core.logger import logger


def _import_pypinyin():
    try:
        from pypinyin import lazy_pinyin, Style  # type: ignore
        return lazy_pinyin, Style
    except Exception:
        logger.warning("[鸣潮] 未安装pypinyin，安装后可使wiki查询失败时给出'你可能想找'的拼音模糊建议。")
        logger.info("[鸣潮] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install pypinyin")
        logger.info("[鸣潮] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install pypinyin")
        return None, None


lazy_pinyin, Style = _import_pypinyin()
_HAS_PYPINYIN = lazy_pinyin is not None


_pinyin_cache: Dict[str, str] = {}


def _to_pinyin(s: str) -> str:
    """中文转无声调拼音串，非中文小写保留。命中缓存后直接返回。"""
    if s in _pinyin_cache:
        return _pinyin_cache[s]
    if _HAS_PYPINYIN:
        result = "".join(lazy_pinyin(s, style=Style.NORMAL)).lower()
    else:
        result = s.lower()
    _pinyin_cache[s] = result
    return result


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _score_pair(query_norm: str, query_py: str, query_py_sorted: str, name: str) -> float:
    """对比 query 和单个候选名，返回 [0,1] 分数。"""
    n_lower = name.lower()
    n_py = _to_pinyin(name)
    n_py_sorted = "".join(sorted(n_py))

    s = max(
        _ratio(query_norm, n_lower),
        _ratio(query_py, n_py),
        _ratio(query_py_sorted, n_py_sorted),
    )

    # 子串加分: 双方拼音都至少 3 字符时启用, 避免 yy/sh/xk 等短缩写
    # 对其他无关 query 产生大量子串噪声命中
    if query_py and n_py:
        short = min(len(query_py), len(n_py))
        long_ = max(len(query_py), len(n_py))
        if short >= 3 and (query_py in n_py or n_py in query_py):
            s = max(s, 0.6 + 0.4 * short / long_)

    return s


def fuzzy_suggest(
    query: str,
    candidates: Dict[str, List[str]],
    top_n: int = 1,
    min_score: float = 0.6,
) -> List[Tuple[str, float]]:
    """对单个别名表做模糊匹配。

    Args:
        query: 用户输入
        candidates: 别名表 {规范名: [别名1, 别名2, ...]}
        top_n: 返回前 N 个建议
        min_score: 分数下限, 低于此值不返回

    Returns:
        [(规范名, 分数), ...] 按分数降序排列, 长度 <= top_n
    """
    q = query.strip()
    if not q or not candidates:
        return []

    q_lower = q.lower()
    q_py = _to_pinyin(q)
    q_py_sorted = "".join(sorted(q_py))

    scores: Dict[str, float] = {}
    for canonical, aliases in candidates.items():
        names: Iterable[str] = (canonical, *aliases)
        best = 0.0
        for name in names:
            s = _score_pair(q_lower, q_py, q_py_sorted, name)
            if s > best:
                best = s
                if best >= 0.99:
                    break
        if best >= min_score:
            scores[canonical] = best

    return sorted(scores.items(), key=lambda x: -x[1])[:top_n]


def fuzzy_suggest_multi(
    query: str,
    sources: List[Tuple[str, Dict[str, List[str]]]],
    top_n: int = 3,
    min_score: float = 0.6,
) -> List[Tuple[str, str, float]]:
    """跨多个分类并联搜索, 用于不知道用户找的是哪一类的场景。

    Args:
        sources: [(label, candidates), ...], 例如 [("武器", weapon_alias_data), ...]

    Returns:
        [(label, 规范名, 分数), ...] 按分数降序, 长度 <= top_n
    """
    pool: List[Tuple[str, str, float]] = []
    for label, cand in sources:
        for name, score in fuzzy_suggest(query, cand, top_n=top_n, min_score=min_score):
            pool.append((label, name, score))
    return sorted(pool, key=lambda x: -x[2])[:top_n]


def format_suggestions(
    suggestions: List[Tuple[str, float]] | List[Tuple[str, str, float]],
    prefix: str = "你可能想找",
) -> str:
    """把 suggest 结果格式化成提示文本; 空列表返回空串。"""
    if not suggestions:
        return ""
    lines = [f"{prefix}:"]
    for item in suggestions:
        if len(item) == 3:
            label, name, _ = item
            lines.append(f" - {name} ({label})")
        else:
            name, _ = item
            lines.append(f" - {name}")
    return "\n".join(lines)
