from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
import requests

from utils.mineru_parser import parse_pdf_to_markdown, token_available


@dataclass(frozen=True)
class PdfChunk:
    """One section or one text unit for script generation."""

    index: int
    text: str
    source: str
    section_title: str = ""  # 章节名，如 Abstract / 1 Introduction（MinerU 时有值）
    parser: str = "pypdf"  # "mineru" | "pypdf"，用于 debug 显示当前解析方式
    images_dir: str = ""   # MinerU 提取图片所在目录
    image_map: Tuple[Tuple[str, str], ...] = ()  # ((figure_label, abs_image_path), ...)


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


def _extract_figure_label(caption: str) -> Optional[str]:
    """从图注中提取标准图号：Figure N / Fig. N / 图N / Table N / Tab. N / 表N。"""
    # Figure / Fig
    m = re.search(r"(fig(?:ure)?\.?\s*\d+[a-z]?)", caption, re.I)
    if m:
        return m.group(1).strip()
    # Table / Tab
    m = re.search(r"(tab(?:le)?\.?\s*\d+[a-z]?)", caption, re.I)
    if m:
        return m.group(1).strip()
    # 图N（中文）
    m = re.search(r"(图\s*\d+[a-z]?)", caption)
    if m:
        return m.group(1).strip()
    # 表N（中文）
    m = re.search(r"(表\s*\d+[a-z]?)", caption)
    if m:
        return m.group(1).strip()
    return None


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# 整行图片引用（MinerU 通常单独一行）
_LINE_IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
# 行内图片引用（句子中夹杂图片）
_INLINE_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _extract_images_and_clean(
    md_text: str, md_parent_dir: Path
) -> Tuple[str, Dict[str, str]]:
    """
    逐行解析 Markdown，提取图片引用，构建图片映射表：
    - 对于 MinerU 常见格式（整行空 caption 图片，图号在后续行），向后扫描最多 3 行寻找图号
    - 对行内嵌图片同样支持
    - 跳过 CDN URL（不下载）

    返回:
        (annotated_text, {figure_label: absolute_image_path})
    """
    image_map: Dict[str, str] = {}
    auto_counter = {"n": 0}
    lines = md_text.splitlines()
    result_lines: List[str] = []

    def _register_image(caption: str, raw_path: str, lookahead_lines: List[str]) -> str:
        """注册一张图片到 image_map，返回替换后的文字标注。"""
        if raw_path.startswith(("http://", "https://", "//")):
            return f"[图片: {caption}]" if caption else "[图片]"

        abs_path = md_parent_dir / raw_path
        if not (abs_path.exists() and abs_path.suffix.lower() in _IMAGE_EXTS):
            return f"[图片: {caption or raw_path}]"

        # 1) 从 caption 提取图号
        label = _extract_figure_label(caption) if caption else None

        # 2) caption 为空时，向后扫最多 3 行找图号（MinerU 格式：图号在图片后的段落文字里）
        if not label:
            for ahead in lookahead_lines:
                ahead = ahead.strip()
                if ahead:
                    label = _extract_figure_label(ahead)
                    if label:
                        break

        # 3) 仍无图号：用自动计数器
        if not label:
            auto_counter["n"] += 1
            label = f"Figure {auto_counter['n']}"

        if label not in image_map:
            image_map[label] = str(abs_path)

        return f"[图片: {label}]"

    i = 0
    while i < len(lines):
        line = lines[i]
        m = _LINE_IMG_RE.match(line)
        if m:
            caption = m.group(1).strip()
            raw_path = m.group(2).strip()
            lookahead = lines[i + 1: i + 4]  # 后续最多 3 行
            result_lines.append(_register_image(caption, raw_path, lookahead))
            i += 1
            continue

        # 处理行内嵌的图片引用
        if _INLINE_IMG_RE.search(line):
            def _replace_inline(mm: re.Match) -> str:
                return _register_image(mm.group(1).strip(), mm.group(2).strip(), [])
            line = _INLINE_IMG_RE.sub(_replace_inline, line)
            line = re.sub(r"<img[^>]*>", "[图片]", line, flags=re.I)

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines), image_map


_HEX_HASH_RE = re.compile(r"^[0-9a-f]{16,}$", re.I)


