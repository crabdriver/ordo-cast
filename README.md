# 🎙️ Ordo Cast

> **Ordo Creator Suite (创作者工作台) — 核心音视频采集与高精度转录引擎**

`Ordo Cast` 是一个用于自动化下载网络音视频（如 YouTube 视频或播客音频）并调用高精度云端 ASR（火山引擎语音识别）将其转录为纯净 Markdown 录音稿的极速本地流水线。

作为 `Ordo Creator Suite` 的第一站，它致力于解决创作者最核心的内容获取与转录痛点，提供工业级的并发火山 ASR 转录并发起以及多线程文件同步，以超低的价格和极高的识别准确率，把原始的音视频资源变成干净整洁的 Markdown 文稿。

---

## ✨ 核心亮点

- 📥 **多线程智能采集**：基于 `yt-dlp` 高效下载 YouTube 及各大音视频平台的音频资源，自动做人声提取与音频格式转换（FFmpeg 提供技术支撑）。
- ⚡ **工业级 Volcano ASR 转录**：接入高性价比的字节跳动**火山引擎**高精度 ASR 转录接口。支持多线程并发提交任务、本地轮询和智能失败重试。
- 📦 **本地文件级缓存**：内置本地流水线状态表（`manifest.json`），实现完美的「增量更新」，绝对不重复提交相同音频，节省接口费用。
- 📝 **Markdown 结构化文稿**：转录好的长文稿自动按句分组并注入元数据信息（包括原始音频链接、转换事件等），支持干净的本地字符规则清洗。
- 🛡️ **优雅的开源边界**：完全隔离配置文件与用户文稿资源，不小心提交配置文件的烦恼从此成为历史。

---

## 📂 项目结构

```
.
├── audio_pipeline/             # 核心 Python 库 (专注于下载、ASR 转录与任务控制)
├── scripts/                    # 核心总控与脚本层
│   ├── download_youtube.py     # YouTube 视频/音频多线程下载
│   ├── transcribe_batch.py    # 批量并发火山 ASR 语音转录与状态轮询
│   ├── run_full_pipeline.py    # 核心一条龙转录入口 (Download -> Transcribe)
│   └── auto_run_pipeline.py    # 无人值守自动驾驶循环总控
├── tests/                      # 核心引擎自动化测试集 (80+ 高覆盖度单元测试)
└── experimental_llm_writer/    # 🧪 实验性 AI 撰稿与拆稿子项目 (未来独立为 Ordo Scribe)
```

---

## 🧪 实验性子项目：`Ordo Scribe` (`experimental_llm_writer/`)

大模型长稿高维语义清洗与拆稿润色功能已从本核心转录引擎中完全剥离，作为独立的**子项目子模块**，放置于 `experimental_llm_writer/` 目录下。

它包含：
- **`normalize_transcript.py`**：基于大模型的长稿智能清洗与语气词润色。
- **`split_to_wechat_articles.py`**：高维语义拆稿引擎，将数万字的长稿智能拆解为符合微信公众号风格的、具备独立逻辑闭环的文章集。
- 独立的用户提示词设计目录（`prompts/`）与完整的独立测试套件（`tests/`）。

---

## 🛠️ 快速开始

### 1. 环境准备

- **Python 3.10+** (推荐 3.12+)
- **FFmpeg**：音频格式处理与采集依赖（macOS 可直接使用 `brew install ffmpeg` 安装）

```bash
# 激活您的虚拟环境并安装核心依赖
python3 -m venv .venv312
source .venv312/bin/activate
pip install -r requirements.txt
```

### 2. 填写配置

复制并填写配置文件：
```bash
# 填写环境变量 (包含火山引擎与 OSS 密钥)
cp .env.example .env

# 配置要下载和转录的自媒体栏目
cp .pipeline/series_map.example.json .pipeline/series_map.json
cp .pipeline/youtube_sources.example.json .pipeline/youtube_sources.json
```

### 3. 一键运转

您可以通过单步脚本独立控制流程，也可以直接运行全自动一键流水线：

```bash
# 1. 运行核心一条龙转录流水线 (下载 -> 批量转录)
python3 scripts/run_full_pipeline.py --series example-series

# 2. 或者在服务器/本地挂起无人值守自动驾驶
python3 scripts/auto_run_pipeline.py --series example-series
```

---

## 📈 常用单步命令手册

| 功能描述 | 核心命令 | 核心产物 |
| :--- | :--- | :--- |
| **视频音频采集** | `python3 scripts/download_youtube.py` | 下载好的人声 MP3 音频文件 |
| **云端并发转录** | `python3 scripts/transcribe_batch.py --wait` | 火山 ASR 识别出的原始 JSON 并同步下载 |
| **长文稿生成** | 上方转录完成后自动合成 | `$DOCUMENT_ROOT/录音稿/<系列>/<音频名>.md` |
| **数据迁移升级** | `python3 scripts/migrate_open_source_layout.py` | 规范化并自动同步整理您的历史旧转录文稿 |

---

## 🛡️ 持续集成与质量保证

项目采用最严苛的代码规范与持续集成，每一次代码更改都会在 GitHub Actions 中自动运行测试。

您可以在本地激活虚拟环境并执行：
```bash
# 1. 运行核心转录与下载库测试套件 (80 个测试)
.venv312/bin/python3 -m unittest discover -s tests

# 2. 运行实验性 AI 撰稿子项目测试套件 (24 个测试)
.venv312/bin/python3 -m unittest discover -s experimental_llm_writer/tests
```

---

## 🏷️ 关于 Ordo Creator Suite

- **`Ordo Cast`** (本项目) ── 把音视频变成干净的 Markdown 录音稿
- **`Ordo Scribe`** (筹备中) ── 大模型高维语义长稿深度撰稿与智能拆稿器
- **`Ordo Publish`** (开发中) ── 跨社交平台多端本地优先一键分发助手

**在秩序中创作，在高效中分享。**
