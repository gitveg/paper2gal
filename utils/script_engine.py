from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from utils.config import load_config

try:
    from langchain_openai import ChatOpenAI
except Exception as e:  # pragma: no cover
    ChatOpenAI = None  # type: ignore


SYSTEM_PROMPT = """
你是一个傲娇但学识渊博的二次元猫娘"奈奈"。你的任务是陪用户读论文。
输入是论文的**一整节**（例如 Abstract、Introduction、或 3 Method）。你需要把它改编成一段"对话剧本"。

要求：
1. **去学术化**：用口语、比喻来解释复杂的概念（比如把"神经网络"比作"连接起来的猫脑"）。
2. **情绪价值**：不要只讲课。要穿插吐槽（比如"这个作者写的句子好长啊喵！"）、撒娇或严厉。
3. **互动设计**：在关键知识点，设计一个"选项"让用户选，或者设计一个"小测验"。
4. **层次划分**：若本节内容较多（如 Method、Related Work），请**按层次划分子节**。在子节开头插入一条 type="sub_head"，且带 "title" 字段（子节标题，如 "3.1 概述"）。子节内再写 dialogue/quiz/choice。这样用户能分层次理解，每层可含多个对话和题目。
5. **解析**：quiz 和 choice 都必须附上 "explanation" 字段（50~120 字）。quiz 的解析解释为什么正确答案是对的；choice 的解析则针对用户的选择，给出思考角度或拓展观点，帮助加深理解。无论哪种，都要口语化，可以吐槽，有奈奈的风格。
6. **格式严格**：输出为 JSON 列表。type 只能是 dialogue / quiz / choice / sub_head。sub_head 项只需 type 与 title；dialogue 需 speaker/text/emotion/type；quiz 需 question/options/correct_answer/feedback_correct/feedback_wrong/explanation；choice 需 prompt/options/emotion/explanation。
""".strip()


@dataclass
class ScriptItem:
    type: str  # dialogue / quiz / choice / sub_head
    speaker: Optional[str] = None
    text: Optional[str] = None
    emotion: Optional[str] = None

    # quiz
    question: Optional[str] = None
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    feedback_correct: Optional[str] = None
    feedback_wrong: Optional[str] = None
    explanation: Optional[str] = None  # 答题解析，无论对错都展示

    # choice（非测验选择）
    prompt: Optional[str] = None


