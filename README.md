# 📖 Paper2Galgame

> 把学术论文变成猫娘陪读的视觉小说。

上传一篇 PDF，AI 猫娘「奈奈」会把论文**按章节剧本化**——不是摘要，是真正的角色对白、吐槽、小测验和选择题。基于 Streamlit 构建，支持 UI 模式与命令行无头模式。

---

## 目录结构

```
paper2gal/
├── app.py               # Streamlit UI 主程序
├── headless.py          # 命令行无头模式
├── utils/
│   ├── config.py        # 配置加载（读取 .env）
│   ├── script_engine.py # LLM 剧本生成引擎
│   ├── pdf_loader.py    # PDF 解析与章节切分
│   ├── mineru_parser.py # MinerU OCR API 客户端
│   └── .env             # 敏感配置（自行创建，不提交）
├── assets/              # 本地图片资源（见下方说明）
├── papers/              # 示例论文存放目录
├── output/              # MinerU 解析缓存
├── requirements.txt
└── environment.yml
```

---

## 快速开始

### 1. 创建环境

```bash
conda env create -f environment.yml
conda activate paper2gal
```

### 2. 配置 API Key

在 `utils/.env`（或项目根目录 `.env`）中填写：

```dotenv
# DeepSeek（推荐）
DeepSeek_API_KEY=sk-xxxxxxxxxxxxxxxx
DeepSeek_BASE_URL=https://api.deepseek.com/v1
DeepSeek_MODEL=deepseek-chat

# 或 OpenAI 标准接口
# OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# OPENAI_API_BASE=https://api.openai.com/v1

# 可选：MinerU OCR（扫描版 PDF 按章节解析）
# MINERU_API_TOKEN=your_token_here
```

> `.env` 加载优先级：`utils/.env` → 项目根目录 `.env` → 当前工作目录 `.env`

### 3. 放入图片资源

将以下图片放入 `assets/` 目录（**文件名必须完全一致**，项目只读本地路径，不使用网图）：

| 文件名 | 说明 |
|---|---|
| `bg_classroom.png` | 教室背景 |
| `char_normal.png` | 奈奈·普通表情 |
| `char_happy.png` | 奈奈·开心 |
| `char_angry.png` | 奈奈·生气 |
| `char_shy.png` | 奈奈·害羞 |

### 4. 运行

**UI 模式**（推荐）：

```bash
streamlit run app.py
```

**命令行无头模式**：

```bash
# 交互式（手动选择选项）
python headless.py --mode interactive

# 自动播放
python headless.py --mode auto

# 指定 PDF，禁用 MinerU
python headless.py --mode auto --pdf papers/react.pdf --no-mineru
```

---

## PDF 解析方式

| 方式 | 触发条件 | 特点 |
|---|---|---|
| **MinerU OCR** | 配置了 `MINERU_API_TOKEN` 且未使用 `--no-mineru` | 云端 OCR，**按章节切分**，还原论文结构 |
| **pypdf** | 未配置 token 或主动禁用 | 本地解析，按字符分块，适合文字版 PDF |

解析结果缓存在 `output/mineru/<pdf_名>/`，重复运行不重复上传。  
运行时会显示 `[debug] MINERU` 或 `[debug] PYPDF` 标识当前解析方式。

---

