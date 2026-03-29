# 流水线加固与问题清零 — 设计说明与执行计划

**日期**：2026-03-29  
**状态**：已完成（按方案 B：P0 / P1 已落地；P2 中重复抽取与 JSON 容错等已做；**未纳入本次**：workflow 最小非法状态跳转校验、`task_logging` 批量写盘、`_poll_if_needed` 深度拆分，可单列迭代）  
**范围**：覆盖此前代码审查中列出的 P0 / P1 / P2 问题，分阶段自动化修复与验证。

---

## 1. 背景与目标

此前从架构、安全、稳定性、易用性等维度对 `tiandiworkspace` 媒体流水线做了审查，识别出若干必须修复与建议改进项。本 spec 的目标是在**不推翻现有三模块架构**的前提下，将问题**系统化清零**，并通过测试与验收标准保证可回归。

**成功标准（总）**

- 拆稿与规范化路径在真实 prompt 下可运行，不因 `str.format` 与花括号冲突而崩溃。
- `manifest.json` 写入具备原子性与崩溃可恢复性；HTTP 调用具备超时，避免无限挂死。
- 大文件与重复 SHA1 计算不会导致明显 OOM 或无谓全量 IO。
- 依赖可复现；README 可让新用户按步骤跑通。
- 测试不泄露真实密钥；关键路径有新增/补强测试。

---

## 2. 默认假设（因无法逐项追问）

若你审阅时未提出异议，实现阶段按以下假设执行：

| 假设 | 内容 |
|------|------|
| A1 | Python 目标版本为 **3.10+**（与当前类型标注习惯一致）。 |
| A2 | 火山/OSS 仍使用 **环境变量 + `.env`**，不引入 Keychain/Vault（可作为后续增强）。 |
| A3 | **不**在本次引入完整状态机库；采用 `Enum` + 集中校验函数，控制改动面。 |
| A4 | `migrate_open_source_layout.py` 的 `_cleanup_empty_dirs` 增加 **workspace 根边界**，不向上删过界。 |
| A5 | P2 项（日志 IO、方法过长拆分等）在时间与风险允许下**尽量做**，若篇幅过大则拆成 follow-up PR。 |

---

## 3. 方案对比（2～3 种）

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **A. 大爆炸** | 一次 PR 改完 P0～P2 全部 | 一次到位 | 评审难、回滚难、易引入回归 |
| **B. 分阶段（推荐）** | **阶段 1：P0** → **阶段 2：P1** → **阶段 3：P2** | 每阶段可独立测试与合并；风险可控 | 总周期略长 |
| **C. 仅安全与数据** | 只做 P0 + manifest 原子写 + 密钥清理 | 最快止血 | 性能与易用性问题遗留 |

**推荐：方案 B**。与你「自动化解决全部问题」的目标一致，同时保持可审阅、可回滚。

---

## 4. 技术设计（按子系统）

### 4.1 Prompt 渲染与 LLM 输出（P0）

**问题根因**：`str.format(**variables)` 与模板/用户内容中的 `{` `}` 冲突（`llm.py`、`prompts/split_wechat_articles.md`）。

**设计**：

- 将 `render_prompt` 改为**安全占位符替换**：仅替换已知键（如 `principles_text`、`issue_number`、`transcript_text`），使用 `string.Template` 或显式 `replace`，**禁止**对全文做 `str.format`。
- 模板文件中的 JSON 示例将 `{` `}` 改为双写 `{{` `}}` **或** 改为纯文字描述 + 占位符，二者选其一，以「渲染后内容与现在语义一致」为准。
- `complete_json` / `parse_article_drafts`：统一抽一层 **「剥离 code fence + 容错 JSON」** 的工具函数（处理大小写、首尾空白、简单前后缀说明）。

**验收**：新增/更新测试：用**真实** `prompts/split_wechat_articles.md` 片段做渲染测试；构造含 `{` 的 `transcript_text` 不崩溃。

