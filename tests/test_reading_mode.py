from __future__ import annotations

from dataclasses import dataclass

from utils.reading_mode import apply_reading_mode


@dataclass
class DummyChunk:
    index: int
    text: str
    source: str = "dummy.pdf"
    section_title: str = ""
    parser: str = "pypdf"


def _mk_mineru_chunks(titles: list[str]) -> list[DummyChunk]:
    return [
        DummyChunk(
            index=i,
            text=f"{t} content",
            section_title=t,
            parser="mineru",
        )
        for i, t in enumerate(titles)
    ]


def _mk_pypdf_chunks(texts: list[str]) -> list[DummyChunk]:
    return [
        DummyChunk(
            index=i,
            text=t,
            section_title="",
            parser="pypdf",
        )
        for i, t in enumerate(texts)
    ]


def test_detailed_keeps_order_and_count() -> None:
    chunks = _mk_mineru_chunks(["Preface", "Abstract", "Method", "Result", "Conclusion"])
    out = apply_reading_mode(chunks, "detailed")
    assert len(out) == len(chunks)
    assert [c.index for c in out] == [c.index for c in chunks]


def test_mineru_fast_only_keeps_abstract_method_experiment() -> None:
    chunks = _mk_mineru_chunks(["Preface", "Abstract", "Related Work", "Method", "Appendix"])
    out = apply_reading_mode(chunks, "fast")
    assert any(c.section_title == "Abstract" for c in out)
    assert any(c.section_title == "Method" for c in out)
    assert all(c.section_title in {"Abstract", "Method"} for c in out)
    assert [c.index for c in out] == sorted(c.index for c in out)


def test_mineru_fast_does_not_include_introduction_even_if_text_mentions_method() -> None:
    chunks = [
        DummyChunk(index=0, section_title="Abstract", text="summary", parser="mineru"),
        DummyChunk(index=1, section_title="1 Introduction", text="we introduce our method and experiments", parser="mineru"),
        DummyChunk(index=2, section_title="3 Method", text="details", parser="mineru"),
        DummyChunk(index=3, section_title="4 Experiments", text="results", parser="mineru"),
    ]
    out = apply_reading_mode(chunks, "fast")
    titles = [c.section_title for c in out]
    assert "1 Introduction" not in titles
    assert all(t in {"Abstract", "3 Method", "4 Experiments"} for t in titles)
    assert "Abstract" in titles


def test_mineru_focus_ratio_and_boundaries() -> None:
    titles = [
        "Cover",
        "Abstract",
        "Introduction",
        "Related Work",
        "Method",
        "Implementation",
        "Experiment Setup",
        "Results",
        "Discussion",
        "Conclusion",
        "Limitation",
        "Appendix",
    ]
    chunks = _mk_mineru_chunks(titles)
    out = apply_reading_mode(chunks, "focus")
    out_idx = [c.index for c in out]
    assert len(out) == 8  # ceil(12 * 0.6)=8
    assert 0 in out_idx
    assert 11 in out_idx
    assert out_idx == sorted(out_idx)


def test_pypdf_fast_and_focus_stable_order() -> None:
    texts = [
        "background intro",
        "abstract summary of this paper",
        "related work baseline",
        "our method details",
        "algorithm design and method",
        "training setting",
        "experiment setup",
        "evaluation metric",
        "results and analysis",
        "more results",
        "ablation study",
        "discussion",
        "conclusion and future work",
        "appendix note",
        "extra details",
        "error cases",
        "limitations",
        "final discussion",
        "supplement",
        "references",
    ]
    chunks = _mk_pypdf_chunks(texts)

    out_fast = apply_reading_mode(chunks, "fast")
    fast_idx = [c.index for c in out_fast]
    assert len(out_fast) <= max(4, 5)  # ceil(20*0.25)=5
    assert fast_idx == sorted(fast_idx)
    assert all(
        "conclusion" not in c.text.lower()
        and "discussion" not in c.text.lower()
        and "appendix" not in c.text.lower()
        for c in out_fast
    )

    out_focus = apply_reading_mode(chunks, "focus")
    focus_idx = [c.index for c in out_focus]
    assert len(out_focus) == 12  # ceil(20*0.6)=12
    assert focus_idx == sorted(focus_idx)


def test_small_paper_thresholds() -> None:
    small_focus = _mk_pypdf_chunks(["a", "b", "c", "d", "e", "f"])
    out_focus = apply_reading_mode(small_focus, "focus")
    assert len(out_focus) == len(small_focus)

    small_fast = _mk_pypdf_chunks(["a", "method", "result", "conclusion"])
    out_fast = apply_reading_mode(small_fast, "fast")
    assert len(out_fast) == 2
