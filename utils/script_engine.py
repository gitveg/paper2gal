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
# 角色性格与自称配置
CHARACTER_CONFIGS = {
    "奈奈": {
        "self_name": "奈奈子",
        "style": "傲娇、毒舌但学识渊博的二次元猫娘",
        "tone": "说话爱带'喵'，经常口嫌体正直地吐槽论文作者，称呼用户为'笨蛋'或'你'。"
    },
    "玲娜贝儿": {
        "self_name": "贝儿",
        "style": "机智、可爱、活泼、充满好奇心的粉色小狐狸",
        "tone": "自称'贝儿'，语气热情且充满能量，擅长用森林里的事物做生动的比喻。"
    },
    "默认": {
        "self_name": "我",
        "style": "学识渊博的陪读助手",
        "tone": "语气亲切，逻辑清晰。"
    }
}

SYSTEM_PROMPT = """你现在是一个{character_style}，你的名字是{character_name}，在对话中必须自称"{self_name}"。你的任务是陪用户读论文。
输入是论文的**一整节**（例如 Abstract、Introduction、或 3 Method）。你需要把它改编成一段"对话剧本"。

要求：
1. **去学术化**：用口语、比喻来解释复杂的概念（比如把"神经网络"比作"连接起来的猫脑"）。
2. **情绪价值**：不要只讲课。根据性格穿插吐槽、鼓励或活泼的互动（比如"这个作者写的句子好长啊！"）、撒娇或严厉。
3. **互动设计**：在关键知识点，设计一个"选项"让用户选，或者设计一个"小测验"。
4. **层次划分**：若本节内容较多（如 Method、Related Work），请**按层次划分子节**。在子节开头插入一条 type="sub_head"，且带 "title" 字段（子节标题，如 "3.1 概述"）。子节内再写 dialogue/quiz/choice。这样用户能分层次理解，每层可含多个对话和题目。
5. **解析**：quiz 和 choice 都必须附上 "explanation" 字段（50~120 字）。quiz 的解析解释为什么正确答案是对的；choice 的解析则针对用户的选择，给出思考角度或拓展观点，帮助加深理解。无论哪种，都要口语化，可以吐槽，有{character_name}的风格。
6. **图片/表格同屏展示**：若正文中有「[图片: ...]」标记，说明原论文该处有插图或表格图。规则：
   - show_image 会与紧随其后的 dialogue **同屏显示**（图片在上，对话在下）。因此：
     * **每当** dialogue 的 text 中提到某张图/表（如"如图1所示""见 Figure 2""如 Figure 1(d) 展示的那样"），**必须紧接在该 dialogue 前面**插入对应的 type="show_image"。
     * 同一张图被多次提及时，每次都要插入 show_image，因为图片会和当前对话文字同屏，帮助理解。
     * **show_image 后紧跟的 dialogue 文字必须真正解释这张图**：描述图里的关键内容、实验结果、趋势对比——不要只说"来看这张图"，而是说"你看这条曲线……这说明……"。
     * show_image 同样适用于表格，figure_id 格式如 "Table 1" / "表1"。
   - **只能**引用"可用图片"列表里列出的图号；列表为空则不生成 show_image。
7. **格式严格**：输出为 JSON 列表。type 只能是 dialogue / quiz / choice / sub_head / show_image。sub_head 项只需 type 与 title；dialogue 需 speaker/text/emotion/type；quiz 需 question/options/correct_answer/feedback_correct/feedback_wrong/explanation；choice 需 prompt/options/emotion/explanation；show_image 需 figure_id 和 caption。
7.**语气特色**：{character_tone}
8.**人设高度一致**：严格遵循"{character_style}"的设定。
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
        image_map: Optional[Dict[str, str]] = None,
        character_name: str = "奈奈",
    ) -> List[Dict[str, Any]]:
        """
        返回一个 JSON 列表（Python list[dict]），供前端逐条播放。
        section_title 为当前章节名（如 Abstract / 3 Method），用于提示 LLM。
        character_name 为当前角色名称，用于 prompt 中。
        """
        conf = CHARACTER_CONFIGS.get(character_name, CHARACTER_CONFIGS["默认"])
        style = conf["style"]
        chunk_text = (chunk_text or "").strip()
        if not chunk_text:
            return self._fallback_script("这一段好像是空的……你是不是上传了扫描版？", chunk_index=chunk_index)

        user_prompt = self._build_user_prompt(
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            section_title=section_title or "",
            image_map=image_map or {},
            character_name=character_name,
        )

        last_err: Optional[Exception] = None
        for _ in range(self.max_retries + 1):
            try:
                # 根据角色名称构建动态 system prompt
                dynamic_system_prompt = SYSTEM_PROMPT.format(
                    character_name=character_name,
                    character_style=conf["style"],
                    self_name=conf["self_name"],      # 注入自称：奈奈子/贝儿
                    character_tone=conf["tone"],
                    character_pronoun="她",
                )
                resp = self.llm.invoke(
                    [
                        SystemMessage(content=dynamic_system_prompt),
                        HumanMessage(content=user_prompt),
                    ]
                )
                content = (getattr(resp, "content", "") or "").strip()
                parsed = self._parse_json_list(content)
                normalized = self._normalize_script(parsed, character_name=character_name)
                if normalized:
                    # 兜底：对 dialogue 中提及的图号自动注入 show_image
                    if image_map:
                        normalized = self._inject_figure_images(normalized, image_map)
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
        return self._fallback_script(msg, chunk_index=chunk_index, character_name=character_name, extra_hint=chunk_text[:260])

    def _build_user_prompt(
        self,
        *,
        chunk_text: str,
        chunk_index: int,
        section_title: str = "",
        image_map: Optional[Dict[str, str]] = None,
        character_name: str = "奈奈",
    ) -> str:
        section_line = f"当前章节：{section_title}\n\n" if section_title else ""
        if image_map:
            figures_line = "可用图片（只能引用这些图号）：" + "、".join(image_map.keys()) + "\n\n"
        else:
            figures_line = ""
        return f"""
{section_line}{figures_line}输入论文本节全文（chunk #{chunk_index}）：
\"\"\"{chunk_text}\"\"\"

