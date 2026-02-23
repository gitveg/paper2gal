from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

from utils.pdf_loader import load_and_chunk_pdf, PdfChunk
from utils.mineru_parser import token_available
from utils.script_engine import ScriptGenerator

# ──────────────────────────────────────────────
# 本地资源路径（必须手动放入 assets/ 目录）
# ──────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"

ASSET_BG = ASSETS_DIR / "bg_classroom.png"
ASSET_CHAR = {
    "char_normal": ASSETS_DIR / "char_normal.png",
    "char_happy":  ASSETS_DIR / "char_happy.png",
    "char_angry":  ASSETS_DIR / "char_angry.png",
    "char_shy":    ASSETS_DIR / "char_shy.png",
}

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _file_to_data_uri(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    ext = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64,{b64}"


# ──────────────────────────────────────────────
# CSS / 全局样式注入
# ──────────────────────────────────────────────

def inject_game_css(bg_data_uri: Optional[str]) -> None:
    bg_img = f"url('{bg_data_uri}')" if bg_data_uri else "none"

    st.markdown(
        f"""
<style>
/* ── 隐藏 Streamlit 默认 Chrome ── */
#MainMenu, footer, header {{ visibility: hidden; }}
[data-testid="stDecoration"],
[data-testid="stToolbar"] {{ display: none !important; }}

/* ── 全屏背景（直接注入 body/stApp，最可靠）── */
html, body, .stApp {{
  background-image: {bg_img} !important;
  background-size: cover !important;
  background-position: center center !important;
  background-repeat: no-repeat !important;
  background-attachment: fixed !important;
}}
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > .main,
.main .block-container {{
  background: transparent !important;
  padding-top: 0.5rem !important;
  max-width: 100% !important;
}}
/* Streamlit 暗色主题防止覆盖背景 */
[data-testid="stAppViewContainer"] {{
  background-color: transparent !important;
}}

/* ── 章节进度条（顶部细线）── */
.p2g-progress-wrap {{
  position: fixed; top: 0; left: 0; right: 0; height: 4px;
  background: rgba(255,255,255,0.08); z-index: 200;
}}
.p2g-progress-fill {{
  height: 100%;
  background: linear-gradient(90deg, #7b4fff 0%, #e066ff 100%);
  transition: width 0.55s ease;
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 12px rgba(160,80,255,0.6);
}}

/* ── 章节徽章（左上）── */
.p2g-section-badge {{
  position: fixed; top: 10px; left: 16px;
  background: rgba(8,6,18,0.72); backdrop-filter: blur(10px);
  border: 1px solid rgba(130,90,230,0.35); border-radius: 20px;
  padding: 0.22rem 0.9rem;
  color: rgba(195,170,255,0.85);
  font-size: 0.75rem; letter-spacing: 1.5px; z-index: 150;
}}

/* ── Debug 徽章（右上，极小）── */
.p2g-debug-badge {{
  position: fixed; top: 10px; right: 14px;
  font-size: 0.65rem; color: rgba(255,255,255,0.22);
  z-index: 150; pointer-events: none;
}}
.p2g-prefetch-badge {{
  position: fixed;
  top: 46px;
  right: 16px;
  z-index: 210;
  pointer-events: none;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  font-size: 0.72rem;
  line-height: 1.2;
  letter-spacing: 0.4px;
  background: rgba(8, 6, 18, 0.72);
  border: 1px solid rgba(130, 90, 230, 0.28);
  color: rgba(215, 198, 255, 0.88);
  backdrop-filter: blur(10px);
}}
.p2g-prefetch-badge.ready {{
  border-color: rgba(120, 230, 170, 0.35);
  color: rgba(190, 255, 226, 0.95);
}}
.p2g-prefetch-badge.loading {{
  border-color: rgba(130, 90, 230, 0.35);
  color: rgba(215, 198, 255, 0.88);
}}

/* ── 角色立绘（右下，对话框上方）── */
.p2g-char {{
  position: fixed;
  right: 1vw; bottom: 180px;
  width: min(42vw, 570px);
  z-index: 40; pointer-events: none; user-select: none;
  filter: drop-shadow(0 28px 42px rgba(0,0,0,0.65));
  transition: opacity 0.35s ease;
}}

/* ── 说话人名牌（对话框上方）── */
.p2g-nameplate {{
  position: fixed; left: 4vw; bottom: 176px;
  background: linear-gradient(135deg,
    rgba(100,55,200,0.92) 0%, rgba(58,28,135,0.92) 100%);
  color: #fff; font-weight: 800; font-size: 0.92rem;
  padding: 0.25rem 1.5rem 0.25rem 0.85rem;
  border-radius: 8px 8px 0 0; z-index: 35;
  letter-spacing: 2.5px;
  clip-path: polygon(0 0, 100% 0, 92% 100%, 0 100%);
  box-shadow: 0 -4px 20px rgba(100,55,200,0.35);
}}

/* ── 对话框（固定底部，全宽）── */
.p2g-dialogue {{
  position: fixed; left: 0; right: 0; bottom: 0;
  min-height: 172px; z-index: 30;
  /* 右 padding 动态跟随立绘宽度，避免宽屏文字过早换行 */
  padding: 1.1rem calc(min(42vw, 570px) + 1vw + 3rem) 1.3rem 4.5vw;
  background: rgba(8,5,20,0.85);
  border-top: 2px solid rgba(120,75,220,0.55);
  backdrop-filter: blur(16px);
  box-shadow: 0 -8px 48px rgba(0,0,0,0.55);
  cursor: pointer;
  user-select: none;
}}
.p2g-text {{
  color: rgba(252,248,255,0.96);
  font-family: "Yu Gothic UI", "Noto Sans CJK SC",
               "PingFang SC", system-ui, sans-serif;
  font-size: 1.04rem; line-height: 1.82; white-space: pre-wrap;
}}
.p2g-feedback {{
  margin-top: 0.5rem;
  font-size: 0.9rem; font-weight: 600;
  color: rgba(200,180,255,0.8);
}}
.p2g-feedback.correct {{ color: #7bffaa; }}
.p2g-feedback.wrong   {{ color: #ff8080; }}
.p2g-explanation {{
  margin-top: 0.55rem;
  padding: 0.5rem 0.85rem;
  background: rgba(110,70,200,0.13);
  border-left: 3px solid rgba(140,100,255,0.5);
  border-radius: 0 8px 8px 0;
  font-size: 0.88rem; line-height: 1.72;
  color: rgba(220,205,255,0.88);
}}
.p2g-explanation-label {{
  font-size: 0.68rem; letter-spacing: 2.5px;
  color: rgba(175,145,255,0.6);
  margin-bottom: 0.2rem; display: block;
}}
.p2g-next-arrow {{
  position: absolute; right: 2.2rem; bottom: 1.1rem;
  color: rgba(160,120,255,0.75); font-size: 1.05rem; font-weight: 700;
  animation: p2g-bounce 1.3s ease infinite;
}}
@keyframes p2g-bounce {{
  0%, 100% {{ transform: translateY(0);   opacity: 0.75; }}
  50%       {{ transform: translateY(4px); opacity: 1;    }}
}}

/* ── 章节标题卡（sub_head 专用，居中弹出）── */
.p2g-chapter-card {{
  position: fixed; left: 50%; top: 40%;
  transform: translate(-50%, -50%);
  background: rgba(7,5,18,0.91); backdrop-filter: blur(18px);
  border: 1px solid rgba(140,95,255,0.6); border-radius: 18px;
  padding: 2rem 4rem; text-align: center; z-index: 45;
  box-shadow: 0 0 70px rgba(100,55,200,0.35);
  min-width: min(520px, 82vw);
}}
.p2g-chapter-label {{
  font-size: 0.7rem; letter-spacing: 5px;
  color: rgba(175,145,255,0.6); text-transform: uppercase;
  margin-bottom: 0.55rem;
}}
.p2g-chapter-title {{
  color: #ead8ff; font-size: 1.45rem; font-weight: 700;
  letter-spacing: 2px;
  text-shadow: 0 0 24px rgba(180,120,255,0.45);
}}

/* ── 选项面板标题 ── */
.p2g-options-label {{
  text-align: center;
  color: rgba(195,170,255,0.7);
  font-size: 0.75rem; letter-spacing: 4px;
  text-transform: uppercase; margin-bottom: 0.35rem;
}}

/* ── 选项按钮（覆盖 Streamlit 默认）── */
div[data-testid="stButton"] {{
  position: relative;
  z-index: 180;
}}
.p2g-util-row,
.p2g-next-row {{
  position: relative;
  z-index: 181;
}}
.p2g-util-row {{
  position: fixed;
  top: 10px;
  right: 16px;
  width: 92px;
  z-index: 220;
}}
.p2g-next-row {{
  position: fixed;
  right: clamp(220px, 31vw, 430px);
  bottom: 188px;
  width: min(220px, 34vw);
  z-index: 220;
}}
div[data-testid="stButton"] > button {{
  width: 100%; text-align: left;
  padding: 0.78rem 1.3rem;
  border-radius: 10px;
  border: 1px solid rgba(120,80,220,0.42);
  background: rgba(10,7,22,0.78);
  color: rgba(238,228,255,0.94);
  font-size: 0.97rem;
  backdrop-filter: blur(10px);
  transition: all 0.18s ease;
  letter-spacing: 0.3px;
}}
div[data-testid="stButton"] > button:hover {{
  border-color: rgba(160,115,255,0.9);
  background: rgba(65,32,140,0.62);
  color: #fff;
  transform: translateX(6px);
  box-shadow: 0 4px 20px rgba(100,55,200,0.32);
}}
div[data-testid="stButton"] > button:active {{
  transform: translateX(2px) scale(0.98);
}}

/* ── 小型功能按钮（退出/回封面）── */
.p2g-util-row div[data-testid="stButton"] > button {{
  text-align: center; padding: 0.35rem 0.8rem;
  font-size: 0.78rem; letter-spacing: 1px;
  background: rgba(8,5,18,0.55);
  border-color: rgba(130,90,230,0.25);
  color: rgba(190,165,255,0.65);
  transform: none !important;
  box-shadow: none !important;
}}
.p2g-util-row div[data-testid="stButton"] > button:hover {{
  border-color: rgba(160,120,255,0.55);
  color: rgba(220,200,255,0.85);
  background: rgba(50,25,100,0.45);
  transform: none !important;
}}
.p2g-next-row div[data-testid="stButton"] > button {{
  text-align: center;
  font-weight: 700;
}}

/* ── 按按钮 key 精准定位（Streamlit 组件不会被 markdown 的 div 真正包裹）── */
.st-key-btn_exit {{
  position: fixed;
  top: 10px;
  right: 16px;
  width: 92px;
  z-index: 240;
  margin: 0 !important;
}}
.st-key-btn_continue {{
  position: fixed;
  right: clamp(230px, 31vw, 430px); /* 放在立绘左侧 */
  bottom: 188px; /* 位于对话框上方 */
  width: 92px;
  z-index: 240;
  margin: 0 !important;
}}
.st-key-btn_exit div[data-testid="stButton"],
.st-key-btn_continue div[data-testid="stButton"] {{
  margin: 0 !important;
}}
.st-key-btn_exit div[data-testid="stButton"] > button,
.st-key-btn_continue div[data-testid="stButton"] > button {{
  width: 92px !important;
  min-width: 92px !important;
  text-align: center !important;
  padding: 0.42rem 0.4rem !important;
  font-size: 0.78rem !important;
  letter-spacing: 1px !important;
  transform: none !important;
  box-shadow: none !important;
}}
.st-key-btn_exit div[data-testid="stButton"] > button:hover,
.st-key-btn_continue div[data-testid="stButton"] > button:hover {{
  transform: none !important;
}}

/* ── 小屏适配：缩小立绘，减少遮挡按钮 ── */
@media (max-width: 900px) {{
  .p2g-char {{
    width: min(38vw, 340px);
    right: 0.5rem;
    bottom: 172px;
  }}
  .p2g-dialogue {{
    padding-right: 44%;
  }}
  .p2g-next-row {{
    right: clamp(160px, 28vw, 280px);
    bottom: 182px;
    width: min(180px, 36vw);
  }}
  .st-key-btn_continue {{
    right: clamp(170px, 28vw, 300px);
    bottom: 182px;
  }}
}}
@media (max-width: 640px) {{
  .p2g-char {{
    width: min(42vw, 240px);
    right: 0.35rem;
    bottom: 160px;
    opacity: 0.95;
  }}
  .p2g-nameplate {{
    bottom: 156px;
  }}
  .p2g-dialogue {{
    min-height: 156px;
    padding: 0.9rem 42% 1rem 4vw;
  }}
  .p2g-util-row {{
    top: 8px;
    right: 10px;
    width: 84px;
  }}
  .p2g-next-row {{
    right: 116px;
    bottom: 168px;
    width: min(132px, 34vw);
  }}
  .p2g-next-row div[data-testid="stButton"] > button {{
    padding: 0.58rem 0.5rem;
    font-size: 0.88rem;
  }}
  .st-key-btn_exit {{
    top: 8px;
    right: 10px;
    width: 84px;
  }}
  .p2g-prefetch-badge {{
    top: 42px;
    right: 10px;
    font-size: 0.68rem;
    padding: 0.2rem 0.55rem;
  }}
  .st-key-btn_continue {{
    right: 112px;
    bottom: 168px;
    width: 84px;
  }}
  .st-key-btn_exit div[data-testid="stButton"] > button,
  .st-key-btn_continue div[data-testid="stButton"] > button {{
    width: 84px !important;
    min-width: 84px !important;
    padding: 0.38rem 0.3rem !important;
    font-size: 0.74rem !important;
  }}
}}
</style>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────
# 状态初始化
# ──────────────────────────────────────────────

def init_state() -> None:
    if "state" not in st.session_state:
        st.session_state.state = "LANDING"

    st.session_state.setdefault("chunks",          [])
    st.session_state.setdefault("chunk_idx",       0)
    st.session_state.setdefault("script_items",    [])
    st.session_state.setdefault("script_idx",      0)
    st.session_state.setdefault("current_feedback", None)
    st.session_state.setdefault("answered",        False)
    st.session_state.setdefault("generator_ready", False)
    st.session_state.setdefault("use_mineru",      True)
    st.session_state.setdefault("parser_used",     "pypdf")
    st.session_state.setdefault("prefetch_cache",  {})
    st.session_state.setdefault("prefetch_future", None)
    st.session_state.setdefault("prefetch_target_idx", None)
    st.session_state.setdefault("prefetch_task_run_token", None)
    st.session_state.setdefault("script_run_token", 0)
    st.session_state.setdefault("prefetch_executor", None)


def ensure_assets_notice() -> None:
    missing = []
    if not ASSET_BG.exists():
        missing.append(str(ASSET_BG))
    for p in ASSET_CHAR.values():
        if not p.exists():
            missing.append(str(p))
    if missing:
        st.warning(
            "检测到以下本地图片资源缺失，请手动放入（代码只读本地路径，不使用网图）：\n\n- "
            + "\n- ".join(missing)
        )


def get_current_item() -> Optional[Dict[str, Any]]:
    items: List[Dict[str, Any]] = st.session_state.script_items
    idx: int = st.session_state.script_idx
    if 0 <= idx < len(items):
        return items[idx]
    return None


def _get_prefetch_executor() -> ThreadPoolExecutor:
    executor = st.session_state.get("prefetch_executor")
    if executor is None:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="p2g-prefetch")
        st.session_state.prefetch_executor = executor
    return executor


def _clear_prefetch_buffer(*, bump_run_token: bool = False) -> None:
    future = st.session_state.get("prefetch_future")
    if future is not None and not future.done():
        future.cancel()

    st.session_state.prefetch_cache = {}
    st.session_state.prefetch_future = None
    st.session_state.prefetch_target_idx = None
    st.session_state.prefetch_task_run_token = None

    if bump_run_token:
        st.session_state.script_run_token = int(st.session_state.get("script_run_token", 0)) + 1


def _apply_script_items(script: List[Dict[str, Any]]) -> None:
    st.session_state.script_items     = script
    st.session_state.script_idx       = 0
    st.session_state.current_feedback = None
    st.session_state.answered         = False
    st.session_state.generator_ready  = True


def _generate_script_for_chunk(chunks: List[PdfChunk], chunk_idx: int) -> List[Dict[str, Any]]:
    gen = ScriptGenerator()
    chunk = chunks[chunk_idx]
    return gen.generate_script(
        chunk.text,
        chunk_index=chunk.index,
        section_title=getattr(chunk, "section_title", "") or None,
    )


def _generate_script_payload(
    chunk_text: str,
    *,
    chunk_index: int,
    section_title: Optional[str],
) -> List[Dict[str, Any]]:
    gen = ScriptGenerator()
    return gen.generate_script(chunk_text, chunk_index=chunk_index, section_title=section_title)


def _collect_prefetch_if_ready() -> None:
    future = st.session_state.get("prefetch_future")
    target_idx = st.session_state.get("prefetch_target_idx")
    task_run_token = st.session_state.get("prefetch_task_run_token")
    current_run_token = int(st.session_state.get("script_run_token", 0))

    if future is None or target_idx is None:
        return
    if not future.done():
        return

    try:
        script = future.result()
    except Exception:
        script = None

    st.session_state.prefetch_future = None
    st.session_state.prefetch_target_idx = None
    st.session_state.prefetch_task_run_token = None

    if script is None:
        return
    if int(task_run_token or -1) != current_run_token:
        return

    cache = dict(st.session_state.get("prefetch_cache") or {})
    cache[int(target_idx)] = script
    st.session_state.prefetch_cache = cache


def _take_prefetched_script(chunk_idx: int, *, wait_if_running: bool = False) -> Optional[List[Dict[str, Any]]]:
    _collect_prefetch_if_ready()

    cache = dict(st.session_state.get("prefetch_cache") or {})
    if chunk_idx in cache:
        script = cache.pop(chunk_idx)
        st.session_state.prefetch_cache = cache
        return script

    future = st.session_state.get("prefetch_future")
    target_idx = st.session_state.get("prefetch_target_idx")
    task_run_token = int(st.session_state.get("prefetch_task_run_token") or -1)
    current_run_token = int(st.session_state.get("script_run_token", 0))
    if future is None or target_idx != chunk_idx:
        return None
    if task_run_token != current_run_token:
        return None
    if not wait_if_running and not future.done():
        return None

    try:
        script = future.result()
    except Exception:
        script = None

    st.session_state.prefetch_future = None
    st.session_state.prefetch_target_idx = None
    st.session_state.prefetch_task_run_token = None
    return script


def _ensure_next_chunk_prefetch(chunks: List[PdfChunk], current_chunk_idx: int) -> None:
    next_idx = int(current_chunk_idx) + 1
    if next_idx < 0 or next_idx >= len(chunks):
        return

    _collect_prefetch_if_ready()

    cache = st.session_state.get("prefetch_cache") or {}
    if next_idx in cache:
        return

    future = st.session_state.get("prefetch_future")
    target_idx = st.session_state.get("prefetch_target_idx")
    task_run_token = int(st.session_state.get("prefetch_task_run_token") or -1)
    current_run_token = int(st.session_state.get("script_run_token", 0))

    if future is not None:
        if target_idx == next_idx and task_run_token == current_run_token:
            return
        if not future.done():
            return

    chunk = chunks[next_idx]
    future = _get_prefetch_executor().submit(
        _generate_script_payload,
        chunk.text,
        chunk_index=chunk.index,
        section_title=getattr(chunk, "section_title", "") or None,
    )
    st.session_state.prefetch_future = future
    st.session_state.prefetch_target_idx = next_idx
    st.session_state.prefetch_task_run_token = current_run_token


def load_script_for_chunk(chunks: List[PdfChunk], chunk_idx: int) -> None:
    script = _generate_script_for_chunk(chunks, chunk_idx)
    _apply_script_items(script)


def _reset_session() -> None:
    st.session_state.state            = "LANDING"
    st.session_state.chunks           = []
    st.session_state.chunk_idx        = 0
    st.session_state.script_items     = []
    st.session_state.script_idx       = 0
    st.session_state.current_feedback = None
    st.session_state.answered         = False
    st.session_state.generator_ready  = False
    _clear_prefetch_buffer(bump_run_token=True)


def advance() -> None:
    items: List[Dict[str, Any]] = st.session_state.script_items
    st.session_state.current_feedback = None
    st.session_state.answered         = False

    if not items:
        return

    st.session_state.script_idx += 1

    if st.session_state.script_idx >= len(items):
        chunks: List[PdfChunk] = st.session_state.chunks
        st.session_state.chunk_idx += 1
        if st.session_state.chunk_idx >= len(chunks):
            st.session_state.script_items = [
                {
                    "type":    "dialogue",
                    "speaker": "奈奈",
                    "text":    "呼……总算读完了！笨蛋主人，能坚持到最后还算有点出息喵。",
                    "emotion": "char_happy",
                }
            ]
            st.session_state.script_idx = 0
            return
        st.session_state.generator_ready = False
        st.session_state.state = "PROCESSING"
        st.rerun()


# ──────────────────────────────────────────────
# 游戏画面渲染（固定层：进度条 / 章节标记 /
#              立绘 / 名牌 / 对话框）
# ──────────────────────────────────────────────

def render_game_screen(item: Optional[Dict[str, Any]]) -> None:
    inject_game_css(_file_to_data_uri(ASSET_BG))

    chunks:    List[PdfChunk] = st.session_state.chunks
    chunk_idx: int            = st.session_state.chunk_idx
    total = len(chunks)

    # ─ 进度条 ─
    pct = int((chunk_idx / max(total - 1, 1)) * 100) if total > 1 else 100
    progress_html = f"""
<div class="p2g-progress-wrap">
  <div class="p2g-progress-fill" style="width:{pct}%"></div>
</div>"""

    # ─ 章节徽章 ─
    section_title = ""
    if chunks and 0 <= chunk_idx < total:
        section_title = getattr(chunks[chunk_idx], "section_title", "") or ""
    badge_html = (
        f'<div class="p2g-section-badge">📖 {section_title}</div>'
        if section_title else ""
    )

    # ─ Debug 徽章 ─
    p = st.session_state.get("parser_used") or "pypdf"
    debug_html = f'<div class="p2g-debug-badge">[debug] {p.upper()}</div>'

    # ─ 预生成状态徽章（给用户感知下一段是否已准备好）─
    prefetch_html = ""
    next_chunk_idx = chunk_idx + 1
    if 0 <= next_chunk_idx < total:
        cache = dict(st.session_state.get("prefetch_cache") or {})
        future = st.session_state.get("prefetch_future")
        target_idx = st.session_state.get("prefetch_target_idx")
        if next_chunk_idx in cache:
            prefetch_html = '<div class="p2g-prefetch-badge ready">下一段已就绪</div>'
        elif future is not None and target_idx == next_chunk_idx:
            prefetch_html = '<div class="p2g-prefetch-badge loading">正在预生成下一段...</div>'

    # ─ 立绘 ─
    emotion_key = "char_normal"
    if item and item.get("emotion"):
        emotion_key = str(item["emotion"])
    char_path = ASSET_CHAR.get(emotion_key, ASSET_CHAR["char_normal"])
    char_uri  = _file_to_data_uri(char_path)
    char_html = f'<img class="p2g-char" src="{char_uri}" />' if char_uri else ""

    # ─ 内容区（对话框 / 名牌 / 章节标题卡）─
    t = (item or {}).get("type") or "dialogue"
    feedback = st.session_state.current_feedback or ""

    if t == "sub_head":
        title = (item or {}).get("title") or ""
        chapter_html = f"""
<div class="p2g-chapter-card">
  <div class="p2g-chapter-label">Chapter</div>
  <div class="p2g-chapter-title">{title}</div>
</div>"""
        nameplate_html = '<div class="p2g-nameplate">奈奈</div>'
        dialogue_html  = f"""
<div class="p2g-dialogue">
  <div class="p2g-text">～ {title} ～</div>
  <div class="p2g-next-arrow">▼</div>
</div>"""
    else:
        chapter_html = ""
        if not item:
            speaker, text = "奈奈", "还没有脚本内容……"
        elif t == "dialogue":
            speaker = str(item.get("speaker") or "奈奈")
            text    = str(item.get("text")    or "")
        elif t == "quiz":
            speaker = "奈奈"
            text    = str(item.get("question") or "来做个小测验喵！")
        elif t == "choice":
            speaker = "奈奈"
            text    = str(item.get("prompt") or "你选哪个？")
        else:
            speaker = "奈奈"
            text    = str(item.get("text") or json.dumps(item, ensure_ascii=False))

        # 反馈气泡 + 解析（quiz 区分对错颜色；choice 统一中性色）
        if feedback and t == "quiz":
            correct_fb = str((item or {}).get("feedback_correct") or "")
            fb_cls     = "correct" if feedback == correct_fb else "wrong"
            fb_html    = f'<div class="p2g-feedback {fb_cls}">{feedback}</div>'
            explanation = str((item or {}).get("explanation") or "").strip()
            if explanation:
                fb_html += (
                    f'<div class="p2g-explanation">'
                    f'<span class="p2g-explanation-label">📖 解析</span>'
                    f'{explanation}'
                    f'</div>'
                )
        elif feedback and t == "choice":
            fb_html = f'<div class="p2g-feedback">{feedback}</div>'
            explanation = str((item or {}).get("explanation") or "").strip()
            if explanation:
                fb_html += (
                    f'<div class="p2g-explanation">'
                    f'<span class="p2g-explanation-label">💭 奈奈的想法</span>'
                    f'{explanation}'
                    f'</div>'
                )
        elif feedback:
            fb_html = f'<div class="p2g-feedback">{feedback}</div>'
        else:
            fb_html = ""

        # ▼ 继续箭头：对话 & 答完题后显示
        show_arrow = t == "dialogue" or t == "sub_head" or bool(feedback)
        arrow_html = '<div class="p2g-next-arrow">▼</div>' if show_arrow else ""

        nameplate_html = f'<div class="p2g-nameplate">{speaker}</div>'
        dialogue_html  = f"""
<div class="p2g-dialogue">
  <div class="p2g-text">{text}</div>
  {fb_html}
  {arrow_html}
</div>"""

    st.markdown(
        "".join([
            progress_html, badge_html, debug_html, prefetch_html,
            char_html, chapter_html,
            nameplate_html, dialogue_html,
        ]),
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────
# 交互层（Streamlit 组件，必须在 HTML 流里）
# ──────────────────────────────────────────────

def render_interaction(item: Optional[Dict[str, Any]]) -> None:
    t = (item or {}).get("type") or "dialogue"
    is_qa = t in {"quiz", "choice"}

    # ── 顶部工具栏（退出按钮，极小）──
    if st.button("✕ 退出", key="btn_exit"):
        _reset_session()
        st.rerun()

    # ── 正文区 ──
    if is_qa and not st.session_state.answered:
        # 选项在视口中央，不会被底部对话框覆盖
        st.markdown("<div style='height:16vh'></div>", unsafe_allow_html=True)

        opts = (item or {}).get("options") or []
        if isinstance(opts, list) and opts:
            _, mid, _ = st.columns([1, 2.2, 1])
            with mid:
                st.markdown(
                    '<div class="p2g-options-label">— 请选择 —</div>',
                    unsafe_allow_html=True,
                )
                for i, opt in enumerate(opts):
                    label    = str(opt)
                    btn_key  = f"opt_{st.session_state.chunk_idx}_{st.session_state.script_idx}_{i}"
                    btn_text = f"{_ALPHA[i] if i < len(_ALPHA) else i+1}. {label}"
                    if st.button(btn_text, key=btn_key, use_container_width=True):
                        if t == "quiz":
                            correct = str((item or {}).get("correct_answer") or "").strip()
                            if label == correct:
                                st.session_state.current_feedback = str(
                                    (item or {}).get("feedback_correct") or "不错嘛。"
                                )
                            else:
                                st.session_state.current_feedback = str(
                                    (item or {}).get("feedback_wrong") or "不对喵！再想想。"
                                )
                        else:
                            st.session_state.current_feedback = f"你选择了：{label}"
                        st.session_state.answered = True
                        st.rerun()

    else:
        # 继续按钮改为 fixed 定位，避免被立绘挤出视口
        st.markdown("<div style='height:2vh'></div>", unsafe_allow_html=True)

        can_next = True
        if is_qa and not st.session_state.answered:
            can_next = False

        if st.button(
            "继续 ▶",
            key="btn_continue",
            disabled=not can_next,
            use_container_width=False,
        ):
            advance()
            st.rerun()

    # ── 点击对话框 = 点击"继续"按钮（JS 注入）──
    # 仅在可以继续时激活，避免未答题时误触发
    _can_click_dialogue = not (is_qa and not st.session_state.answered)
    if _can_click_dialogue:
        components.html(
            """
<script>
(function () {
  var par = window.parent;
  if (!par) return;

  // 防止 Streamlit 每次 rerender 重复绑定
  if (par._p2g_click_handler) {
    par.document.removeEventListener('click', par._p2g_click_handler, true);
  }

  par._p2g_click_handler = function (e) {
    var dlg = par.document.querySelector('.p2g-dialogue');
    if (!dlg) return;
    // 点击目标必须在对话框内部
    if (!dlg.contains(e.target)) return;

    // 找到"继续"按钮（非禁用状态）
    var btns = par.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      if (b.textContent.trim().startsWith('\u7ee7\u7eed') && !b.disabled) {
        b.click();
        return;
      }
    }
  };

  par.document.addEventListener('click', par._p2g_click_handler, true);
})();
</script>
            """,
            height=0,
        )


# ──────────────────────────────────────────────
# Streamlit 主流程
# ──────────────────────────────────────────────

def render_landing_page() -> None:
    inject_game_css(_file_to_data_uri(ASSET_BG))
    ensure_assets_notice()

    st.markdown(
        """
<style>
.p2g-landing-card {
  background: rgba(8,5,20,0.82);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(130,90,230,0.4);
  border-radius: 18px;
  padding: 2.2rem 2.3rem 1.6rem;
  max-width: 620px;
  margin: 11vh auto 0;
  box-shadow: 0 16px 60px rgba(0,0,0,0.35);
}
.p2g-landing-title {
  font-size: 2.2rem;
  font-weight: 800;
  letter-spacing: 3px;
  background: linear-gradient(135deg, #d6b0ff, #7b4fff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 0.35rem;
}
.p2g-landing-sub {
  color: rgba(212,194,255,0.78);
  font-size: 0.95rem;
  line-height: 1.8;
}
.p2g-landing-note {
  color: rgba(188,165,245,0.62);
  font-size: 0.82rem;
  margin-top: 0.6rem;
  letter-spacing: 0.5px;
}
.st-key-btn_start_game {
  max-width: 620px;
  margin: 0.9rem auto 0 !important;
}
.st-key-btn_start_game div[data-testid="stButton"] > button {
  height: 48px;
  font-weight: 800;
  text-align: center;
  letter-spacing: 1px;
}
</style>
<div class="p2g-landing-card">
  <div class="p2g-landing-title">Paper2Galgame</div>
  <div class="p2g-landing-sub">
    把论文变成可互动的 Galgame 伴读体验。上传 PDF 后，系统会解析内容，并生成对话、提问和选择题。
  </div>
  <div class="p2g-landing-note">
    建议先准备好 API Key（OpenAI / DeepSeek）和角色素材图片，再开始体验。
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("开始游戏", key="btn_start_game", use_container_width=True):
        st.session_state.state = "GUIDE"
        st.rerun()


def render_guide_page() -> None:
    inject_game_css(_file_to_data_uri(ASSET_BG))
    ensure_assets_notice()

    st.markdown(
        """
<style>
.p2g-guide-card {
  background: rgba(8,5,20,0.84);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(130,90,230,0.42);
  border-radius: 18px;
  padding: 2rem 2.2rem;
  max-width: 720px;
  margin: 8vh auto 0;
  box-shadow: 0 16px 60px rgba(0,0,0,0.35);
}
.p2g-guide-title {
  font-size: 1.8rem;
  font-weight: 800;
  color: #f1e4ff;
  letter-spacing: 2px;
  margin-bottom: 0.35rem;
}
.p2g-guide-sub {
  color: rgba(190,165,255,0.72);
  font-size: 0.9rem;
  margin-bottom: 1rem;
}
.p2g-guide-list {
  margin: 0;
  padding-left: 1.2rem;
  color: rgba(240,233,255,0.95);
  line-height: 1.95;
  font-size: 1rem;
}
.p2g-guide-list li { margin-bottom: 0.35rem; }
.p2g-guide-tip {
  margin-top: 0.9rem;
  color: rgba(205,186,255,0.78);
  font-size: 0.9rem;
  line-height: 1.75;
  border-top: 1px dashed rgba(150,120,230,0.25);
  padding-top: 0.8rem;
}
.st-key-btn_go_setup, .st-key-btn_back_landing {
  margin-top: 0.5rem !important;
}
.st-key-btn_go_setup div[data-testid="stButton"] > button,
.st-key-btn_back_landing div[data-testid="stButton"] > button {
  text-align: center;
  font-weight: 700;
}
</style>
<div class="p2g-guide-card">
  <div class="p2g-guide-title">操作说明</div>
  <div class="p2g-guide-sub">开始前先看一遍，体验会顺很多。</div>
  <ol class="p2g-guide-list">
    <li>上传论文 PDF（优先选择可复制文字的 PDF；扫描版建议开启 MinerU OCR）。</li>
    <li>等待系统解析并生成剧情脚本，系统会自动切分论文内容并生成互动问题。</li>
    <li>按照游戏提示阅读内容、回答题目或做选择，再点击“继续”推进剧情。</li>
    <li>如果解析失败或内容为空，请检查 API Key、PDF 格式，或切换 OCR 选项后重试。</li>
  </ol>
  <div class="p2g-guide-tip">
    基本流程：<b>1. 上传论文，2. 按照游戏提示回答题目</b>。<br/>
    你可以随时点击“退出”返回首页重新开始。
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        if st.button("前往上传论文", key="btn_go_setup", use_container_width=True):
            st.session_state.state = "SETUP"
            st.rerun()
        if st.button("返回首页", key="btn_back_landing", use_container_width=True):
            st.session_state.state = "LANDING"
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Paper2Galgame",
        page_icon="📖",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_state()

    if st.session_state.state == "LANDING":
        render_landing_page()

    if st.session_state.state == "GUIDE":
        render_guide_page()

    # ════════════════════════════
    # STATE: SETUP
    # ════════════════════════════
    if st.session_state.state == "SETUP":
        # 封面注入背景（无图时只用黑底）
        inject_game_css(_file_to_data_uri(ASSET_BG))
        ensure_assets_notice()

        st.markdown(
            """
<style>
.setup-card {
  background: rgba(8,5,20,0.82); backdrop-filter: blur(18px);
  border: 1px solid rgba(130,90,230,0.4); border-radius: 18px;
  padding: 2.2rem 2.5rem; max-width: 540px; margin: 8vh auto 0;
}
.setup-title {
  font-size: 2.1rem; font-weight: 800; letter-spacing: 3px;
  background: linear-gradient(135deg, #c084ff, #7b4fff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 0.2rem;
}
.setup-subtitle {
  font-size: 0.85rem; color: rgba(190,165,255,0.65);
  letter-spacing: 1.5px; margin-bottom: 1.6rem;
}
</style>
<div class="setup-card">
  <div class="setup-title">Paper2Galgame</div>
  <div class="setup-subtitle">把论文变成猫娘陪读视觉小说</div>
</div>
            """,
            unsafe_allow_html=True,
        )

        with st.container():
            st.markdown("<div style='max-width:540px; margin:0 auto; padding:0 1rem'>", unsafe_allow_html=True)

            if st.button("返回说明页", key="btn_back_guide", use_container_width=True):
                st.session_state.state = "GUIDE"
                st.rerun()

            uploaded = st.file_uploader("选择一篇 PDF 论文", type=["pdf"])

            mineru_ready = token_available()
            default_use_mineru = bool(st.session_state.use_mineru) and mineru_ready
            st.session_state.use_mineru = st.checkbox(
                "🔬 使用 MinerU OCR 解析（按章节，需要 MINERU_API_TOKEN）",
                value=default_use_mineru,
                disabled=not mineru_ready,
            )
            if not mineru_ready:
                st.caption("💡 设置 MINERU_API_TOKEN 可启用按章节解析。")

            st.markdown("</div>", unsafe_allow_html=True)

        if uploaded is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                f.write(uploaded.read())
                tmp_path = Path(f.name)
            st.session_state._tmp_pdf_path = str(tmp_path)  # type: ignore[attr-defined]
            st.session_state.state = "PROCESSING"
            st.rerun()

    # ════════════════════════════
    # STATE: PROCESSING
    # ════════════════════════════
    if st.session_state.state == "PROCESSING":
        inject_game_css(_file_to_data_uri(ASSET_BG))

        st.markdown(
            """
<div style="position:fixed;left:50%;top:45%;transform:translate(-50%,-50%);
  background:rgba(8,5,20,0.85);backdrop-filter:blur(14px);
  border:1px solid rgba(130,90,230,0.4);border-radius:16px;
  padding:2rem 3rem;text-align:center;z-index:60;min-width:320px">
  <div style="font-size:1.5rem;margin-bottom:0.6rem">⚙️</div>
  <div style="color:rgba(220,200,255,0.9);font-size:1rem;letter-spacing:1px">
    正在生成剧本……
  </div>
  <div style="color:rgba(175,150,255,0.55);font-size:0.78rem;margin-top:0.4rem">
    别急喵！我才不是为你努力的！
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

        if not st.session_state.chunks:
            pdf_path = Path(getattr(st.session_state, "_tmp_pdf_path", ""))
            if not pdf_path.exists():
                st.error("临时 PDF 文件丢失了，请回到封面重新上传。")
                if st.button("回到封面"):
                    _reset_session()
                    st.rerun()
                return

            with st.spinner("解析 PDF…"):
                try:
                    chunks = load_and_chunk_pdf(
                        pdf_path,
                        use_mineru=bool(st.session_state.use_mineru),
                    )
                except Exception as e:
                    st.error(f"PDF 解析失败：{e}")
                    if st.button("回到封面"):
                        _reset_session()
                        st.rerun()
                    return

            if not chunks:
                st.error("没有解析到任何文本。可能是扫描版 PDF，请启用 MinerU OCR。")
                if st.button("回到封面"):
                    _reset_session()
                    st.rerun()
                return

            st.session_state.chunks    = chunks
            st.session_state.chunk_idx = 0
            parser_used = chunks[0].parser if chunks else "pypdf"
            st.session_state.parser_used = parser_used
            _clear_prefetch_buffer(bump_run_token=True)

        idx = int(st.session_state.chunk_idx)
        idx = max(0, min(idx, len(st.session_state.chunks) - 1))
        st.session_state.chunk_idx = idx

        with st.spinner(f"生成第 {idx + 1} 段剧本…"):
            try:
                prefetched = _take_prefetched_script(idx, wait_if_running=True)
                if prefetched is not None:
                    _apply_script_items(prefetched)
                else:
                    load_script_for_chunk(st.session_state.chunks, idx)
            except Exception as e:
                st.error(str(e))
                st.info("请检查 .env 中的 API Key 配置。")
                if st.button("回到封面"):
                    _reset_session()
                    st.rerun()
                return

        _ensure_next_chunk_prefetch(st.session_state.chunks, idx)
        st.session_state.state = "GAME_LOOP"
        st.rerun()

    # ════════════════════════════
    # STATE: GAME_LOOP
    # ════════════════════════════
    if st.session_state.state == "GAME_LOOP":
        if not st.session_state.generator_ready:
            st.session_state.state = "PROCESSING"
            st.rerun()

        _collect_prefetch_if_ready()
        if st.session_state.chunks:
            _ensure_next_chunk_prefetch(st.session_state.chunks, int(st.session_state.chunk_idx))

        item = get_current_item()
        render_game_screen(item)
        render_interaction(item)


if __name__ == "__main__":
    main()
