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
```

### 无头模式

```bash

python headless.py --mode interacive/auto
```