请只输出 JSON 数组（list），不要输出任何额外文本、不要用 ``` 包裹。

约束：
- type 只能是 dialogue / quiz / choice / sub_head / show_image
- sub_head 项：仅需 type="sub_head" 与 title="子节标题"（用于长节按层次划分）
- show_image 项：type="show_image", figure_id（**必须与可用图片列表中的图号完全一致**）, caption（简短说明）。每次 dialogue 提到某图/表时，在该 dialogue 前插入对应 show_image；同一图可多次插入。若无可用图片则不生成。
- emotion 只能在以下 key 里选一个：char_normal, char_happy, char_angry, char_shy
- dialogue 项必须包含 speaker,text,emotion,type，其中 speaker 必须是 "{character_name}"
- quiz 项必须包含：type="quiz", question, options(数组), correct_answer, feedback_correct, feedback_wrong, explanation(解析，50~120字，解释为什么正确答案是对的)
- choice 项必须包含：type="choice", prompt, options(数组), emotion, explanation(解析，50~120字，针对这道思考题给出{character_name}的观点或思路拓展)

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

    def _normalize_script(self, items: List[Any], character_name: str = "奈奈") -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            t = str(it.get("type") or "").strip()
            if t not in {"dialogue", "quiz", "choice", "sub_head", "show_image"}:
                continue

            if t == "sub_head":
                title = str(it.get("title") or "").strip()
                if title:
                    out.append({"type": "sub_head", "title": title})
                continue

            if t == "show_image":
                figure_id = str(it.get("figure_id") or "").strip()
                caption = str(it.get("caption") or "").strip()
                if figure_id:
                    out.append({"type": "show_image", "figure_id": figure_id, "caption": caption})
                continue

            if t == "dialogue":
                speaker = str(it.get("speaker") or character_name).strip()
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

    def _find_mentioned_label(self, text: str, image_map: Dict[str, str]) -> Optional[str]:
        """
        检测 dialogue 文字里是否提到了 image_map 中的某个图号（图/表）。
        依次尝试：直接子串匹配 → 数字+前缀模式匹配（兼容中英文变体）。
        返回第一个匹配到的 label，未匹配则返回 None。
        """
        text_lower = text.lower()
        for label in image_map:
            if label.lower() in text_lower:
                return label
        # 数字模式匹配（"Figure 1" ↔ "图1" / "Fig.1" / "figure1" 等）
        for label in image_map:
            nums = re.findall(r"\d+", label)
            if not nums:
                continue
            num = nums[0]
            label_lower = label.lower()
            if re.search(r"tab", label_lower):
                pats = [rf"tab(?:le)?\.?\s*{num}", rf"表\s*{num}"]
            else:
                pats = [rf"fig(?:ure)?\.?\s*{num}", rf"图\s*{num}"]
            if any(re.search(p, text_lower) for p in pats):
                return label
        return None

    def _inject_figure_images(
        self,
        items: List[Dict[str, Any]],
        image_map: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        后处理：扫描每条 dialogue，只要文字里提到了图号就在其前面注入
        show_image（不管之前有没有展示过），让图片和讲解文字同屏呈现。
        app.py 的 _merge_show_image_with_dialogue 会把 show_image+dialogue
        合并成带 figure_id 的 dialogue，最终一步展示图片+解释。
        """
        result: List[Dict[str, Any]] = []
        for item in items:
            if item.get("type") == "dialogue":
                text = str(item.get("text") or "")
                label = self._find_mentioned_label(text, image_map)
                if label:
                    # 直接注入，不做 already_shown 去重——
                    # 同屏显示图片+文字是期望行为，重复展示同一张图是合理的
                    result.append({
                        "type": "show_image",
                        "figure_id": label,
                        "caption": "",
                    })
            result.append(item)
        return result

    def _clamp_emotion(self, emotion: Any) -> str:
        e = str(emotion or "char_normal").strip()
        return e if e in {"char_normal", "char_happy", "char_angry", "char_shy"} else "char_normal"

    def _fallback_script(self, msg: str, *, chunk_index: int, character_name: str = "奈奈", extra_hint: Optional[str] = None) -> List[Dict[str, Any]]:
        text = msg
        if extra_hint:
            text += f"\n\n（原文片段：{extra_hint}…）"
        return [
            {
                "type": "dialogue",
                "speaker": character_name,
                "text": text,
                "emotion": "char_shy" if chunk_index % 2 else "char_normal",
            }
        ]
