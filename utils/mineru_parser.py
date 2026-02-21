from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable, Optional

import requests
from dotenv import load_dotenv

DEFAULT_API_BASE = "https://mineru.net/api/v4"
DEFAULT_INTERVAL = 5
DEFAULT_TIMEOUT = 300
_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    root = Path(__file__).resolve().parents[1]
    utils_env = root / "utils" / ".env"
    root_env = root / ".env"
    cwd_env = Path.cwd() / ".env"
    # 只加载一个 .env：优先项目内（utils > root），最后才 cwd，避免 Streamlit 从别处启动时用到错误的 .env 导致 401
    for path in (utils_env, root_env, cwd_env):
        if path.exists():
            load_dotenv(dotenv_path=str(path), override=False)
            break
    _DOTENV_LOADED = True


def _get_token(explicit: Optional[str] = None) -> Optional[str]:
    _load_dotenv_once()
    if explicit is not None:
        token = str(explicit).strip()
        return token or None
    env_token = os.getenv("MINERU_API_TOKEN") or os.getenv("MINERU_TOKEN")
    token = (env_token or "").strip()
    # 去掉 .env 里可能带的首尾引号，避免 401
    if token and len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        token = token[1:-1].strip()
    return token or None


def token_available() -> bool:
    return _get_token() is not None


def _get_api_base(explicit: Optional[str] = None) -> str:
    _load_dotenv_once()
    if explicit is not None:
        base = str(explicit).strip()
        if base:
            return base.rstrip("/")
    env_base = (os.getenv("MINERU_API_BASE") or "").strip()
    return (env_base or DEFAULT_API_BASE).rstrip("/")


def _safe_stem(path: Path) -> str:
    stem = path.stem.strip() or "pdf"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)


def _default_output_dir(pdf_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "output" / "mineru" / _safe_stem(pdf_path)


def upload_pdf_to_mineru(
    pdf_path: str | Path,
    *,
    token: Optional[str] = None,
    api_base: Optional[str] = None,
    language: str = "ch",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = True,
) -> str:
    """
    Upload a PDF to MinerU and return the batch_id.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    token = _get_token(token)
    if not token:
        raise RuntimeError("Missing MinerU token (set MINERU_API_TOKEN)")

    api_base = _get_api_base(api_base)
    url = f"{api_base}/file-urls/batch"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = {
        "enable_formula": bool(enable_formula),
        "language": str(language),
        "enable_table": bool(enable_table),
        "files": [
            {
                "name": pdf_path.name,
                "is_ocr": bool(is_ocr),
                "data_id": "paper2gal",
            }
        ],
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"MinerU upload request failed: {data}")

    batch_id = data["data"]["batch_id"]
    urls: Iterable[str] = data["data"].get("file_urls") or []
    urls = list(urls)
    if not urls:
        raise RuntimeError("MinerU upload URL list is empty")

    for put_url in urls:
        with pdf_path.open("rb") as f:
            put_resp = requests.put(put_url, data=f, timeout=60)
            put_resp.raise_for_status()

    return batch_id


def download_mineru_result(
    batch_id: str,
    *,
    output_dir: str | Path,
    token: Optional[str] = None,
    api_base: Optional[str] = None,
    interval: int = DEFAULT_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """
    Poll MinerU for extraction result, download, and unzip into output_dir.
    """
    token = _get_token(token)
    if not token:
        raise RuntimeError("Missing MinerU token (set MINERU_API_TOKEN)")

    api_base = _get_api_base(api_base)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    url = f"{api_base}/extract-results/batch/{batch_id}"
    start_time = time.time()

    while True:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"MinerU polling failed: {data}")

        extract_info = data["data"]["extract_result"][0]
        state = extract_info.get("state")

        if state == "done":
            zip_url = extract_info["full_zip_url"]
            zip_resp = requests.get(zip_url, timeout=60)
            zip_resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
                zf.extractall(output_dir)
            return output_dir

        if time.time() - start_time > timeout:
            raise TimeoutError("MinerU extraction timed out")

        time.sleep(max(1, int(interval)))


def find_markdown_file(extracted_dir: Path) -> Path:
    """
    Locate the most likely markdown file in the extracted directory.
    """
    full_md = extracted_dir / "full.md"
    if full_md.exists():
        return full_md

    md_files = list(extracted_dir.rglob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No markdown files found in: {extracted_dir}")

    return max(md_files, key=lambda p: p.stat().st_size)


def parse_pdf_to_markdown(
    pdf_path: str | Path,
    *,
    output_dir: Optional[str | Path] = None,
    token: Optional[str] = None,
    api_base: Optional[str] = None,
    use_cache: bool = True,
    interval: int = DEFAULT_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """
    Parse a PDF with MinerU and return the markdown file path.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(output_dir) if output_dir else _default_output_dir(pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    if use_cache:
        md_candidates = list(out_dir.rglob("*.md"))
        if md_candidates:
            return max(md_candidates, key=lambda p: p.stat().st_size)

    batch_id = upload_pdf_to_mineru(pdf_path, token=token, api_base=api_base)
    download_mineru_result(
        batch_id,
        output_dir=out_dir,
        token=token,
        api_base=api_base,
        interval=interval,
        timeout=timeout,
    )
    return find_markdown_file(out_dir)
