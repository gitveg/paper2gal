# 📖 Paper2Galgame

> 把论文阅读变成有趣的二次元剧情游戏。

上传一篇 PDF，二次元AI（比如猫娘、蜡笔小新）会把论文**按章节剧本化**——不是摘要，是真正的角色对白、吐槽、小测验和选择题。基于 Streamlit 构建，支持 UI 模式与命令行无头模式。

---

## 🗂️ 目录结构

```
paper2gal/
├── app.py                 # 🖥️ Streamlit UI 主程序
├── headless.py            # 💻 命令行无头模式
├── utils/
│   ├── script_engine.py   # 🎭 LLM 剧本生成引擎
│   ├── pdf_loader.py      # 📄 PDF 解析与章节切分
│   ├── reading_mode.py    # ⚡ 阅读模式过滤器
│   ├── mineru_parser.py   # 🔍 MinerU OCR 客户端
│   ├── config.py          # ⚙️ 配置加载
│   └── .env               # 🔑 敏感配置（自行创建）
├── assets/                # 🎨 立绘与背景图片
├── papers/                # 📚 示例 PDF（含 ReAct Demo）
├── output/                # 💾 MinerU 解析缓存
└── .streamlit/config.toml # 🌐 Streamlit 服务配置
```

---

## 🚀 快速开始

### 1️⃣ 创建环境

```bash
conda env create -f environment.yml
conda activate paper2gal
```

### 2️⃣ 配置 API Key

复制 `utils/.env.example` 为 `utils/.env`，填入你的密钥：

```dotenv
# 推荐：DeepSeek
DeepSeek_API_KEY=sk-xxxxxxxxxxxxxxxx
DeepSeek_BASE_URL=https://api.deepseek.com/v1
DeepSeek_MODEL=deepseek-chat

# 或 OpenAI 兼容接口
# OPENAI_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：MinerU OCR（按章节解析，效果更好）
# MINERU_KEY=your_token_here
```

> 💡 `.env` 加载优先级：`utils/.env` → 项目根目录 `.env` → 当前工作目录 `.env`

### 3️⃣ 放入角色素材

将图片放入 `assets/` 目录，文件名必须完全一致：

| 文件 | 用途 |
|---|---|
| `bg_classroom.png` | 游戏背景 |
| `char_normal.png` | 角色·普通 |
| `char_happy.png` | 角色·开心 |
| `char_angry.png` | 角色·生气 |
| `char_shy.png` | 角色·害羞 |

> 📌 项目只读本地路径，不使用任何网络图片。缺失图片时页面会给出提示。

### 4️⃣ 启动！

```bash
streamlit run app.py
```

没有 PDF？点击设置页的 **「🎮 Demo：ReAct 论文」** 按钮，一键加载内置示例直接体验。

---

## 📖 阅读模式

| 模式 | 说明 | 适合场景 |
|---|---|---|
| ⚡ **极速阅读** | 只保留摘要、方法、实验关键章节 | 快速了解论文核心 |
| 📘 **标准阅读**（默认） | 完整阅读全部章节 | 深度理解 |

UI 中可在设置页切换；启用 MinerU 时还可手动勾选阅读章节。

---

## 🔍 PDF 解析双轨

| 方式 | 触发条件 | 特点 |
|---|---|---|
| 🌐 **MinerU OCR** | 配置了 `MINERU_KEY` | 云端 OCR · 按章节切分 · 还原论文结构 |
| 📄 **pypdf** | 未配置或手动禁用 | 本地解析 · 即时响应 · 无需网络 |

解析结果缓存在 `output/mineru/`，重启不重复上传。
界面右上角会显示 `[debug] MINERU` 或 `[debug] PYPDF` 说明当前使用的解析方式。

---

## 💻 命令行无头模式

```bash
# 交互式推进
python headless.py --mode interactive

# 全自动播放
python headless.py --mode auto

# 极速阅读 + 自动播放
python headless.py --mode auto --reading-mode fast

# 指定 PDF + 跳过 MinerU
python headless.py --mode auto --pdf papers/react.pdf --no-mineru
```

---

