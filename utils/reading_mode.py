from __future__ import annotations

import math
import re
from typing import Dict, List, Literal, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.pdf_loader import PdfChunk


ReadingMode = Literal["fast", "detailed", "standard", "focus"]

_CORE_KEYWORDS: Dict[str, List[str]] = {
    "abstract": ["abstract", "摘要"],
    "method": ["method", "methods", "approach", "methodology", "方法", "算法", "模型"],
    "experiment": ["experiment", "experiments", "evaluation", "result", "results", "实验", "评估", "结果"],
    "conclusion": ["conclusion", "conclusions", "discussion", "总结", "结论", "讨论"],
}
_FAST_CATEGORIES = ("abstract", "method", "experiment")


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _category_hits(text: str) -> Dict[str, bool]:
    t = _normalize(text)
    return {k: any(kw in t for kw in kws) for k, kws in _CORE_KEYWORDS.items()}


def _fast_score_text(text: str) -> int:
    # Limit scan length to reduce per-chunk latency on long texts.
    hits = _category_hits(str(text or "")[:2000])
    score = 0
    if hits["abstract"]:
        score += 2
    if hits["method"]:
        score += 3
    if hits["experiment"]:
        score += 3
    return score


def _pick_top_by_score(indices: List[int], scores: Dict[int, int], limit: int) -> List[int]:
    ranked = sorted(indices, key=lambda i: (-scores.get(i, 0), i))
    return ranked[: max(0, limit)]


def _as_ordered_chunks(chunks: List["PdfChunk"], indices: Set[int]) -> List["PdfChunk"]:
    return [c for i, c in enumerate(chunks) if i in indices]


def _target_fast(total: int) -> int:
    if total <= 4:
        return min(total, 2)
    return min(total, max(4, math.ceil(total * 0.25)))


def _apply_mineru_fast(chunks: List["PdfChunk"]) -> List["PdfChunk"]:
    n = len(chunks)
    target = _target_fast(n)
    candidates: List[int] = []
    for i, c in enumerate(chunks):
        title = str(getattr(c, "section_title", "") or "")
        title_hits = _category_hits(title)
        is_fast_title = any(title_hits[cat] for cat in _FAST_CATEGORIES)
        if is_fast_title:
            candidates.append(i)

    if not candidates:
        return chunks[: min(n, target)]

    # MinerU has section titles, so fast mode strictly follows section title only.
    # Keep original document order and do not inject non-target sections.
    selected = candidates[:target]
    return _as_ordered_chunks(chunks, set(selected))


def _apply_pypdf_fast(chunks: List["PdfChunk"]) -> List["PdfChunk"]:
    n = len(chunks)
    target = _target_fast(n)
    fast_scores = {i: _fast_score_text(getattr(c, "text", "")) for i, c in enumerate(chunks)}

    cat_indices: Dict[str, List[int]] = {k: [] for k in _FAST_CATEGORIES}
    for i, c in enumerate(chunks):
        hits = _category_hits(getattr(c, "text", ""))
        for cat in _FAST_CATEGORIES:
            matched = hits.get(cat, False)
            if matched:
                cat_indices[cat].append(i)

    quotas = {
        "abstract": max(1, math.ceil(target * 0.25)),
        "method": max(1, math.ceil(target * 0.40)),
        "experiment": max(1, target - (math.ceil(target * 0.25) + math.ceil(target * 0.40))),
    }

    selected: Set[int] = set()
    for cat in _FAST_CATEGORIES:
        ranked = _pick_top_by_score(cat_indices[cat], fast_scores, quotas[cat])
        for i in ranked:
            selected.add(i)
            if len(selected) >= target:
                break
        if len(selected) >= target:
            break

    if len(selected) < target:
        fast_positive = [i for i in range(n) if fast_scores.get(i, 0) > 0]
        for i in _pick_top_by_score(fast_positive, fast_scores, target):
            selected.add(i)
            if len(selected) >= target:
                break

    if not selected:
        return chunks[: min(n, target)]

    return _as_ordered_chunks(chunks, selected)


def apply_reading_mode(chunks: List["PdfChunk"], reading_mode: ReadingMode) -> List["PdfChunk"]:
    if not chunks:
        return chunks

    mode = str(reading_mode or "detailed").strip().lower()
    if mode in {"standard", "focus"}:
        mode = "detailed"
    if mode not in {"fast", "detailed"}:
        mode = "detailed"
    if mode == "detailed":
        return chunks

    parser = str(getattr(chunks[0], "parser", "pypdf") or "pypdf").strip().lower()
    if parser == "mineru":
        return _apply_mineru_fast(chunks)
    return _apply_pypdf_fast(chunks)
