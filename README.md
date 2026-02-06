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
conda env create -f environment.yml
conda activate paper2gal
pip install -r requirements.txt
```

在项目根目录创建 `.env`，配置 LLM 接口（二选一即可）：

- `OPENAI_API_KEY`（或 `DeepSeek_API_KEY`）+ 可选 `OPENAI_API_BASE` / `DeepSeek_BASE_URL`
- 剧本生成依赖上述 API，未配置会报错

### 可选：MinerU OCR（扫描版 PDF）

- 在 `.env` 或系统环境变量中设置 `MINERU_API_TOKEN`（可选 `MINERU_API_BASE`）
- 默认启用 MinerU（若未配置 token 会自动回退到 pypdf）
- 如需禁用：headless 模式使用 `--no-mineru`
- 解析结果默认缓存到 `output/mineru/<pdf_name>/`

### 无头模式

```bash

python headless.py --mode interacive/auto
```