---

### 4.2 Manifest 持久化（P0）

**设计**：

- `PipelineManifest.save()`：写入临时文件 → `os.replace` 原子替换目标路径；可选：写入前校验 JSON 序列化结果非空。
- `get()`：返回 **浅拷贝** `dict.copy()`，避免外部修改污染内部状态。

**验收**：单测模拟「写入中断」场景可用简化方式：先测 save 后文件完整可读；测修改 `get()` 返回值不影响 `entries`。

---

### 4.3 网络与转录 Provider（P0 / P1）

**设计**：

- 所有 `urllib.request.urlopen` 增加统一 **timeout**（建议常量在 `transcription.py` 或配置中，默认 60s，可测）。
- 音频哈希：对象键/hash 计算改为 **分块读取**（与 `workflow._audio_sha1` 一致），避免 `read_bytes()`。
- **workflow 层**：对同一 `source_path`，若 `audio_size` + `audio_mtime_ns` 与 manifest 中一致且已有 `audio_sha1`，则 **跳过** 全文件 SHA1 重算（manifest 需持久化上次元数据；首次或变化时重算）。

**验收**：单测 mock 文件大小/mtime 跳过逻辑；集成层面不强制真实网络。

---

### 4.4 工作流状态与健壮性（P1）

**设计**：

- 引入 **状态枚举**（或常量类）+ `assert_transition` 辅助函数；**最小集**：在 `upsert` 或关键路径校验非法跳转（先覆盖 completed/failed 等明显非法路径，避免过度工程）。
- `scanner`：`stat()` 包 `try/except FileNotFoundError`，跳过或记录该文件。
- `workflow`：`rename` 路径 TOCTOU：捕获 `FileNotFoundError`，记录日志并回退到预期路径逻辑。
- 日志时间：统一 **UTC** 或统一本地带时区，与 `manifest.updated_at` 策略一致（推荐 UTC）。

---

### 4.5 脚本易用性与错误处理（P1）

**设计**：

- `run_full_pipeline.py`：`run_step` 捕获 `CalledProcessError`，打印**步骤名称** + 非零退出码 + 简短说明，返回非 0 退出码。
- `transcribe_batch.py`：`main` 顶层捕获合理异常类型或 `Exception`，记录到 logger，避免裸 traceback（可选保留 `DEBUG` 开关打印 traceback）。
- `normalize_transcript.py`：无 LLM 时 **明确打印一行**「未配置 CONTENT_LLM_*，使用规则清洗」。

---

### 4.6 依赖与文档（P1）

**设计**：

- `requirements.txt`：锁定主版本或下限，例如 `openai>=1.0,<2`、`python-dotenv>=1.0` 等（以当前环境能 `pip install` 为准）。
- `README.md`：补充 Python 版本、`pip install -r requirements.txt`、ffmpeg / yt-dlp 说明、首次复制 `.env.example` → `.env`。

---

### 4.7 测试与安全清理（P0 / P1）

**设计**：

- `tests/test_transcribe_batch.py`：移除与真实密钥相同的字符串，改为假值。
- 审查其他测试文件中是否硬编码真实 bucket/endpoint（可保留公开 endpoint 若无害）。

---

### 4.8 P2 聚合（在阶段 3 处理）

- 抽取重复：`TRANSIENT_ERROR_KEYWORDS`、`strip_json_code_fence`、`filter_series` 到 `audio_pipeline` 或 `scripts/_common.py`。
- `youtube_downloader` 导入风格与 `sync_many` 异常范围收窄/补全。
- `task_logging`：可选批量写 summary（若改动大则记为后续迭代）。
- `article_splitter`：`allow_pending_review` 要么实现要么从 API 移除。

---

## 5. 执行计划（分阶段任务清单）

### 阶段 1 — P0 止血（优先合并）

