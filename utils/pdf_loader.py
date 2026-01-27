from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


@dataclass(frozen=True)
class PdfChunk:
    """一个用于剧本生成的最小文本单元。"""

    index: int
    text: str
    source: str


def load_and_chunk_pdf(
    pdf_path: str | Path,
    *,
    chunk_size: int = 1400,
    chunk_overlap: int = 180,
) -> List[PdfChunk]:
    """
    解析 PDF 并切分为文本块（chunk）。

    - 使用 pypdf 读取页面文本（避免依赖 langchain-community）
    - 使用 RecursiveCharacterTextSplitter 进行分块，便于逐块生成剧本
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

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
                },
            )
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", ";", "，", ",", " ", ""],
    )

    chunks: List[PdfChunk] = []
    for i, d in enumerate(splitter.split_documents(docs)):
        text = (d.page_content or "").strip()
        if not text:
            continue
        source = str(d.metadata.get("source") or pdf_path.name)
        chunks.append(PdfChunk(index=len(chunks), text=text, source=source))

    return chunks

