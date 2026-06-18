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
