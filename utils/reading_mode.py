from __future__ import annotations

import math
import re
from typing import Dict, List, Literal, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.pdf_loader import PdfChunk


ReadingMode = Literal["fast", "focus", "detailed"]

_CORE_KEYWORDS: Dict[str, List[str]] = {
    "abstract": ["abstract", "摘要"],
    "method": ["method", "methods", "approach", "methodology", "方法", "算法", "模型"],
    "experiment": ["experiment", "experiments", "evaluation", "result", "results", "实验", "评估", "结果"],
    "conclusion": ["conclusion", "conclusions", "discussion", "总结", "结论", "讨论"],
}
_FAST_CATEGORIES = ("abstract", "method", "experiment")
_FOCUS_RATIO = 0.60
_PYPDF_FOCUS_WINDOWS = 6


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _category_hits(text: str) -> Dict[str, bool]:
    t = _normalize(text)
    return {k: any(kw in t for kw in kws) for k, kws in _CORE_KEYWORDS.items()}


def _score_chunk(chunk: "PdfChunk") -> int:
    section_title = _normalize(getattr(chunk, "section_title", ""))
    body = _normalize(getattr(chunk, "text", ""))
    full = f"{section_title} {body}".strip()
    hits = _category_hits(full)

    score = 0
    if hits["abstract"]:
        score += 2
    if hits["method"]:
        score += 3
    if hits["experiment"]:
        score += 3
    if hits["conclusion"]:
        score += 2
    return score


def _fast_score_text(text: str) -> int:
    hits = _category_hits(text)
    score = 0
    if hits["abstract"]:
        score += 2
    if hits["method"]:
        score += 3
    if hits["experiment"]:
        score += 3
    return score


def _uniform_sample_indices(total: int, k: int) -> List[int]:
    if total <= 0 or k <= 0:
        return []
    if k >= total:
        return list(range(total))
    if k == 1:
        return [0]
    # Evenly sample indices including boundaries.
    out = []
    for i in range(k):
        idx = round(i * (total - 1) / (k - 1))
        out.append(int(idx))
    return sorted(set(out))


def _pick_top_by_score(indices: List[int], scores: Dict[int, int], limit: int) -> List[int]:
    ranked = sorted(indices, key=lambda i: (-scores.get(i, 0), i))
    return ranked[: max(0, limit)]


def _as_ordered_chunks(chunks: List["PdfChunk"], indices: Set[int]) -> List["PdfChunk"]:
    return [c for i, c in enumerate(chunks) if i in indices]


def _target_fast(total: int) -> int:
    if total <= 4:
        return min(total, 2)
    return min(total, max(4, math.ceil(total * 0.25)))


def _target_focus(total: int) -> int:
    return min(total, max(8, math.ceil(total * _FOCUS_RATIO)))


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


def _apply_mineru_focus(chunks: List["PdfChunk"]) -> List["PdfChunk"]:
    n = len(chunks)
    if n <= 6:
        return chunks

    target = _target_focus(n)
    core_indices = []
    other_indices = []
    for i, c in enumerate(chunks):
        title_hits = _category_hits(getattr(c, "section_title", ""))
        if any(title_hits.values()):
            core_indices.append(i)
        else:
            other_indices.append(i)

    ordered = [0, n - 1] + core_indices + other_indices
    dedup = []
    seen: Set[int] = set()
    for i in ordered:
        if i not in seen:
            seen.add(i)
            dedup.append(i)
    selected = set(dedup[:target])

    if len(selected) < target:
        selected.update(_uniform_sample_indices(n, target))

    selected.add(0)
    selected.add(n - 1)
    return _as_ordered_chunks(chunks, selected)


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


def _apply_pypdf_focus(chunks: List["PdfChunk"]) -> List["PdfChunk"]:
    n = len(chunks)
    if n <= 6:
        return chunks

    target = _target_focus(n)
    scores = {i: _score_chunk(c) for i, c in enumerate(chunks)}
    selected: Set[int] = {0, n - 1}

    # Coverage pass: split into windows and keep one best chunk per window.
    win_count = min(_PYPDF_FOCUS_WINDOWS, n)
    for w in range(win_count):
        start = math.floor(w * n / win_count)
        end = math.floor((w + 1) * n / win_count)
        candidates = list(range(start, max(start + 1, end)))
        best = _pick_top_by_score(candidates, scores, 1)
        if best:
            selected.add(best[0])
        if len(selected) >= target:
            break

    if len(selected) < target:
        for i in _pick_top_by_score(list(range(n)), scores, target):
            selected.add(i)
            if len(selected) >= target:
                break

    if len(selected) < target:
        selected.update(_uniform_sample_indices(n, target))

    return _as_ordered_chunks(chunks, selected)


def apply_reading_mode(chunks: List["PdfChunk"], reading_mode: ReadingMode) -> List["PdfChunk"]:
    if not chunks:
        return chunks

    mode = str(reading_mode or "detailed").strip().lower()
    if mode not in {"fast", "focus", "detailed"}:
        mode = "detailed"
    if mode == "detailed":
        return chunks

    parser = str(getattr(chunks[0], "parser", "pypdf") or "pypdf").strip().lower()
    if parser == "mineru":
        return _apply_mineru_fast(chunks) if mode == "fast" else _apply_mineru_focus(chunks)
    return _apply_pypdf_fast(chunks) if mode == "fast" else _apply_pypdf_focus(chunks)
