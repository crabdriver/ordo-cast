# 全自动媒体流水线

这个仓库提供一条可本地运行的内容流水线：`下载 YouTube 音频 -> 云端转录 -> 长稿规范化 -> 拆成公众号文章`。

## 开源边界

仓库只保留通用代码、测试、提示词和 `example` 模板。

以下内容都属于本地运行态，不应提交：

- `.pipeline/series_map.json`
- `.pipeline/youtube_sources.json`
- `.pipeline/manifest.json`
- `.pipeline/logs/`
- `.pipeline/raw_transcripts/`
- 你的本地原则文件
- `DOCUMENT_ROOT` 下的全部文稿输出

## 环境与依赖

- **Python 3.10+**（推荐；与仓库中类型标注习惯一致）。
- 安装 Python 依赖（建议在虚拟环境中执行）：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

- **ffmpeg**：YouTube 下载与部分音频处理依赖系统可用的 `ffmpeg`（macOS 常用 `brew install ffmpeg`；其他平台请从 [ffmpeg.org](https://ffmpeg.org) 安装并确保在 `PATH` 中）。
- **yt-dlp**：由 `requirements.txt` 安装；流水线脚本会调用项目环境中的 `yt-dlp`。

## 本地准备

1. 复制并填写环境变量模板。

```bash
cp .env.example .env
```

2. 准备本地系列配置和 YouTube 来源配置。

```bash
cp .pipeline/series_map.example.json .pipeline/series_map.json
cp .pipeline/youtube_sources.example.json .pipeline/youtube_sources.json
```

3. 把你的拆稿原则保存到本地路径。

- 默认路径：`${DOCUMENT_ROOT:-$HOME/文稿}/本地配置/文章拆解核心原则与心法.md`
- 可参考模板：`prompts/article_principles.example.md`

## 关键配置

- `DOCUMENT_ROOT`：统一文稿根目录，默认是 `$HOME/文稿`
- `ARTICLE_PRINCIPLES_PATH`：拆稿原则文件路径，不设置时走默认路径
- `VOLCENGINE_*`：火山 ASR 配置
- `OSS_*`：阿里云 OSS 配置
- `CONTENT_LLM_*`：正文清洗和拆稿用的 LLM 配置

## 输出结构

- 转录长稿：`$DOCUMENT_ROOT/录音稿/<系列>/<期号_标题>.md`
- 拆解文章：`$DOCUMENT_ROOT/拆解文章/<系列>/<期号_标题>/<期号-文章序号_标题>.md`
- 运行态：仓库内 `.pipeline/`

## 常用命令

下载指定系列：

```bash
python3 scripts/download_youtube.py --series tiandi
```

批量转录并等待完成：

```bash
python3 scripts/transcribe_batch.py --wait --series tiandi
```

规范化转录稿：

```bash
python3 scripts/normalize_transcript.py --series tiandi
```

自动拆稿：

```bash
python3 scripts/split_to_wechat_articles.py --series tiandi
```

拆稿行为说明：

- **待复核**：manifest 中 `review_status=pending` 时，默认**跳过**拆稿；若要对未复核长稿拆稿，请加 `--allow-pending-review`（全链路 `run_full_pipeline.py` 亦支持同名参数）。
- **固定篇数**：需要每期恰好拆成 14 篇时，可在 `.env` 设置 `EXPECTED_ARTICLES_PER_TRANSCRIPT=14`，或运行 `split_to_wechat_articles.py --expected-articles 14`。篇数与模型输出不一致时会自动重试；最终仍不一致则报错且**不写入**文章文件。
- **残留旧稿**：若磁盘上存在残留或部分旧拆稿目录，脚本会自动归档到 `.pipeline/recovery/articles/` 后重试，而不是直接要求人工清理。

一条命令跑完整链路：

```bash
python3 scripts/run_full_pipeline.py --series tiandi
```

如果你想用“一次性完整链路”直接走全自动语义：

```bash
python3 scripts/run_full_pipeline.py --series tiandi --full-auto --expected-articles 14
```

其中 `--full-auto` 会自动把拆稿阶段切到 `--allow-pending-review`，避免因为 `review_status=pending` 被静默跳过。

无人值守自动驾驶入口：

```bash
python3 scripts/auto_run_pipeline.py --series tiandi --expected-articles 14
```

`auto_run_pipeline.py` 会循环执行下载、转录、规范化、拆稿，并在以下场景退出：

- `0`：本轮已收敛，转录/规范化/拆稿都到达可接受终态。
- `3`：流程仍未完全收敛，但连续多轮无进展或达到最大自动驾驶轮次。
- `2`：存在明确失败（配置错误、下载失败、转录失败、拆稿失败等）。

## 迁移旧数据

如果你之前把转录稿和拆稿文章放在仓库里，先运行：

```bash
python3 scripts/migrate_open_source_layout.py --workspace-root .
```

这个脚本会做三件事：

- 把旧的转录稿迁到 `$DOCUMENT_ROOT/录音稿/...`
- 把旧的拆稿文章迁到 `$DOCUMENT_ROOT/拆解文章/<系列>/<源录音稿文件夹>/...`
- 把仓库根下的 `00_文章拆解核心原则与心法.md` 复制到新的本地原则路径

## 持续集成

若仓库托管在 GitHub 并已启用 Actions，推送到 `master` / `main` 或打开针对这些分支的 PR 时，会在 Python 3.10、3.11、3.12 下自动运行 `python -m unittest discover -s tests`。

## 变更记录

见仓库根目录 [`CHANGELOG.md`](CHANGELOG.md)。

## 验证建议

1. 先只跑一个系列，确认新文件已经落到 `文稿/` 下。
2. 再重跑一次同一系列，确认不会因为路径迁移而重复生成混乱文件。
3. 最后再放开全部系列执行总控脚本或 `auto_run_pipeline.py`。
