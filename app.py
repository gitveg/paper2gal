from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from utils.pdf_loader import load_and_chunk_pdf, PdfChunk
from utils.mineru_parser import token_available
from utils.script_engine import ScriptGenerator


# -----------------------------
# 资源路径（必须是本地路径）
# 注意：你需要手动把图片放到 assets/ 目录下（见 README.md 与 assets/PLACE_IMAGES_HERE.txt）
# -----------------------------
ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"

ASSET_BG = ASSETS_DIR / "bg_classroom.png"
ASSET_CHAR = {
    "char_normal": ASSETS_DIR / "char_normal.png",
    "char_happy": ASSETS_DIR / "char_happy.png",
    "char_angry": ASSETS_DIR / "char_angry.png",
    "char_shy": ASSETS_DIR / "char_shy.png",
}


def _file_to_data_uri(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    # 根据后缀猜测 mime（这里只用 png）
    mime = "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def inject_css(bg_data_uri: Optional[str]) -> None:
    st.markdown(
        """
<style>
/* 隐藏 Streamlit 默认 UI */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* 全屏背景层 */
.p2g-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  background: #111;
  background-image: var(--p2g-bg);
  background-size: cover;
  background-position: center;
  filter: saturate(1.05);
}

/* 角色立绘：右下角 */
.p2g-char {
  position: fixed;
  right: 2.0rem;
  bottom: 8.2rem; /* 留出对话框高度 */
  width: min(32vw, 420px);
  z-index: 2;
  pointer-events: none;
  user-select: none;
  filter: drop-shadow(0 18px 28px rgba(0,0,0,0.55));
}

/* 对话框：底部固定 */
.p2g-dialogue {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 1.3rem;
  width: min(980px, 92vw);
  z-index: 3;
  padding: 1.05rem 1.2rem;
  border-radius: 18px;
  background: rgba(0,0,0,0.55);
  border: 1px solid rgba(255,255,255,0.14);
  backdrop-filter: blur(8px);
  box-shadow: 0 18px 40px rgba(0,0,0,0.35);
  color: rgba(255,255,255,0.92);
  font-family: ui-monospace, "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
}
.p2g-speaker {
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 0.35rem;
  color: rgba(255,255,255,0.96);
}
.p2g-text {
  font-size: 1.02rem;
  line-height: 1.55;
  white-space: pre-wrap;
}
.p2g-hint {
  margin-top: 0.55rem;
  font-size: 0.92rem;
  color: rgba(255,255,255,0.7);
}

/* 让主内容区透明，避免遮挡背景 */
[data-testid="stAppViewContainer"] > .main {
  background: transparent;
}
[data-testid="stAppViewContainer"] {
  background: transparent;
}

/* 按钮组更像“选项” */
div.stButton > button {
  border-radius: 14px;
  padding: 0.6rem 0.95rem;
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(20,20,20,0.35);
  color: rgba(255,255,255,0.92);
}
div.stButton > button:hover {
  border-color: rgba(255,255,255,0.32);
  background: rgba(20,20,20,0.5);
}
</style>
        """,
        unsafe_allow_html=True,
    )

    bg_css = f'url("{bg_data_uri}")' if bg_data_uri else "none"
    st.markdown(
        f"""
<div class="p2g-bg" style="--p2g-bg: {bg_css};"></div>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "state" not in st.session_state:
        st.session_state.state = "SETUP"

    st.session_state.setdefault("chunks", [])  # List[PdfChunk]
    st.session_state.setdefault("chunk_idx", 0)

    st.session_state.setdefault("script_items", [])  # List[Dict[str, Any]]
    st.session_state.setdefault("script_idx", 0)

    st.session_state.setdefault("current_feedback", None)  # str|None
    st.session_state.setdefault("answered", False)

    st.session_state.setdefault("generator_ready", False)
    st.session_state.setdefault("use_mineru", True)


def ensure_assets_notice() -> None:
    missing = []
    if not ASSET_BG.exists():
        missing.append(str(ASSET_BG))
    for k, p in ASSET_CHAR.items():
        if not p.exists():
            missing.append(str(p))

    if missing:
        st.warning(
            "检测到缺少本地图片资源（不会使用网图 URL）。请手动把图片放到以下路径：\n\n- "
            + "\n- ".join(missing)
        )


def get_current_item() -> Optional[Dict[str, Any]]:
    items: List[Dict[str, Any]] = st.session_state.script_items
    idx: int = st.session_state.script_idx
    if 0 <= idx < len(items):
        return items[idx]
    return None


def load_script_for_chunk(chunks: List[PdfChunk], chunk_idx: int) -> None:
    """
    生成某个 chunk 的脚本，并重置播放指针。
    """
    gen = ScriptGenerator()
    chunk = chunks[chunk_idx]
    script = gen.generate_script(
        chunk.text,
        chunk_index=chunk.index,
        section_title=getattr(chunk, "section_title", "") or None,
    )

    st.session_state.script_items = script
    st.session_state.script_idx = 0
    st.session_state.current_feedback = None
    st.session_state.answered = False
    st.session_state.generator_ready = True


def advance() -> None:
    """
    前进到下一条脚本；若当前 chunk 播放结束，则生成下一个 chunk 的脚本。
    """
    items: List[Dict[str, Any]] = st.session_state.script_items
    st.session_state.current_feedback = None
    st.session_state.answered = False

    if not items:
        return

    st.session_state.script_idx += 1

    if st.session_state.script_idx >= len(items):
        # chunk 结束 -> 下一个 chunk
        chunks: List[PdfChunk] = st.session_state.chunks
        st.session_state.chunk_idx += 1
        if st.session_state.chunk_idx >= len(chunks):
            # 全部结束
            st.session_state.script_items = [
                {
                    "type": "dialogue",
                    "speaker": "奈奈",
                    "text": "呼……总算读完了！笨蛋主人，能坚持到最后还算有点出息喵。",
                    "emotion": "char_happy",
                }
            ]
            st.session_state.script_idx = 0
            return

        # 生成下一个 chunk
        st.session_state.generator_ready = False
        st.session_state.state = "PROCESSING"
        st.rerun()


def render_game_layer(item: Optional[Dict[str, Any]]) -> None:
    bg_uri = _file_to_data_uri(ASSET_BG)
    inject_css(bg_uri)

    ensure_assets_notice()

    # 角色立绘
    emotion_key = "char_normal"
    if item and item.get("emotion"):
        emotion_key = str(item.get("emotion"))
    char_path = ASSET_CHAR.get(emotion_key, ASSET_CHAR["char_normal"])
    char_uri = _file_to_data_uri(char_path)
    if char_uri:
        st.markdown(
            f'<img class="p2g-char" src="{char_uri}" />',
            unsafe_allow_html=True,
        )

    # 对话框内容
    speaker = "奈奈"
    text = "喵……（空）"
    hint = "点击“下一步”继续。"

    if not item:
        text = "还没有脚本内容……你可以回到封面重新上传 PDF。"
    else:
        t = item.get("type")
        if t == "sub_head":
            speaker = "奈奈"
            text = f"【小节】{item.get('title') or ''}"
            hint = "点击“下一步”继续。"
        elif t == "dialogue":
            speaker = str(item.get("speaker") or "奈奈")
            text = str(item.get("text") or "")
            hint = "点击“下一步”继续。"
        elif t == "quiz":
            speaker = "奈奈"
            text = str(item.get("question") or "来做个小测验喵！")
            hint = "先选择一个选项。"
        elif t == "choice":
            speaker = "奈奈"
            text = str(item.get("prompt") or "你选哪个？")
            hint = "先选择一个选项。"
        else:
            speaker = "奈奈"
            text = str(item.get("text") or json.dumps(item, ensure_ascii=False))
            hint = "点击“下一步”继续。"

    feedback = st.session_state.current_feedback
    if feedback:
        hint = feedback

    st.markdown(
        f"""
<div class="p2g-dialogue">
  <div class="p2g-speaker">{speaker}</div>
  <div class="p2g-text">{text}</div>
  <div class="p2g-hint">{hint}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_interaction(item: Optional[Dict[str, Any]]) -> None:
    """
    渲染 quiz/choice 的按钮组与“下一步”。
    注意：按钮必须在普通 Streamlit 流里，不能只放 HTML。
    """
    st.markdown("<div style='height: 68vh;'></div>", unsafe_allow_html=True)

    cols = st.columns([1, 1, 1])
    with cols[1]:
        if item and item.get("type") in {"quiz", "choice"}:
            opts = item.get("options") or []
            if isinstance(opts, list) and opts:
                st.markdown("### 选项")
                for i, opt in enumerate(opts):
                    label = str(opt)
                    if st.button(label, key=f"opt_{st.session_state.chunk_idx}_{st.session_state.script_idx}_{i}"):
                        if item.get("type") == "quiz":
                            correct = str(item.get("correct_answer") or "").strip()
                            if label == correct:
                                st.session_state.current_feedback = str(
                                    item.get("feedback_correct") or "不错嘛。"
                                )
                            else:
                                st.session_state.current_feedback = str(
                                    item.get("feedback_wrong") or "不对喵！再想想。"
                                )
                        else:
                            st.session_state.current_feedback = f"你选择了：{label}"
                        st.session_state.answered = True

            st.markdown("---")

        # 下一步：quiz/choice 必须先作答才允许前进；sub_head/dialogue 可直接下一步
        can_next = True
        if item and item.get("type") in {"quiz", "choice"}:
            can_next = bool(st.session_state.answered)

        if st.button("下一步 ▶", disabled=not can_next, use_container_width=True):
            advance()

        if st.button("回到封面（重新上传）", use_container_width=True):
            st.session_state.state = "SETUP"
            st.session_state.chunks = []
            st.session_state.chunk_idx = 0
            st.session_state.script_items = []
            st.session_state.script_idx = 0
            st.session_state.current_feedback = None
            st.session_state.answered = False
            st.session_state.generator_ready = False
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Paper2Galgame", page_icon="📄", layout="wide")
    init_state()

    if st.session_state.state == "SETUP":
        st.title("Paper2Galgame")
        st.caption("把学术论文变成猫娘陪读的视觉小说（剧本化，而不是纯摘要）。")

        ensure_assets_notice()

        st.markdown("#### 上传 PDF")
        uploaded = st.file_uploader("选择一篇 PDF 论文", type=["pdf"])
        mineru_ready = token_available()
        default_use_mineru = bool(st.session_state.use_mineru) and mineru_ready
        st.session_state.use_mineru = st.checkbox(
            "Use MinerU OCR for scanned PDFs (requires MINERU_API_TOKEN)",
            value=default_use_mineru,
            disabled=not mineru_ready,
        )
        if not mineru_ready:
            st.caption("Tip: set MINERU_API_TOKEN to enable OCR parsing.")

        st.markdown("---")
        st.markdown(
            """
**提示：**
- 需要先配置 `OPENAI_API_KEY`（OpenAI 或 DeepSeek OpenAI 兼容接口）。
- 立绘/背景必须放在本地 `assets/` 目录（见 `README.md`）。
            """.strip()
        )

        if uploaded is not None:
            # 保存到临时文件，交给 PyPDFLoader
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                f.write(uploaded.read())
                tmp_path = Path(f.name)

            st.session_state._tmp_pdf_path = str(tmp_path)  # type: ignore[attr-defined]
            st.session_state.state = "PROCESSING"
            st.rerun()

    if st.session_state.state == "PROCESSING":
        st.title("正在把论文拆成剧本……")
        st.caption("别急喵！我、我才不是为了你才努力的！")

        ensure_assets_notice()

        # 两种情况：
        # 1) 首次上传：chunks 为空 -> 解析 PDF
        # 2) 播放到下一 chunk：chunks 已存在 -> 仅为当前 chunk_idx 生成脚本
        if not st.session_state.chunks:
            pdf_path = Path(getattr(st.session_state, "_tmp_pdf_path", ""))
            if not pdf_path.exists():
                st.error("临时 PDF 文件丢失了，请回到封面重新上传。")
                if st.button("回到封面"):
                    st.session_state.state = "SETUP"
                    st.rerun()
                return

            with st.spinner("解析 PDF 并切分 chunk..."):
                chunks = load_and_chunk_pdf(
                    pdf_path,
                    use_mineru=bool(st.session_state.use_mineru),
                )
                if not chunks:
                    st.error("没有解析到任何文本。可能是扫描版图片 PDF。可尝试配置 MINERU_API_TOKEN 并启用 OCR。")
                    if st.button("回到封面"):
                        st.session_state.state = "SETUP"
                        st.rerun()
                    return

                st.session_state.chunks = chunks
                st.session_state.chunk_idx = 0

        idx = int(st.session_state.chunk_idx)
        idx = max(0, min(idx, len(st.session_state.chunks) - 1))
        st.session_state.chunk_idx = idx

        with st.spinner(f"生成剧本（chunk #{idx}）..."):
            try:
                load_script_for_chunk(st.session_state.chunks, idx)
            except Exception as e:
                st.error(str(e))
                st.info("请配置好环境变量后再试（见 README.md）。")
                if st.button("回到封面"):
                    st.session_state.state = "SETUP"
                    st.session_state.chunks = []
                    st.session_state.chunk_idx = 0
                    st.session_state.script_items = []
                    st.session_state.script_idx = 0
                    st.session_state.current_feedback = None
                    st.session_state.answered = False
                    st.session_state.generator_ready = False
                    st.rerun()
                return

        st.session_state.state = "GAME_LOOP"
        st.rerun()

    if st.session_state.state == "GAME_LOOP":
        # 若前一个“advance”触发了 PROCESSING，这里不会进来
        item = get_current_item()

        # 如果 chunk 切换后进入 PROCESSING，再生成脚本
        if not st.session_state.generator_ready:
            st.session_state.state = "PROCESSING"
            st.rerun()

        render_game_layer(item)
        render_interaction(item)


if __name__ == "__main__":
    # 建议使用：streamlit run app.py
    main()