| ID | 任务 | 主要文件 |
|----|------|----------|
| S1-1 | Prompt 安全渲染 + 模板修正 | `llm.py`, `prompts/split_wechat_articles.md`, `prompts/clean_transcript.md`（若同类问题） |
| S1-2 | Manifest 原子 save + get 拷贝 | `manifest.py` |
| S1-3 | urlopen 全局 timeout | `transcription.py` |
| S1-4 | 大文件哈希/上传改为分块或流式 | `transcription.py`, 与 workflow 对齐 |
| S1-5 | 测试密钥脱敏 | `tests/test_transcribe_batch.py` 等 |
| S1-6 | 新增/更新测试覆盖真实模板渲染 | `tests/` |

**阶段 1 完成定义**：`python3 -m unittest discover -s tests -v` 全绿；手动冒烟：渲染拆稿 prompt 无异常。

---

### 阶段 2 — P1 稳定性与体验

| ID | 任务 | 主要文件 |
|----|------|----------|
| S2-1 | workflow：基于 size+mtime 跳过 SHA1 重算 | `workflow.py`, manifest 字段 |
| S2-2 | scanner stat 容错 | `scanner.py` |
| S2-3 | 状态枚举/非法转换防护（最小集） | `workflow.py` 或新模块 |
| S2-4 | 时间戳统一 UTC | `workflow.py`, `normalization.py` 等 |
| S2-5 | run_full_pipeline / transcribe_batch 友好错误 | `scripts/*.py` |
| S2-6 | normalize 无 LLM 提示 | `normalize_transcript.py`, `ai_tasks.py` |
| S2-7 | requirements 锁定 + README 补齐 | `requirements.txt`, `README.md` |
| S2-8 | migrate 脚本 cleanup 目录边界 | `migrate_open_source_layout.py` |

---

### 阶段 3 — P2 代码质量与收尾

| ID | 任务 | 主要文件 |
|----|------|----------|
| S3-1 | 抽取重复常量与工具函数 | `audio_pipeline/`, `scripts/` |
| S3-2 | LLM JSON 解析容错增强 | `llm.py`, `article_splitter.py` |
| S3-3 | youtube_downloader 异常与导入风格 | `youtube_downloader.py` |
| S3-4 | `allow_pending_review` 处理 | `article_splitter.py` |
| S3-5 | 文档：本 spec 中「已实施」勾选 + 变更摘要 | 本文件或 `CHANGELOG` 片段 |

---

## 6. 测试策略

- **单元测试**：每个阶段合并前必须全量 unittest 通过。
- **回归测试**：重点覆盖 `render_prompt`、`manifest.save/load`、workflow reconcile（含跳过 SHA1）。
- **不提交**：含真实密钥的测试数据；`.env` 保持 gitignore。

---

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 模板改动导致 LLM 输出格式变化 | 保留旧模板备份于 git 历史；阶段 1 后做一次真实拆稿冒烟 |
| manifest 原子写与旧工具兼容性 | 仍输出同一 JSON schema |
| 依赖锁定导致某环境装不上 | 在 README 注明 Python 版本；必要时放宽上界 |

回滚：按 git 阶段提交 revert；manifest 格式不变则数据可恢复。

---

## 8. 审阅后下一步（流程）

1. 你审阅本 spec，直接在本文件顶部改「状态」或留言修改意见。  
2. 你确认后，执行阶段将按 **writing-plans** 产出更细的逐步实施清单（若需要），并**直接开始实现**阶段 1→3。  
3. 实现完成后，你只需拉代码 + 跑一次全量测试与一次端到端冒烟。

---

## 9. 需要你确认的一点（可异步回复）

**若只能先做其中一段**：是否同意 **默认优先完成阶段 1（P0）+ 阶段 2 中的 manifest/SHA1/README/依赖**，阶段 3 部分条目可拆到第二迭代？（默认：**同意**，除非你回复「必须一次做完 P2 全部」。）

---

*本文件由 brainstorming 流程产出，作为实现与验收的唯一对照 spec。*
