from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class LLMConfig:
    """
    统一的 LLM 配置（OpenAI / DeepSeek 等 OpenAI 兼容接口）。

    说明：
    - 非敏感配置：直接写在本文件（默认值）
    - 敏感配置：只从 `.env` 读取（API Key / Base URL）
    """

    api_key: str
    base_url: Optional[str]
    model: str
    temperature: float
    request_timeout: int
    max_retries: int


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig


def _project_root() -> Path:
    # utils/config.py -> project root
    return Path(__file__).resolve().parents[1]


def load_config() -> AppConfig:
    """
    加载配置：
    - 仅加载 `.env` 中的敏感字段
    - 其余字段使用本文件内置默认值
    """
    root = _project_root()

    # 先加载 .env（敏感信息建议放这里）
    # 规则：优先尝试“当前工作目录”的 .env，其次尝试“项目根目录”的 .env，最后尝试 utils/.env
    cwd_env = Path.cwd() / ".env"
    root_env = root / ".env"
    utils_env = root / "utils" / ".env"
    if cwd_env.exists():
        load_dotenv(dotenv_path=str(cwd_env), override=False)
    elif root_env.exists():
        load_dotenv(dotenv_path=str(root_env), override=False)
    elif utils_env.exists():
        load_dotenv(dotenv_path=str(utils_env), override=False)

    # -----------------------------
    # 非敏感默认配置：直接写死在这里
    # -----------------------------
    default_model = "deepseek-chat"
    temperature = 0.7
    request_timeout = 60
    max_retries = 2

    # -----------------------------
    # 敏感配置：只从 .env 读
    # -----------------------------
    api_key = (os.getenv("DeepSeek_API_KEY") or "").strip()
    base_url_raw = (os.getenv("DeepSeek_BASE_URL") or os.getenv("OPENAI_API_BASE") or "").strip()
    base_url = base_url_raw or None
    model = (os.getenv("DeepSeek_MODEL") or "").strip() or default_model

    if not api_key:
        raise RuntimeError(
            "缺少敏感配置：未在 .env 中设置 API_KEY。"
        )

    llm = LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        request_timeout=request_timeout,
        max_retries=max_retries,
    )
    return AppConfig(llm=llm)

