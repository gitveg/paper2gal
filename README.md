## Paper2Galgame

把用户上传的 PDF 学术论文，“剧本化”为一款二次元猫娘伴读的视觉小说（Streamlit 应用）。

### 你需要准备的本地资源（必须手动放入）
请在项目根目录创建 `assets/` 文件夹，并放入以下图片文件（文件名必须完全一致，代码里会按本地路径读取）：

- `assets/bg_classroom.png`（默认教室背景）
- `assets/char_normal.png`
- `assets/char_happy.png`
- `assets/char_angry.png`
- `assets/char_shy.png`

> 注意：本项目**不会**使用任何网图 URL；所有图片都从本地路径读取。

### 安装与运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### Conda 环境（推荐）

#### 方式 1：使用 environment.yml（最省事）

```bash
conda env create -f environment.yml
conda activate paper2gal
streamlit run app.py
```

#### 方式 2：手动创建 + pip 安装

```bash
conda create -n paper2gal python=3.11 -y
conda activate paper2gal
python -m pip install -r requirements.txt
streamlit run app.py
```

### 配置 LLM（OpenAI / DeepSeek）

本项目通过 `langchain-openai` 调用 OpenAI 兼容接口。

推荐使用统一配置文件：把 `config.example.json` 复制为 `config.json`，然后填写。

```bash
copy config.example.json config.json
```

随后你可以选择两种方式提供 API Key：
- **方式 1（推荐）**：环境变量 `OPENAI_API_KEY`
- **方式 2**：写入 `config.json` 的 `llm.api_key`

配置优先级：**环境变量 > config.json > 默认值**。

你也可以用环境变量 `PAPER2GAL_CONFIG` 指定配置文件路径。

仍然支持仅用环境变量（不创建 config.json），如下：

#### 方案 A：OpenAI

- `OPENAI_API_KEY`：你的 API Key
- `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）

#### 方案 B：DeepSeek（OpenAI 兼容）

- `OPENAI_API_KEY`：你的 DeepSeek API Key
- `OPENAI_BASE_URL`：DeepSeek OpenAI 兼容 Base URL（例如 `https://api.deepseek.com`，以官方为准）
- `OPENAI_MODEL`（可选，例如 `deepseek-chat`，以官方为准）

### 使用说明

- 上传 PDF 后，应用会把论文切成多个 Chunk。
- 每个 Chunk 会交给“剧本引擎”生成 **JSON 列表**，然后以视觉小说方式逐条播放。
- 播放完一个 Chunk 会自动生成下一个 Chunk 的脚本。

### 无头模式（不启用 UI）

当前仓库已支持无头 CLI：`headless.py`。

#### 终端交互模式（像“对话模式”）

```bash
python headless.py --pdf "你的论文.pdf" --interactive
```

#### 自动模式（批处理/无交互）

```bash
python headless.py --pdf "你的论文.pdf" --auto --auto-strategy correct --export "out/script.json"
```

说明：
- `--interactive`：每句回车继续；遇到 `quiz/choice` 需要你输入编号选择。
- `--auto`：自动选择并继续（`--auto-strategy` 可选 `first/correct/last`）。
- `--export`：把所有 chunk 的脚本导出为一个 JSON 文件（便于后续做离线回放/调试）。

