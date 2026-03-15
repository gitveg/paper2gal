from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

from utils.pdf_loader import load_and_chunk_pdf, PdfChunk
from utils.mineru_parser import token_available
from utils.reading_mode import apply_reading_mode
from utils.script_engine import ScriptGenerator

# ──────────────────────────────────────────────
# 本地资源路径（必须手动放入 assets/ 目录）
# ──────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"

ASSET_BG = ASSETS_DIR / "bg_classroom.png"

# ──────────────────────────────────────────────
# 角色配置：支持多角色
# 每个角色一个文件夹，包含不同表情的图片
# 角色文件夹结构：
#   assets/角色ID/
#     ├── normal.png  (普通表情)
#     ├── happy.png   (开心)
#     ├── angry.png   (生气)
#     └── shy.png    (害羞)
# ──────────────────────────────────────────────
CHARACTERS = {
    "nana": {
        "name": "奈奈",
        "description": "傲娇的二次元猫娘",
        "folder": "nana",
    },
    "lina": {
        "name": "玲娜贝儿",
        "description": "机智的粉色小狐狸",
        "folder": "lina",
    },
}

<<<<<<< HEAD
def _get_character_folder(character_id: str) -> Path:
    """获取角色资源文件夹路径"""
    folder = CHARACTERS.get(character_id, CHARACTERS["nana"])["folder"]
    return ASSETS_DIR / folder

def _load_character_assets(character_id: str) -> dict:
    """加载角色的所有表情图片路径"""
    char_folder = _get_character_folder(character_id)
    return {
        "char_normal": char_folder / "char_normal.png",
        "char_happy":  char_folder / "char_happy.png",
        "char_angry":  char_folder / "char_angry.png",
        "char_shy":    char_folder / "char_shy.png",
    }

def _get_character_name(character_id: str) -> str:
    """获取角色显示名称"""
    return CHARACTERS.get(character_id, CHARACTERS["nana"])["name"]

