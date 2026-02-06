from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.pdf_loader import load_and_chunk_pdf
from utils.script_engine import ScriptGenerator


ROOT_DIR = Path(__file__).resolve().parent
PAPERS_DIR = ROOT_DIR / "papers"
DEFAULT_PAPER_NAME = "ReAct"


def _print_divider(title: str = "") -> None:
    line = "=" * 72
    if title:
        print(f"\n{line}\n{title}\n{line}")
    else:
        print(f"\n{line}")


def _render_item(item: Dict[str, Any]) -> None:
    t = item.get("type")
    if t == "sub_head":
        title = item.get("title", "")
        print(f"  ──────── {title} ────────")
        return
    emo = item.get("emotion")
    if t == "dialogue":
        speaker = item.get("speaker", "奈奈")
        text = item.get("text", "")
        print(f"[{speaker} | {emo}] {text}")
    elif t == "quiz":
        q = item.get("question", "")
        print(f"[奈奈 | {emo}] 小测验：{q}")
    elif t == "choice":
        p = item.get("prompt", "")
        print(f"[奈奈 | {emo}] 选择：{p}")
    else:
        print(f"[未知] {json.dumps(item, ensure_ascii=False)}")


def _choose_option_interactive(options: List[str]) -> int:
    for i, opt in enumerate(options, start=1):
        print(f"  {i}. {opt}")
    while True:
        raw = input("请输入选项编号/字母(A/B/C...)/关键字：").strip()

        # 1) 支持输入数字：1/2/3...
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx

        # 2) 支持输入字母：A/B/C...（大小写均可）
        # 兼容用户输入 "C" / "c" 这种情况
        if len(raw) == 1 and raw.isalpha():
            idx = ord(raw.lower()) - ord("a")
            if 0 <= idx < len(options):
                return idx

        # 3) 兼容输入 "A." / "C、" / "B)" 这类带符号的写法
        if raw:
            ch = raw[0]
            if ch.isalpha():
                idx = ord(ch.lower()) - ord("a")
                if 0 <= idx < len(options):
                    return idx

        # 4) 关键字匹配：允许直接输入/粘贴选项文本的一部分（例如“交替”）
        # 规则：
        # - 若匹配到唯一选项，直接返回
        # - 若匹配到多个，列出候选项并让用户缩小关键字或用编号选择
        kw = raw.strip()
        if len(kw) >= 2:
            matches = [i for i, opt in enumerate(options) if kw in str(opt)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print("匹配到多个选项，请用更具体的关键字或直接输入编号：")
                for i in matches:
                    print(f"  {i + 1}. {options[i]}")
        print("输入无效，请重试。")


def _choose_option_auto(item: Dict[str, Any], options: List[str], strategy: str) -> int:
    if strategy == "first":
        return 0
    if strategy == "correct" and item.get("type") == "quiz":
        correct = str(item.get("correct_answer") or "").strip()
        for i, opt in enumerate(options):
            if str(opt).strip() == correct:
                return i
        return 0
    if strategy == "last":
        return max(0, len(options) - 1)
    return 0


def _play_script_items(
    script_items: List[Dict[str, Any]],
    *,
    interactive: bool,
    auto_strategy: str,
) -> None:
    for item in script_items:
        _render_item(item)

        t = item.get("type")
        if t == "sub_head":
            pass  # 无需选项，直接继续
        elif t in {"quiz", "choice"}:
            options = item.get("options") or []
            if not isinstance(options, list) or not options:
                print("（此条缺少 options，跳过）")
                continue
            options = [str(x) for x in options]

            if interactive:
                picked = _choose_option_interactive(options)
            else:
                picked = _choose_option_auto(item, options, auto_strategy)
                print(f"（自动选择：{picked + 1}. {options[picked]}）")

            # quiz 的反馈
            if t == "quiz":
                correct = str(item.get("correct_answer") or "").strip()
                picked_text = options[picked]
                if picked_text == correct:
                    print(str(item.get("feedback_correct") or "不错嘛。"))
                else:
                    print(str(item.get("feedback_wrong") or "不对喵！再想想。"))

        if interactive:
            input("回车继续下一句…")


def run_headless(
    *,
    pdf_path: Path,
    chunk_size: int,
    chunk_overlap: int,
    max_chunks: Optional[int],
    interactive: bool,
    auto_strategy: str,
    export_path: Optional[Path],
    use_mineru: bool,
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在：{pdf_path}")

    chunks = load_and_chunk_pdf(
        pdf_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_mineru=use_mineru,
    )
    if not chunks:
        raise RuntimeError("没有解析到任何文本（可能是扫描版图片 PDF）。可尝试配置 MINERU_API_TOKEN 并使用 --use-mineru。")

    if max_chunks is not None:
        chunks = chunks[: max(0, max_chunks)]

    gen = ScriptGenerator()

    export: List[Dict[str, Any]] = []

    _print_divider("Paper2Galgame 无头模式（终端）")
    print(f"PDF：{pdf_path}")
    print(f"chunks：{len(chunks)}（chunk_size={chunk_size}, overlap={chunk_overlap}）")
    print(f"交互：{'是' if interactive else '否'}（auto_strategy={auto_strategy}）")

    for chunk in chunks:
        section_label = f" {chunk.section_title}" if getattr(chunk, "section_title", "") else ""
        _print_divider(f"Chunk #{chunk.index}{section_label}")
        script_items = gen.generate_script(
            chunk.text,
            chunk_index=chunk.index,
            section_title=getattr(chunk, "section_title", "") or None,
        )

        export.append(
            {
                "chunk_index": chunk.index,
                "source": chunk.source,
                "script": script_items,
            }
        )

        _play_script_items(script_items, interactive=interactive, auto_strategy=auto_strategy)

    _print_divider("结束")
    print("读完啦喵。")

    if export_path:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出脚本：{export_path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Paper2Galgame headless CLI")
    p.add_argument("--paper", default=DEFAULT_PAPER_NAME, help="论文名称（不含 .pdf），默认 ReAct")
    p.add_argument("--pdf", default=None, help="PDF 文件路径（优先级高于 --paper）")
    p.add_argument("--chunk-size", type=int, default=1400)
    p.add_argument("--chunk-overlap", type=int, default=180)
    p.add_argument("--max-chunks", type=int, default=None, help="限制最多处理多少个 chunk（调试用）")
    p.add_argument("--use-mineru", action="store_true", help="强制使用 MinerU OCR（需要 MINERU_API_TOKEN）")
    p.add_argument("--no-mineru", action="store_true", help="禁用 MinerU OCR（默认启用）")

    p.add_argument(
        "--mode",
        choices=["auto", "interactive"],
        default="auto",
        help="运行模式：auto=全自动；interactive=命令行交互（每句回车/手选选项）",
    )

    # 兼容旧参数（不再推荐使用）：--auto / --interactive
    # - 为了不破坏你之前的命令，这里仍然解析它们，但在 --help 中隐藏
    p.add_argument("--interactive", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)

    p.add_argument(
        "--auto-strategy",
        choices=["first", "correct", "last"],
        default="first",
        help="自动模式的选择策略：first/correct/last",
    )
    p.add_argument("--export", default=None, help="导出所有 chunk 的脚本到 JSON 文件路径")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # 优先使用 --pdf；否则从 papers/ 目录按论文名查找
    if args.pdf:
        pdf_path = Path(str(args.pdf)).expanduser().resolve()
    else:
        name = str(args.paper or DEFAULT_PAPER_NAME).strip()
        if not name:
            name = DEFAULT_PAPER_NAME
        filename = name if name.lower().endswith(".pdf") else f"{name}.pdf"
        pdf_path = (PAPERS_DIR / filename).resolve()

    export_path = Path(args.export).expanduser().resolve() if args.export else None

    # mode 优先；兼容旧参数时用旧参数覆盖 mode
    mode = str(getattr(args, "mode", "auto") or "auto").strip()
    if getattr(args, "interactive", False):
        mode = "interactive"
    elif getattr(args, "auto", False):
        mode = "auto"
    interactive = mode == "interactive"

    try:
        run_headless(
            pdf_path=pdf_path,
            chunk_size=int(args.chunk_size),
            chunk_overlap=int(args.chunk_overlap),
            max_chunks=args.max_chunks,
            interactive=interactive,
            auto_strategy=str(args.auto_strategy),
            export_path=export_path,
            use_mineru=False if bool(args.no_mineru) else True,
        )
        return 0
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

