# 消融实验记录

本文件用于记录 Task2 复杂金融文档还原流程的可复现实验。每次实验应保留配置快照、运行目录、提交 CSV 和本地评估 JSON，避免只记录主观观察。

## 记录模板

| 实验ID | 日期 | 输入目录 | 配置文件 | work_dir | 提交CSV | 评估JSON | 切块策略 | API并发 | 后处理 | 失败数 | 主要观察 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_full |  |  | configs/default.yaml | outputs/baseline_full | outputs/baseline_full/submission.csv | outputs/baseline_full/metrics/local_eval.json | 整图优先 | 1 | 无 |  |  |
| long_slide_v1 |  |  | configs/long_strip.yaml | outputs/long_slide_v1 | outputs/long_slide_v1/submission.csv | outputs/long_slide_v1/metrics/local_eval.json | 固定纵向滑窗 | 2 | 基础拼接 |  |  |
| long_slide_v2 |  |  | configs/long_strip.yaml | outputs/long_slide_v2 | outputs/long_slide_v2/submission.csv | outputs/long_slide_v2/metrics/local_eval.json | 空白线纵向滑窗 | 2 | 去重+目录保护 |  |  |
| table_grid_v1 |  |  | configs/table_grid.yaml | outputs/table_grid_v1 | outputs/table_grid_v1/submission.csv | outputs/table_grid_v1/metrics/local_eval.json | 固定二维网格 | 1 | HTML修复 |  |  |
| table_grid_v2 |  |  | configs/table_grid.yaml | outputs/table_grid_v2 | outputs/table_grid_v2/submission.csv | outputs/table_grid_v2/metrics/local_eval.json | 投影辅助网格 | 1 | 行级拼接+HTML修复 |  |  |
| quality_retry_v1 |  |  | configs/default.yaml | outputs/quality_retry_v1 | outputs/quality_retry_v1/submission.csv | outputs/quality_retry_v1/metrics/local_eval.json | 按风险重跑 | 1-4 | 质量门禁重跑 |  |  |

## 本地评估命令

```bash
python -m finix_restore.local_eval \
  --pred_dir outputs/train_long/merged \
  --gt_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_long_100/id_mapping.csv" \
  --output outputs/train_long/metrics/long_eval.json
```

## 记录要求

- `输入目录` 写完整目录，多个目录用逗号分隔。
- `work_dir` 必须对应本次实际运行目录，避免复用旧缓存时无法审计。
- `提交CSV` 必须是本次实验实际生成并回读通过的文件。
- `评估JSON` 必须由 `finix_restore.local_eval` 生成。
- `主要观察` 记录可执行结论，例如接缝重复、表格错列、API 超时比例，而不是泛泛描述。

## 2026-06-23 训练集切图评估

- 设计文档：`docs/superpowers/specs/2026-06-23-chunking-evaluation-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-23-chunking-evaluation-execution.md`
- 最终报告：`outputs/chunk_eval/final_report.md`
- 关键产物：`outputs/chunk_eval/s0_profile/train_profile.csv`、`outputs/chunk_eval/s1_dry_run/summary.csv`、`outputs/chunk_eval/s2_api_ablation/s2_metrics_summary_fresh.md`
- 当前结论：全量 dry-run 支持 `balanced_6m` 作为下一阶段 table 基线；API partial 显示 table HTML 结构稳定性和表格合并仍是进入全量训练集评分前的 P0 风险。

## 2026-06-23 A榜 balanced_6m 全量预测

- 输入目录：`data/AFAC A榜评测数据集/finix_huge_long_rest_A/images`、`data/AFAC A榜评测数据集/finix_huge_table_rest_A/images`
- 配置文件：`scripts/chunk_eval/configs/balanced_6m.yaml`
- work_dir：`outputs/a_eval/balanced_6m_full`
- 提交 CSV：`outputs/a_eval/balanced_6m_full/submission_A_balanced_6m_from_merged.csv`
- 风险清单：`outputs/a_eval/balanced_6m_full/risk_summary.md`
- 主要观察：A榜 100 张均生成 merged；CLI 因质量门未直接写 CSV，原因是 table 样本存在 `html_broken` 和 `high_duplication` 风险；最终提交 CSV 从 merged 结果组装，并通过列名、行数、空输出和重复文件名校验。
