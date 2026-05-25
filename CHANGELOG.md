# 变更摘要

## 未发布（main）

### 拆稿与配置

- 待复核（`review_status=pending`）默认不拆稿；`--allow-pending-review` 放行。
- 固定篇数：`EXPECTED_ARTICLES_PER_TRANSCRIPT` / `--expected-articles`；与模型输出不一致时有限重试，最终仍失败则不写稿。
- 提示词支持 `{expected_articles_constraint}` 硬性篇数说明。
- `partial` 与磁盘残留旧稿目录会自动归档到 `.pipeline/recovery/articles/` 后重试，减少人工清理。

### 稳定性与代码质量

- **task_logging**：`events.jsonl` 仍逐条追加；`summary` / `latest_status` 每 10 条事件批量写盘，`finish` 时必定写全。
- **workflow**：轮询逻辑拆为 `_handle_poll_*` 小函数，便于阅读与单测。
- **youtube_downloader**：`sync_many` 除 `CalledProcessError` 外捕获 `OSError`（含磁盘权限、重命名失败等）。
- **退出语义**：`transcribe_batch.py` 区分 `all_done / incomplete / failed`；`run_full_pipeline.py` 不再把未收敛转录当作成功继续下游。
- **自动驾驶**：新增 `scripts/auto_run_pipeline.py`，可循环续跑下载、转录、规范化、拆稿并输出汇总状态。

### 数据与校验

- **manifest**：转录 `status` 非法跳转校验（`manifest_state`）。
- **CI**：GitHub Actions 在 Python 3.10–3.12 下跑 `unittest`。