# 默认角色
DEFAULT_CHARACTER = "nana"
=======
# 演示文档（内置，无需用户上传）
DEMO_PDF = ROOT_DIR / "papers" / "ReAct.pdf"
DEMO_PDF_TITLE = "ReAct: Synergizing Reasoning and Acting in Language Models"
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
READING_MODE_OPTIONS = ["fast", "detailed"]
READING_MODE_LABELS = {
    "fast": "极速阅读",
    "detailed": "标准阅读（详细）",
}
COMMON_SECTION_ORDER = [
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiment",
    "conclusion",
    "appendix",
]
COMMON_SECTION_LABELS = {
    "abstract": "Abstract / 摘要",
    "introduction": "Introduction / 引言",
    "related_work": "Related Work / 相关工作",
    "method": "Method / 方法",
    "experiment": "Experiment / 实验与结果",
    "conclusion": "Conclusion / 结论",
    "appendix": "Appendix / 附录",
}
COMMON_SECTION_KEYWORDS = {
    "abstract": ["abstract", "摘要"],
    "introduction": ["introduction", "intro", "引言", "背景"],
    "related_work": ["related work", "related", "literature", "相关工作"],
    "method": ["method", "methods", "approach", "framework", "methodology", "方法", "模型", "算法"],
    "experiment": ["experiment", "experiments", "evaluation", "result", "results", "实验", "评估", "结果"],
    "conclusion": ["conclusion", "conclusions", "future work", "总结", "结论"],
    "appendix": ["appendix", "supplementary", "supplement", "附录"],
}


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
.p2g-mode-badge {{
  position: fixed; top: 28px; right: 14px;
  font-size: 0.68rem; color: rgba(210, 188, 255, 0.78);
  z-index: 150; pointer-events: none;
}}
.p2g-prefetch-badge {{
  position: fixed;
  top: 64px;
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
/* 以高度为主约束：永远不超出对话框上方可用空间；宽度自适应纵横比 */
.p2g-char {{
  position: fixed;
  right: 1vw; bottom: 180px;
  height: min(calc(100vh - 210px), 70vh, 680px);
  width: auto;
  max-width: min(36vw, 500px);
  z-index: 40; pointer-events: none; user-select: none;
  filter: drop-shadow(0 28px 42px rgba(0,0,0,0.65));
  transition: opacity 0.35s ease;
}}

/* ── 说话人名牌（紧贴对话框顶部，随对话框高度自适应）── */
.p2g-nameplate {{
  position: fixed; left: 4vw;
  bottom: calc(var(--p2g-dlg-h, 172px) + 4px);
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
  /* 右 padding：立绘改为高度控制后，按预期渲染宽度留白 */
  padding: 1.1rem calc(min(28vw, 400px) + 1vw + 2rem) 1.3rem 4.5vw;
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

/* ── 论文图片展示卡（show_image 专用，居中弹出）── */
.p2g-figure-card {{
  position: fixed; left: 50%; top: 38%;
  transform: translate(-50%, -50%);
  background: rgba(7,5,18,0.92); backdrop-filter: blur(18px);
  border: 1px solid rgba(140,95,255,0.55); border-radius: 16px;
  padding: 1.2rem 1.4rem 1rem; text-align: center; z-index: 46;
  box-shadow: 0 0 60px rgba(100,55,200,0.35);
  max-width: min(640px, 78vw);
}}
/* 图片与对话同屏：缩小卡片，上移，给底部对话框留空间 */
.p2g-figure-card.with-dialogue {{
  top: 31%;
  max-width: min(520px, 68vw);
  padding: 0.8rem 1rem 0.7rem;
}}
.p2g-figure-card.with-dialogue .p2g-figure-img {{
  max-height: 34vh;
}}
.p2g-figure-img {{
  max-width: 100%; max-height: 46vh;
  border-radius: 8px; object-fit: contain;
  box-shadow: 0 4px 24px rgba(0,0,0,0.6);
}}
.p2g-figure-label {{
  font-size: 0.68rem; letter-spacing: 3px; text-transform: uppercase;
  color: rgba(175,145,255,0.55); margin-bottom: 0.4rem;
}}
.p2g-figure-caption {{
  margin-top: 0.55rem;
  color: rgba(215,198,255,0.85);
  font-size: 0.84rem; line-height: 1.55;
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
  right: clamp(230px, 31vw, 430px);
  bottom: calc(var(--p2g-dlg-h, 172px) + 14px); /* 随对话框高度浮动 */
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

/* ── 中等屏幕适配（≤900px）── */
@media (max-width: 900px) {{
  .p2g-char {{
    /* 高度约束在小屏同样生效，只需收窄 max-width 防止过宽 */
    max-width: min(34vw, 320px);
    right: 0.5rem;
    bottom: 172px;
  }}
  .p2g-dialogue {{
    padding-right: 40%;
  }}
  .p2g-next-row {{
    right: clamp(160px, 28vw, 280px);
    width: min(180px, 36vw);
  }}
  .st-key-btn_continue {{
    right: clamp(170px, 28vw, 300px);
  }}
}}
/* ── 手机端适配（≤640px）── */
@media (max-width: 640px) {{
  .p2g-char {{
    /* 手机上立绘缩小，避免遮挡主要内容 */
    height: min(calc(100vh - 190px), 55vh, 380px);
    max-width: min(40vw, 220px);
    right: 0.35rem;
    bottom: 160px;
    opacity: 0.92;
  }}
  .p2g-nameplate {{
    /* 名牌继续跟随 CSS 变量，此处只调字号 */
    font-size: 0.82rem;
    padding: 0.2rem 1.1rem 0.2rem 0.75rem;
  }}
  .p2g-dialogue {{
    min-height: 150px;
    padding: 0.9rem 38% 1rem 4vw;
  }}
  .p2g-util-row {{
    top: 8px;
    right: 10px;
    width: 84px;
  }}
  .p2g-next-row {{
    right: 100px;
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
    right: 100px;
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
    st.session_state.setdefault("reading_mode",    "detailed")
    st.session_state.setdefault("enable_section_pick", False)
    st.session_state.setdefault("raw_chunks",      [])
    st.session_state.setdefault("available_sections", [])
    st.session_state.setdefault("selected_sections", None)
    st.session_state.setdefault("section_label_to_key", {})
    st.session_state.setdefault("section_filter_applied", False)
    st.session_state.setdefault("parser_used",     "pypdf")
    st.session_state.setdefault("prefetch_cache",  {})
    st.session_state.setdefault("prefetch_future", None)
    st.session_state.setdefault("prefetch_target_idx", None)
    st.session_state.setdefault("prefetch_task_run_token", None)
    st.session_state.setdefault("use_demo_pdf",    False)
    st.session_state.setdefault("script_run_token", 0)
    st.session_state.setdefault("prefetch_executor", None)
    st.session_state.setdefault("paper_image_map",   {})


def ensure_assets_notice() -> None:
    missing = []
    if not ASSET_BG.exists():
        missing.append(str(ASSET_BG))
    if missing:
        st.warning(
            "检测到以下本地图片资源缺失，请手动放入（代码只读本地路径，不使用网图）：\n\n- "
            + "\n- ".join(missing)
        )


def _normalize_for_section(text: str) -> str:
    s = str(text or "").lower()
    s = re.sub(r"[#`$^*_+~]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _infer_common_section_key(title: str, body: str) -> Optional[str]:
    # Prefer title match; fallback to body prefix to handle OCR-noisy headings.
    title_norm = _normalize_for_section(title)
    body_norm = _normalize_for_section(body[:1200])
    for key in COMMON_SECTION_ORDER:
        kws = COMMON_SECTION_KEYWORDS[key]
        if any(kw in title_norm for kw in kws):
            return key
    for key in COMMON_SECTION_ORDER:
        kws = COMMON_SECTION_KEYWORDS[key]
        if any(kw in body_norm for kw in kws):
            return key
    return None


def _build_common_section_mapping(chunks: List[PdfChunk]) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for i, ch in enumerate(chunks):
        key = _infer_common_section_key(
            str(getattr(ch, "section_title", "") or ""),
            str(getattr(ch, "text", "") or ""),
        )
        if key is not None:
            mapping[i] = key
    return mapping


def _lookup_image_path(figure_id: str) -> Optional[str]:
    """
    在 session_state.paper_image_map 中查找图片文件路径。
    匹配策略（依序尝试）：精确匹配 → 子串匹配 → 共同数字匹配。
    """
    paper_image_map: Dict[str, str] = st.session_state.get("paper_image_map") or {}
    if not figure_id or not paper_image_map:
        return None
    fid = figure_id.strip()
    fid_lower = fid.lower()

    # 1. 精确匹配
    for k, v in paper_image_map.items():
        if k.lower() == fid_lower:
            return v
    # 2. 子串匹配（"Figure 1" ∈ "Figure 1: Architecture"）
    for k, v in paper_image_map.items():
        if fid_lower in k.lower() or k.lower() in fid_lower:
            return v
    # 3. 数字匹配（"Fig. 1" 与 "Figure 1" 共享数字 "1"）
    fid_nums = re.findall(r"\d+", fid)
    if fid_nums:
        for k, v in paper_image_map.items():
            if re.findall(r"\d+", k) == fid_nums:
                return v
    return None


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


def _merge_show_image_with_dialogue(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    把 show_image + 紧随的 dialogue 合并为带 figure_id 的 dialogue，
    使图片和讲解文字同屏显示，不再是分两步的断层体验。
    同时把孤立的 show_image（无紧随 dialogue）转成 dialogue 形式。
    """
    result: List[Dict[str, Any]] = []
    i = 0
    while i < len(items):
        item = items[i]
        if item.get("type") == "show_image":
            figure_id = item.get("figure_id") or ""
            caption   = item.get("caption") or ""
            # 若下一条是 dialogue，合并
            if i + 1 < len(items) and items[i + 1].get("type") == "dialogue":
                next_item = dict(items[i + 1])
                if not next_item.get("figure_id"):
                    next_item["figure_id"] = figure_id
                result.append(next_item)
                i += 2
                continue
            # 孤立 show_image → 转成 dialogue（使用 caption 或兜底文案）
            text = caption if caption else (
                f"来看看这张图喵～（{figure_id}）" if figure_id else "来看看这张图喵～"
            )
            result.append({
                "type": "dialogue",
                "speaker": "奈奈",
                "text": text,
                "emotion": "char_normal",
                "figure_id": figure_id,
            })
            i += 1
        else:
            result.append(item)
            i += 1
    return result


def _apply_script_items(script: List[Dict[str, Any]]) -> None:
    merged = _merge_show_image_with_dialogue(script)
    st.session_state.script_items     = merged
    st.session_state.script_idx       = 0
    st.session_state.current_feedback = None
    st.session_state.answered         = False
    st.session_state.generator_ready  = True


def _generate_script_for_chunk(chunks: List[PdfChunk], chunk_idx: int) -> List[Dict[str, Any]]:
    gen = ScriptGenerator()
    chunk = chunks[chunk_idx]
<<<<<<< HEAD
    # 获取当前角色名称
    character_name = _get_character_name(st.session_state.get("selected_character", DEFAULT_CHARACTER))
=======
    image_map = dict(getattr(chunk, "image_map", ())) or None
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
    return gen.generate_script(
        chunk.text,
        chunk_index=chunk.index,
        section_title=getattr(chunk, "section_title", "") or None,
<<<<<<< HEAD
        character_name=character_name,
=======
        image_map=image_map,
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
    )


def _generate_script_payload(
    chunk_text: str,
    *,
    chunk_index: int,
    section_title: Optional[str],
<<<<<<< HEAD
    character_name: str,
=======
    image_map: Optional[Dict[str, str]] = None,
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
) -> List[Dict[str, Any]]:
    gen = ScriptGenerator()
    return gen.generate_script(
        chunk_text,
        chunk_index=chunk_index,
        section_title=section_title,
<<<<<<< HEAD
        character_name=character_name,
=======
        image_map=image_map,
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
    )


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
        # 验证预取脚本的角色是否与当前选择一致
        if script:
            # 获取当前"应该"显示的名称
            current_character_name = _get_character_name(st.session_state.get("selected_character", DEFAULT_CHARACTER))
            
            # 不要直接对比 speaker，因为 AI 可能会写错
            # 我们在这里强制把预取脚本里的所有 speaker 修正为当前选择的角色
            for item in script:
                if item.get("type") == "dialogue":
                    item["speaker"] = current_character_name
        
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

    # 验证预取脚本的角色是否与当前选择一致
    if script:
        # 获取当前"应该"显示的名称
        current_character_name = _get_character_name(st.session_state.get("selected_character", DEFAULT_CHARACTER))
        
        # 不要直接对比 speaker，因为 AI 可能会写错
        # 我们在这里强制把预取脚本里的所有 speaker 修正为当前选择的角色
        for item in script:
            if item.get("type") == "dialogue":
                item["speaker"] = current_character_name

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
<<<<<<< HEAD
    # 获取当前角色名称，确保预生成也使用正确的角色
    character_name = _get_character_name(st.session_state.get("selected_character", DEFAULT_CHARACTER))
=======
    image_map = dict(getattr(chunk, "image_map", ())) or None
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
    future = _get_prefetch_executor().submit(
        _generate_script_payload,
        chunk.text,
        chunk_index=chunk.index,
        section_title=getattr(chunk, "section_title", "") or None,
<<<<<<< HEAD
        character_name=character_name,  # 显式传递角色名称
=======
        image_map=image_map,
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
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
    st.session_state.raw_chunks       = []
    st.session_state.available_sections = []
    st.session_state.selected_sections = None
    st.session_state.section_label_to_key = {}
    st.session_state.section_filter_applied = False
    st.session_state.chunk_idx        = 0
    st.session_state.script_items     = []
    st.session_state.script_idx       = 0
    st.session_state.current_feedback = None
    st.session_state.answered         = False
    st.session_state.generator_ready  = False
    _clear_prefetch_buffer(bump_run_token=True)
    st.session_state.paper_image_map  = {}


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
            _reset_session()
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
    img_count = len(st.session_state.get("paper_image_map") or {})
    img_str = f" | 🖼 {img_count}张图" if img_count else ""
    debug_html = f'<div class="p2g-debug-badge">[debug] {p.upper()}{img_str}</div>'
    mode = str(st.session_state.get("reading_mode") or "detailed").strip().lower()
    mode_label = READING_MODE_LABELS.get(mode, "标准阅读（详细）")
    mode_html = f'<div class="p2g-mode-badge">模式: {mode_label}</div>'

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
    # 获取当前选择的角色
    current_character = st.session_state.get("selected_character", DEFAULT_CHARACTER)
    # 使用新角色的图片加载方式
    char_assets = _load_character_assets(current_character)
    
    # 调试信息 - 显示图片路径
    #st.caption(f"DEBUG: current_character={current_character}, char_assets={char_assets}")
    
    # 兼容旧的 emotion key（如 char_normal -> normal）
    emotion_key = "char_normal"
    if item and item.get("emotion"):
        emotion_key = str(item["emotion"])
    # 将 char_xxx 转换为 xxx
    emotion_file_key = emotion_key.replace("char_", "") if emotion_key.startswith("char_") else emotion_key
    char_path = char_assets.get(emotion_key) or char_assets.get(f"char_{emotion_file_key}")
    if not char_path:
        # 回退到默认
        char_path = char_assets.get("char_normal")
    
    # 调试信息 - 显示实际使用的图片路径
    #st.caption(f"DEBUG: emotion_key={emotion_key}, char_path={char_path}, exists={char_path.exists() if char_path else False}")
    
    char_uri  = _file_to_data_uri(char_path) if char_path else None
    char_html = f'<img class="p2g-char" src="{char_uri}" />' if char_uri else ""

    # 获取当前角色名称
    current_character_name = _get_character_name(current_character)
    #st.caption(f"DEBUG: current_character_name={current_character_name}")

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
        nameplate_html = f'<div class="p2g-nameplate">{current_character_name}</div>'
        dialogue_html  = f"""
<div class="p2g-dialogue">
  <div class="p2g-text">～ {title} ～</div>
  <div class="p2g-next-arrow">▼</div>
</div>"""

    else:
        # ── 对话携带 figure_id 时在上方渲染图片卡 ──
        chapter_html = ""
        if not item:
            speaker, text = current_character_name, "还没有脚本内容……"
        elif t == "dialogue":
<<<<<<< HEAD
            raw_speaker = str(item.get("speaker") or "")
            # 关键修正：如果原定说话人是“奈奈”或为空，强制修正为当前选中的角色名
            if raw_speaker == "奈奈" or raw_speaker == "" or raw_speaker != current_character_name:
                speaker = current_character_name
            else:
                speaker = raw_speaker
            text = str(item.get("text") or "")
=======
            speaker   = str(item.get("speaker") or "奈奈")
            text      = str(item.get("text")    or "")
            figure_id = str(item.get("figure_id") or "")
            if figure_id:
                img_path_str = _lookup_image_path(figure_id)
                if img_path_str:
                    img_uri = _file_to_data_uri(Path(img_path_str))
                    chapter_html = f"""
<div class="p2g-figure-card with-dialogue">
  <div class="p2g-figure-label">论文插图</div>
  <img class="p2g-figure-img" src="{img_uri}" alt="{figure_id}" />
</div>""" if img_uri else ""
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
        elif t == "quiz":
            speaker = current_character_name
            text    = str(item.get("question") or f"来做个小测验{current_character_name}！")
        elif t == "choice":
            speaker = current_character_name
            text    = str(item.get("prompt") or "你选哪个？")
        else:
            speaker = current_character_name
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
                    f'<span class="p2g-explanation-label">💭 {current_character_name}的想法</span>'
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
            progress_html, badge_html, debug_html, mode_html, prefetch_html,
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

    # ── JS 注入：① 对话框高度 → CSS 变量  ② 点击对话框推进 ──
    _can_click_dialogue = not (is_qa and not st.session_state.answered)
    components.html(
        f"""
<script>
(function () {{
  var par = window.parent;
  if (!par) return;
  var doc = par.document;

  // ─── ① 实时测量对话框高度，写入 CSS 变量 --p2g-dlg-h ───
  // 名牌和"继续"按钮的 bottom 都依赖这个变量，确保始终在对话框上方
  function updateDlgHeight() {{
    var dlg = doc.querySelector('.p2g-dialogue');
    if (dlg) {{
      var h = Math.ceil(dlg.getBoundingClientRect().height);
      if (h > 0) doc.documentElement.style.setProperty('--p2g-dlg-h', h + 'px');
    }}
  }}
  updateDlgHeight();
  setTimeout(updateDlgHeight, 150);
  setTimeout(updateDlgHeight, 600);

  // 窗口大小改变时重算（响应竖屏/横屏切换）
  if (!par._p2g_resize_bound) {{
    par.addEventListener('resize', updateDlgHeight, {{passive: true}});
    par._p2g_resize_bound = true;
  }}

  // MutationObserver：对话框内容变化时（如解析展开）立即重算
  if (par._p2g_dlg_observer) par._p2g_dlg_observer.disconnect();
  var dlgEl = doc.querySelector('.p2g-dialogue');
  if (dlgEl) {{
    par._p2g_dlg_observer = new MutationObserver(function() {{
      updateDlgHeight();
    }});
    par._p2g_dlg_observer.observe(dlgEl, {{childList: true, subtree: true}});
  }}

  // ─── ② 点击对话框 = 点击"继续"按钮 ───
  if (par._p2g_click_handler) {{
    doc.removeEventListener('click', par._p2g_click_handler, true);
  }}

  var canClick = {'true' if _can_click_dialogue else 'false'};
  par._p2g_click_handler = function (e) {{
    if (!canClick) return;
    var dlg = doc.querySelector('.p2g-dialogue');
    if (!dlg || !dlg.contains(e.target)) return;
    var btns = doc.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {{
      var b = btns[i];
      if (b.textContent.trim().startsWith('\u7ee7\u7eed') && !b.disabled) {{
        b.click();
        return;
      }}
    }}
  }};
  doc.addEventListener('click', par._p2g_click_handler, true);
}})();
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
.st-key-btn_start_game, .st-key-btn_demo_play {
  max-width: 620px;
  margin: 0.6rem auto 0 !important;
}
.st-key-btn_start_game div[data-testid="stButton"] > button,
.st-key-btn_demo_play div[data-testid="stButton"] > button {
  height: 48px;
  font-weight: 800;
  text-align: center;
  letter-spacing: 1px;
}
.p2g-demo-badge {
  display: inline-block;
  margin-top: 1rem;
  padding: 0.45rem 1rem;
  background: rgba(120,80,220,0.18);
  border: 1px solid rgba(160,110,255,0.35);
  border-radius: 30px;
  font-size: 0.82rem;
  color: rgba(210,185,255,0.82);
  letter-spacing: 0.5px;
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
  <div class="p2g-demo-badge">内置演示文档：ReAct — 推理与行动协同的语言模型</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    _, mid_l, mid_r, _ = st.columns([0.8, 1, 1, 0.8])
    with mid_l:
        if st.button("上传论文开始", key="btn_start_game", use_container_width=True):
            st.session_state.use_demo_pdf = False
            st.session_state.state = "GUIDE"
            st.rerun()
    with mid_r:
        demo_disabled = not DEMO_PDF.exists()
        if st.button(
            "演示体验 (ReAct)",
            key="btn_demo_play",
            use_container_width=True,
            disabled=demo_disabled,
            help=None if not demo_disabled else "找不到 papers/ReAct.pdf，请确认文件存在。",
        ):
            st.session_state.use_demo_pdf = True
            st.session_state.state = "SETUP"
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
    # 强制同步一次，确保无论在哪个页面，selected_character 永远等于 persistent_char
    if "persistent_char" in st.session_state:
        st.session_state.selected_character = st.session_state.persistent_char
    # 确保角色选择始终存在，并验证其值在CHARACTERS中有效
    elif "selected_character" not in st.session_state:
        st.session_state.selected_character = DEFAULT_CHARACTER
    elif st.session_state.selected_character not in CHARACTERS:
        st.session_state.selected_character = DEFAULT_CHARACTER

    if st.session_state.state == "LANDING":
        render_landing_page()

    elif st.session_state.state == "GUIDE":
        render_guide_page()

    # ════════════════════════════
    # STATE: SETUP
    # ════════════════════════════
    elif st.session_state.state == "SETUP":
        # 调试信息
        #st.write(f"DEBUG SETUP: selected_character = {st.session_state.get('selected_character')}")
        
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

            # ── 角色选择 ──
            # 确保 session_state 中有一个持久化的 key
            if "persistent_char" not in st.session_state:
                st.session_state.persistent_char = DEFAULT_CHARACTER
            
            character_options = list(CHARACTERS.keys())
            character_labels = {k: f"{v['name']} - {v['description']}" for k, v in CHARACTERS.items()}

            # 找到当前持久化角色在选项中的索引，确保 UI 反显正确
            try:
                current_idx = character_options.index(st.session_state.persistent_char)
            except ValueError:
                current_idx = 0

            # 渲染 selectbox，使用 key="char_selector" 避免冲突
            selected_character = st.selectbox(
                "🎭 选择陪你阅读的角色",
                options=character_options,
                index=current_idx,
                key="char_selector", 
                format_func=lambda x: character_labels.get(x, x),
                help="选择不同的角色陪你阅读论文",
            )

            # 实时同步到持久化变量和全局使用的 selected_character
            st.session_state.persistent_char = selected_character
            st.session_state.selected_character = selected_character

            current_debug = st.session_state.get("selected_character", "NOT_SET")
            #st.caption(f"DEBUG: selected_character = {current_debug}")

            # 检查角色资源是否存在
            char_assets = _load_character_assets(selected_character)
            missing_char_imgs = []
            for emotion, path in char_assets.items():
                if not path.exists():
                    missing_char_imgs.append(str(path))
            if missing_char_imgs:
                st.warning(
                    f"角色「{_get_character_name(selected_character)}」的图片缺失，将使用默认角色。\n"
                    + "缺失文件：" + ", ".join([str(p) for p in missing_char_imgs])
                )

            # ── 阅读模式选择 ──
            if str(st.session_state.get("reading_mode") or "").strip().lower() not in READING_MODE_OPTIONS:
                st.session_state.reading_mode = "detailed"
            st.selectbox(
                "阅读模式",
                options=READING_MODE_OPTIONS,
                key="reading_mode",
                format_func=lambda x: READING_MODE_LABELS.get(str(x), str(x)),
                help="极速：只读摘要/方法/实验；标准：完整阅读。",
            )

            # 初始化 enable_section_pick（如果还没有值）
            st.session_state.setdefault("enable_section_pick", False)

            st.checkbox(
                "手动勾选阅读章节（需 MinerU 解析）",
                key="enable_section_pick",
            )

            # 初始化 use_mineru（如果还没有值）
            st.session_state.setdefault("use_mineru", True)

            mineru_ready = token_available()
            # 如果启用了章节勾选，强制使用 MinerU
            use_mineru_for_checkbox = mineru_ready and (
                st.session_state.enable_section_pick or st.session_state.use_mineru
            )
            st.checkbox(
                "🔬 使用 MinerU OCR 解析（按章节，需要 MINERU_API_TOKEN）",
                key="use_mineru",
                value=use_mineru_for_checkbox,
                disabled=(not mineru_ready) or bool(st.session_state.enable_section_pick),
            )
            if not mineru_ready:
                st.caption("💡 设置 MINERU_API_TOKEN 可启用按章节解析。")
            elif st.session_state.enable_section_pick:
                st.caption("💡 已启用章节勾选，MinerU OCR 自动开启。")

            use_demo: bool = bool(st.session_state.get("use_demo_pdf"))

            if use_demo:
                # ── 演示文档模式：显示信息卡 + 直接开始按钮 ──
                st.markdown(
                    f"""
<div style="
  margin-top:0.8rem; padding:0.9rem 1.1rem;
  background:rgba(100,60,200,0.15); border-radius:12px;
  border:1px solid rgba(150,110,255,0.35);
">
  <div style="font-size:0.72rem;letter-spacing:2px;color:rgba(180,150,255,0.6);
    text-transform:uppercase;margin-bottom:0.25rem;">演示文档</div>
  <div style="color:#e8d8ff;font-weight:700;font-size:1rem;line-height:1.5;">
    {DEMO_PDF_TITLE}
  </div>
  <div style="color:rgba(200,175,255,0.65);font-size:0.82rem;margin-top:0.2rem;">
    papers/ReAct.pdf &nbsp;·&nbsp; 无需上传，直接开始
  </div>
</div>""",
                    unsafe_allow_html=True,
                )
                if st.button("开始演示体验", key="btn_start_demo", use_container_width=True):
                    st.session_state._tmp_pdf_path = str(DEMO_PDF)  # type: ignore[attr-defined]
                    st.session_state.chunks = []
                    st.session_state.raw_chunks = []
                    st.session_state.available_sections = []
                    st.session_state.selected_sections = None
                    st.session_state.section_label_to_key = {}
                    st.session_state.section_filter_applied = False
                    st.session_state.state = "PROCESSING"
                    st.rerun()
            else:
                # ── 普通上传模式 ──
                uploaded = st.file_uploader("选择一篇 PDF 论文", type=["pdf"])
                if uploaded is not None:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                        f.write(uploaded.read())
                        tmp_path = Path(f.name)
                    st.session_state._tmp_pdf_path = str(tmp_path)  # type: ignore[attr-defined]
                    st.session_state.chunks = []
                    st.session_state.raw_chunks = []
                    st.session_state.available_sections = []
                    st.session_state.selected_sections = None
                    st.session_state.section_label_to_key = {}
                    st.session_state.section_filter_applied = False
                    st.session_state.state = "PROCESSING"
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

<<<<<<< HEAD
        if uploaded is not None:      
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                f.write(uploaded.read())
                tmp_path = Path(f.name)
            st.session_state._tmp_pdf_path = str(tmp_path)  # type: ignore[attr-defined]
            st.session_state.chunks = []
            st.session_state.raw_chunks = []
            st.session_state.available_sections = []
            st.session_state.selected_sections = None
            st.session_state.section_label_to_key = {}
            st.session_state.section_filter_applied = False
            st.session_state.state = "PROCESSING"
            st.rerun()

    elif st.session_state.state == "SECTION_PICKER":
        # 调试信息
        #st.write(f"DEBUG SECTION_PICKER: selected_character = {st.session_state.get('selected_character')}")
        
=======
    if st.session_state.state == "SECTION_PICKER":
>>>>>>> 48a970c4da66ee735775400400e939bc352b23d1
        inject_game_css(_file_to_data_uri(ASSET_BG))
        ensure_assets_notice()

        sections: List[str] = list(st.session_state.get("available_sections") or [])
        if not sections:
            st.session_state.state = "PROCESSING"
            st.rerun()

        st.markdown(
            """
<div style="max-width:760px;margin:8vh auto 0;background:rgba(8,5,20,0.82);
  backdrop-filter:blur(18px);border:1px solid rgba(130,90,230,0.4);
  border-radius:18px;padding:1.6rem 1.8rem;">
  <div style="font-size:1.25rem;font-weight:700;color:#ead8ff;letter-spacing:1px;">
    选择要阅读的章节
  </div>
  <div style="margin-top:0.35rem;color:rgba(195,170,255,0.78);font-size:0.86rem;">
    这里只展示常见大章节（如 Abstract / Introduction / Method），不会显示 3.1 之类细分标题。
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

        # 初始化 session_state 中的 selected_sections（必须在 widget 实例化前完成）
        if st.session_state.get("selected_sections") is None:
            st.session_state.selected_sections = sections

        # 使用 key 参数直接绑定到 session_state，避免 default 参数导致的点击两次问题
        st.multiselect(
            "章节列表",
            options=sections,
            key="selected_sections",
        )
        # 从 session_state 获取最终选择
        selected = st.session_state.selected_sections

        col_back, col_ok = st.columns([1, 1])
        with col_back:
            if st.button("返回上传页", key="btn_back_setup", use_container_width=True):
                # 保存当前选择的角色（使用临时键名，在selectbox渲染前恢复）
                saved_character = st.session_state.get("selected_character", DEFAULT_CHARACTER)
                st.session_state.state = "SETUP"
                # 保存角色选择到临时键，在selectbox渲染前恢复
                st.session_state.saved_character = saved_character
                st.rerun()
        with col_ok:
            if st.button("开始阅读", key="btn_start_with_sections", use_container_width=True):
                # 调试信息
                #st.write(f"DEBUG 跳转前: selected_character = {st.session_state.get('selected_character')}")
                if not selected:
                    st.error("请至少勾选一个章节，不能空选。")
                else:
                    st.session_state.section_filter_applied = True
                    st.session_state.state = "PROCESSING"
                    st.rerun()

    # ════════════════════════════
    # STATE: PROCESSING
    # ════════════════════════════
    elif st.session_state.state == "PROCESSING":
        # 调试信息
        #st.write(f"DEBUG PROCESSING: selected_character = {st.session_state.get('selected_character')}")
        
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
    别急嗷！我才不是为你努力的！
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

            raw_chunks: List[PdfChunk] = list(st.session_state.get("raw_chunks") or [])
            if not raw_chunks:
                with st.spinner("解析 PDF…"):
                    try:
                        raw_chunks = load_and_chunk_pdf(
                            pdf_path,
                            use_mineru=bool(st.session_state.use_mineru),
                        )
                    except Exception as e:
                        st.error(f"PDF 解析失败：{e}")
                        if st.button("回到封面"):
                            _reset_session()
                            st.rerun()
                        return

                if not raw_chunks:
                    st.error("没有解析到任何文本。可能是扫描版 PDF，请启用 MinerU OCR。")
                    if st.button("回到封面"):
                        _reset_session()
                        st.rerun()
                    return

                st.session_state.raw_chunks = raw_chunks
                st.session_state.parser_used = raw_chunks[0].parser if raw_chunks else "pypdf"
                section_mapping = _build_common_section_mapping(raw_chunks)
                available_keys = [
                    k for k in COMMON_SECTION_ORDER
                    if any(v == k for v in section_mapping.values())
                ]
                available_labels = [COMMON_SECTION_LABELS[k] for k in available_keys]
                st.session_state.available_sections = available_labels
                st.session_state.section_label_to_key = {COMMON_SECTION_LABELS[k]: k for k in available_keys}
                if st.session_state.get("selected_sections") is None:
                    st.session_state.selected_sections = list(available_labels)

                if (
                    bool(st.session_state.get("enable_section_pick"))
                    and st.session_state.parser_used == "mineru"
                    and available_labels
                    and not bool(st.session_state.get("section_filter_applied"))
                ):
                    st.session_state.state = "SECTION_PICKER"
                    st.rerun()

            working_chunks: List[PdfChunk] = list(st.session_state.get("raw_chunks") or [])
            if (
                bool(st.session_state.get("enable_section_pick"))
                and st.session_state.get("parser_used") == "mineru"
            ):
                label_to_key = dict(st.session_state.get("section_label_to_key") or {})
                if not label_to_key:
                    st.warning("未识别到可勾选的标准章节，已跳过章节筛选。")
                    st.session_state.section_filter_applied = True
                else:
                    chosen_labels = st.session_state.get("selected_sections")
                    chosen_keys = {
                        label_to_key[label]
                        for label in (chosen_labels or [])
                        if label in label_to_key
                    }
                    section_mapping = _build_common_section_mapping(working_chunks)
                    if chosen_keys:
                        working_chunks = [
                            c for i, c in enumerate(working_chunks)
                            if section_mapping.get(i) in chosen_keys
                        ]
                    else:
                        working_chunks = []

            chunks = apply_reading_mode(
                working_chunks,
                reading_mode=str(st.session_state.get("reading_mode") or "detailed"),
            )

            if not chunks:
                st.error("当前筛选条件下没有可读内容。请放宽章节勾选或切换阅读模式。")
                if st.button("返回上传页"):
                    st.session_state.state = "SETUP"
                    st.rerun()
                return

            st.session_state.chunks = chunks
            st.session_state.chunk_idx = 0
            # 合并所有 chunk 的图片映射，供 show_image 渲染时查找
            merged_image_map: Dict[str, str] = {}
            for _c in chunks:
                merged_image_map.update(dict(getattr(_c, "image_map", ())))
            st.session_state.paper_image_map = merged_image_map
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
    elif st.session_state.state == "GAME_LOOP":
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
