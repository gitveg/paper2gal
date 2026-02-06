from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from utils.mineru_parser import parse_pdf_to_markdown, token_available


@dataclass(frozen=True)
class PdfChunk:
    """One section or one text unit for script generation."""

    index: int
    text: str
    source: str
    section_title: str = ""  # 章节名，如 Abstract / 1 Introduction（MinerU 时有值）


def _load_docs_with_pypdf(pdf_path: Path) -> List[Document]:
    reader = PdfReader(str(pdf_path))
    docs: List[Document] = []
    for page_idx, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if not text:
            continue
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": str(pdf_path),
                    "page": page_idx,
                    "parser": "pypdf",
                },
            )
        )
    return docs


def _clean_markdown_text(md_text: str) -> str:
    # Drop image links to reduce noise.
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md_text)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)
    return text


def _split_markdown_sections(md_text: str) -> List[Tuple[str, int, str]]:
    """
    Split markdown into sections by headings.
    Returns a list of (title, level, content).
    """
    lines = md_text.splitlines()
    sections: List[Tuple[str, int, List[str]]] = []
    current_title = "Preamble"
    current_level = 0
    buffer: List[str] = []

    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    for line in lines:
        m = heading_re.match(line)
        if m:
            if buffer:
                sections.append((current_title, current_level, buffer))
                buffer = []
            current_level = len(m.group(1))
            current_title = m.group(2).strip()
            continue
        buffer.append(line)

    if buffer:
        sections.append((current_title, current_level, buffer))

    normalized: List[Tuple[str, int, str]] = []
    for title, level, buf in sections:
        content = "\n".join(buf).strip()
        if content:
            normalized.append((title, level, content))
    return normalized


def _load_docs_with_mineru(pdf_path: Path, *, output_dir: Optional[Path] = None) -> List[Document]:
    md_path = parse_pdf_to_markdown(pdf_path, output_dir=output_dir)
    md_text = md_path.read_text(encoding="utf-8", errors="ignore")
    md_text = _clean_markdown_text(md_text).strip()
    if not md_text:
        return []

    sections = _split_markdown_sections(md_text)
    if not sections:
        sections = [("Full", 0, md_text)]

    docs: List[Document] = []
    for idx, (title, level, content) in enumerate(sections):
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "source": str(pdf_path),
                    "parser": "mineru",
                    "md_path": str(md_path),
                    "section_title": title,
                    "section_level": level,
                    "section_index": idx,
                },
            )
        )
    return docs


def load_and_chunk_pdf(
    pdf_path: str | Path,
    *,
    chunk_size: int = 1400,
    chunk_overlap: int = 180,
    use_mineru: bool = True,
    mineru_fallback: bool = True,
    mineru_output_dir: Optional[str | Path] = None,
) -> List[PdfChunk]:
    """
    Parse a PDF and split it into chunks for downstream script generation.

    - Default: MinerU OCR (if token available)
    - Fallback: pypdf text extraction
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(mineru_output_dir) if mineru_output_dir else None

    docs: List[Document] = []
    if use_mineru and token_available():
        docs = _load_docs_with_mineru(pdf_path, output_dir=output_dir)
        if not docs and mineru_fallback:
            docs = _load_docs_with_pypdf(pdf_path)
    else:
        docs = _load_docs_with_pypdf(pdf_path)
        if not docs and mineru_fallback and token_available():
            docs = _load_docs_with_mineru(pdf_path, output_dir=output_dir)

    chunks: List[PdfChunk] = []
    # MinerU：按 section 为粒度，不再对 section 内做字符切分，保持连贯
    is_mineru = docs and str((docs[0].metadata or {}).get("parser")) == "mineru"
    if is_mineru:
        for d in docs:
            text = (d.page_content or "").strip()
            if not text:
                continue
            source = str(d.metadata.get("source") or pdf_path.name)
            section_title = str(d.metadata.get("section_title") or "").strip()
            chunks.append(PdfChunk(index=len(chunks), text=text, source=source, section_title=section_title))
        return chunks

    # pypdf 或无 section 时：按字符分块
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "，", ";", "；", ",", " ", ""],
    )
    for d in splitter.split_documents(docs):
        text = (d.page_content or "").strip()
        if not text:
            continue
        source = str(d.metadata.get("source") or pdf_path.name)
        chunks.append(PdfChunk(index=len(chunks), text=text, source=source))

    return chunks