class ScriptGenerator:
    """
    把论文 chunk 转换为"视觉小说脚本"（JSON 列表）。

    说明：
    - 使用 OpenAI 兼容接口（OpenAI / DeepSeek 等）
    - 通过强约束提示词 + JSON 解析与容错，尽量保证输出可播放
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 2,
        request_timeout: int = 60,
    ) -> None:
        if ChatOpenAI is None:
            raise RuntimeError(
                "未能导入 langchain_openai.ChatOpenAI。请确认已安装 requirements.txt 里的依赖。"
            )

        cfg = load_config()

        self.model = model or cfg.llm.model
        self.temperature = temperature if temperature is not None else cfg.llm.temperature
        self.max_retries = max_retries if max_retries is not None else cfg.llm.max_retries
        self.request_timeout = request_timeout if request_timeout is not None else cfg.llm.request_timeout

        api_key = cfg.llm.api_key
        base_url = cfg.llm.base_url

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "api_key": api_key,
            "timeout": self.request_timeout,
        }
        if base_url:
            kwargs["base_url"] = base_url
            kwargs["openai_api_base"] = base_url

        try:
            self.llm = ChatOpenAI(**kwargs)
        except TypeError:
            kwargs.pop("openai_api_base", None)
            self.llm = ChatOpenAI(**kwargs)

    def generate_script(
        self,
        chunk_text: str,
        *,
        chunk_index: int,
        section_title: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        返回一个 JSON 列表（Python list[dict]），供前端逐条播放。
        section_title 为当前章节名（如 Abstract / 3 Method），用于提示 LLM。
        """
        chunk_text = (chunk_text or "").strip()
        if not chunk_text:
            return self._fallback_script("这一段好像是空的……你是不是上传了扫描版？", chunk_index=chunk_index)

        user_prompt = self._build_user_prompt(
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            section_title=section_title or "",
        )

        last_err: Optional[Exception] = None
        for _ in range(self.max_retries + 1):
            try:
                resp = self.llm.invoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ]
                )
                content = (getattr(resp, "content", "") or "").strip()
                parsed = self._parse_json_list(content)
                normalized = self._normalize_script(parsed)
                if normalized:
                    return normalized
            except Exception as e:
                last_err = e
                continue

        msg = (
            "唔……这段作者写得太绕了，我一时没把剧本整理成标准格式。"
            "我们先用简化版继续读下去喵！"
        )
        if last_err:
            msg += f"\n（内部解析失败：{type(last_err).__name__}）"
        return self._fallback_script(msg, chunk_index=chunk_index, extra_hint=chunk_text[:260])

    def _build_user_prompt(
        self,
        *,
        chunk_text: str,
        chunk_index: int,
        section_title: str = "",
    ) -> str:
        section_line = f"当前章节：{section_title}\n\n" if section_title else ""
        return f"""
{section_line}输入论文本节全文（chunk #{chunk_index}）：
\"\"\"{chunk_text}\"\"\"

请只输出 JSON 数组（list），不要输出任何额外文本、不要用 ``` 包裹。

约束：
- type 只能是 dialogue / quiz / choice / sub_head
- sub_head 项：仅需 type="sub_head" 与 title="子节标题"（用于长节按层次划分）
- emotion 只能在以下 key 里选一个：char_normal, char_happy, char_angry, char_shy
- dialogue 项必须包含 speaker,text,emotion,type
- quiz 项必须包含：type="quiz", question, options(数组), correct_answer, feedback_correct, feedback_wrong, explanation(解析，50~120字，解释为什么正确答案是对的)
- choice 项必须包含：type="choice", prompt, options(数组), emotion, explanation(解析，50~120字，针对这道思考题给出奈奈的观点或思路拓展)

若本节内容较多，请用 sub_head 划分子节，再在子节内写 dialogue/quiz/choice。请把解释写进对话文本里，而不是 JSON 外面。
""".strip()

    def _parse_json_list(self, raw: str) -> List[Any]:
        cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.I | re.M)

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
        except Exception:
            pass

        m = re.search(r"\[[\s\S]*\]", cleaned)
        if m:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data

        raise ValueError("LLM 输出不是 JSON 列表")

    def _normalize_script(self, items: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            t = str(it.get("type") or "").strip()
            if t not in {"dialogue", "quiz", "choice", "sub_head"}:
                continue

            if t == "sub_head":
                title = str(it.get("title") or "").strip()
                if title:
                    out.append({"type": "sub_head", "title": title})
                continue

            if t == "dialogue":
                speaker = str(it.get("speaker") or "奈奈").strip()
                text = str(it.get("text") or "").strip()
                emotion = self._clamp_emotion(it.get("emotion"))
                if text:
                    out.append(
                        {
                            "type": "dialogue",
                            "speaker": speaker,
                            "text": text,
                            "emotion": emotion,
                        }
                    )

            elif t == "quiz":
                q = str(it.get("question") or "").strip()
                opts = it.get("options")
                if not (q and isinstance(opts, list) and len(opts) >= 2):
                    continue
                opts2 = [self._normalize_option_text(o) for o in opts]
                correct = self._normalize_correct_answer(it.get("correct_answer"), opts2)
                explanation = str(it.get("explanation") or "").strip()
                out.append(
                    {
                        "type": "quiz",
                        "question": q,
                        "options": opts2,
                        "correct_answer": correct,
                        "feedback_correct": str(it.get("feedback_correct") or "嗯哼，还行吧。").strip(),
                        "feedback_wrong": str(it.get("feedback_wrong") or "笨蛋！再想想喵！").strip(),
                        "explanation": explanation,
                        "emotion": self._clamp_emotion(it.get("emotion")),
                    }
                )

            elif t == "choice":
                prompt = str(it.get("prompt") or it.get("question") or "你选哪个？").strip()
                opts = it.get("options")
                if not (isinstance(opts, list) and len(opts) >= 2):
                    continue
                explanation = str(it.get("explanation") or "").strip()
                out.append(
                    {
                        "type": "choice",
                        "prompt": prompt,
                        "options": [self._normalize_option_text(o) for o in opts],
                        "emotion": self._clamp_emotion(it.get("emotion")),
                        "explanation": explanation,
                    }
                )

        if not out:
            return self._fallback_script(
                "这段写得太硬核了……我先用最普通的方式给你捋一遍喵。",
                chunk_index=-1,
            )
        return out

    def _normalize_option_text(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        for _ in range(3):
            prev = text
            text = re.sub(r"^\s*[（(]\s*(?:[A-Za-z]|\d{1,2})\s*[）)]\s*", "", text).strip()
            text = re.sub(r"^\s*(?:[A-Za-z]|\d{1,2})\s*[\.\)、,:：]\s*", "", text).strip()
            if text == prev:
                break
        return text or str(value).strip()

    def _normalize_correct_answer(self, raw_answer: Any, options: List[str]) -> str:
        if not options:
            return str(raw_answer or "").strip()

        raw = str(raw_answer or "").strip()
        if not raw:
            return options[0]

        idx = self._option_label_to_index(raw)
        if idx is not None and 0 <= idx < len(options):
            return options[idx]

        cleaned = self._normalize_option_text(raw)
        idx = self._option_label_to_index(cleaned)
        if idx is not None and 0 <= idx < len(options):
            return options[idx]

        for opt in options:
            if cleaned == str(opt).strip():
                return opt

        return cleaned or options[0]

    def _option_label_to_index(self, text: str) -> Optional[int]:
        s = str(text or "").strip()
        if not s:
            return None

        m = re.fullmatch(r"[（(]?\s*([A-Za-z])\s*[）)]?[\.\)、,:：]?\s*", s)
        if m:
            return ord(m.group(1).upper()) - ord("A")

        m = re.fullmatch(r"[（(]?\s*(\d{1,2})\s*[）)]?[\.\)、,:：]?\s*", s)
        if m:
            return int(m.group(1)) - 1

        return None

    def _clamp_emotion(self, emotion: Any) -> str:
        e = str(emotion or "char_normal").strip()
        return e if e in {"char_normal", "char_happy", "char_angry", "char_shy"} else "char_normal"

    def _fallback_script(self, msg: str, *, chunk_index: int, extra_hint: Optional[str] = None) -> List[Dict[str, Any]]:
        text = msg
        if extra_hint:
            text += f"\n\n（原文片段：{extra_hint}…）"
        return [
            {
                "type": "dialogue",
                "speaker": "奈奈",
                "text": text,
                "emotion": "char_shy" if chunk_index % 2 else "char_normal",
            }
        ]