def _collect_dir_images(images_dir: Path, image_map: Dict[str, str]) -> None:
    """
    扫描图片目录，补充 Markdown 没有引用的图片。
    对于 MinerU 常见的 hash 文件名（如 7f523138...jpg），由于无法从文件名推断图号，
    这类文件仅在 Markdown 解析已正确提取后跳过（避免用随机 hash 数字生成错误 label）。
    对于有意义文件名（含顺序数字，如 fig_1.png），正常提取图号。
    """
    if not images_dir.exists() or not images_dir.is_dir():
        return
    existing_paths = set(image_map.values())
    existing_nums: set = {re.search(r"(\d+)", k).group(1) for k in image_map if re.search(r"(\d+)", k)}
    fallback_n = max((int(n) for n in existing_nums if n.isdigit()), default=0)

    for img_file in sorted(images_dir.iterdir()):
        if img_file.suffix.lower() not in _IMAGE_EXTS:
            continue
        if str(img_file) in existing_paths:
            continue
        stem = img_file.stem
        # hash 文件名（纯十六进制字符串，长度≥16）→ 跳过，避免生成错误 label
        if _HEX_HASH_RE.match(stem):
            continue
        # 有意义文件名：提取数字
        num_m = re.search(r"(\d+)", stem)
        if num_m:
            num = num_m.group(1)
            label = f"Figure {num}"
            if num not in existing_nums:
                image_map[label] = str(img_file)
                existing_nums.add(num)
        else:
            # 完全无数字：用顺序编号
            fallback_n += 1
            label = f"Figure {fallback_n}"
            if label not in image_map:
                image_map[label] = str(img_file)


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
    raw_md = md_path.read_text(encoding="utf-8", errors="ignore")

    md_parent = md_path.parent
    # 提取全文图片映射，并把 ![...](path) 替换为文字标注
    annotated_md, paper_image_map = _extract_images_and_clean(raw_md, md_parent)
    annotated_md = annotated_md.strip()

    if not annotated_md:
        return []

    sections = _split_markdown_sections(annotated_md)
    if not sections:
        sections = [("Full", 0, annotated_md)]

    # 兜底：扫描 images/ 及常见子目录，补充 Markdown 未链接的图片
    for _subdir in ("images", "image", "imgs", "figures", "fig"):
        _collect_dir_images(md_parent / _subdir, paper_image_map)
    # 也扫描 md_parent 本身（某些 MinerU 版本把图片放根目录）
    _collect_dir_images(md_parent, paper_image_map)

    images_dir_str = str(md_parent)
    docs: List[Document] = []
    for idx, (title, level, content) in enumerate(sections):
        # 每个 chunk 都携带全文图片表，让 LLM 能引用任何已知图片
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
                    "images_dir": images_dir_str,
                    "image_map": paper_image_map,  # 全文图片表（每个 chunk 都一样）
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
        try:
            docs = _load_docs_with_mineru(pdf_path, output_dir=output_dir)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            # 401 Unauthorized 或网络错误时自动回退到 pypdf，避免 UI 直接报错
            if mineru_fallback:
                docs = _load_docs_with_pypdf(pdf_path)
            else:
                raise RuntimeError(f"MinerU 请求失败（{e}），可关闭「Use MinerU OCR」或检查 MINERU_API_TOKEN。") from e
        if not docs and mineru_fallback:
            docs = _load_docs_with_pypdf(pdf_path)
    else:
        docs = _load_docs_with_pypdf(pdf_path)
        if not docs and mineru_fallback and token_available():
            try:
                docs = _load_docs_with_mineru(pdf_path, output_dir=output_dir)
            except (requests.exceptions.HTTPError, requests.exceptions.RequestException):
                pass

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
            images_dir = str(d.metadata.get("images_dir") or "")
            image_map_dict: Dict[str, str] = d.metadata.get("image_map") or {}
            image_map_tuple: Tuple[Tuple[str, str], ...] = tuple(sorted(image_map_dict.items()))
            chunks.append(PdfChunk(
                index=len(chunks),
                text=text,
                source=source,
                section_title=section_title,
                parser="mineru",
                images_dir=images_dir,
                image_map=image_map_tuple,
            ))
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
        chunks.append(PdfChunk(index=len(chunks), text=text, source=source, parser="pypdf"))

    return chunks
