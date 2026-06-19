# Table chunk 像素预算实验脚本与命令清单

本目录配合 `docs/superpowers/plans/2026-06-19-image-chunking-optimization.md`
对应的 P1 反馈“表格 chunk 真实耗时偏高”，提供一组**只读、可重复**的实验入口，
用来验证 `chunk.table.target_pixels` 在 6M / 5M / 4M 三档下：

- dry-run 阶段 chunks 数、`max_chunk_pixels`、`over_safe_chunks`、`over_hard_chunks`
- API 小批量阶段单请求 elapsed_ms 分布与分桶总耗时

实验**不修改** `data/`、不打印 `.env`、不改主代码、产物全部落在 `outputs/chunk_budget/`。

## 0. 前置约束

- 主代码不动。三档目标像素通过专用 YAML 覆盖。
- `data/` 视为只读输入，命令里只用 `--input_dir` 指向其下。
- 产物目录全部位于 `outputs/chunk_budget/<phase>/<budget>/`，可随时整目录删除。

## 1. 文件清单

- `configs/budget_6m.yaml`：等价当前默认（target=6M, safe=8M）。
- `configs/budget_5m.yaml`：target=5M, safe=7M。
- `configs/budget_4m.yaml`：target=4M, safe=6M。
- `aggregate_dry_run.py`：扫 `chunks/*/manifest.json` + `qc/*.json`，按 doc_type 分桶汇总。
- `aggregate_api_elapsed.py`：扫 `logs/run.jsonl`，按 doc_type 分桶统计 elapsed_ms。
- `run_dry_run_all.sh`：一键跑训练集 long+table、A 榜 long+table 的 dry-run（三档）。
- `run_api_smoke.sh`：在 A 榜 table 上抽样跑真实 API（默认两档：6M 对照 + 一档候选）。

## 2. 实验阶段一：dry-run（只切片，不调 API）

执行：

```bash
bash scripts/chunk_budget_experiment/run_dry_run_all.sh
```

完成后产物布局：

```
outputs/chunk_budget/dry_run/
  6m/{train,a_list}/{long,table}/{chunks,profiles,qc,merged}
  5m/{train,a_list}/{long,table}/...
  4m/{train,a_list}/{long,table}/...
```

汇总：

```bash
python scripts/chunk_budget_experiment/aggregate_dry_run.py \
  --root outputs/chunk_budget/dry_run \
  --out  outputs/chunk_budget/dry_run/summary.csv
```

输出 CSV 列：`budget,dataset,doc_type,files,chunks_total,chunks_p50,chunks_p95,
max_chunk_pixels,over_safe_total,over_hard_total`，决策依据：
- `chunks_total` 增长比例 vs 预期单请求耗时下降比例
- `over_hard_total` 必须为 0
- `over_safe_total` 应当随预算下调而下降到 0

## 3. 实验阶段二：API 小批量对比（只在 A 榜 table 上抽样）

⚠ 需要 `.env` 已配置 `FINIX_API_KEY` / `FINIX_USER_IDS`。
样本量、抽样档位见脚本头部变量，**默认仅消耗少量 API 配额**。

```bash
bash scripts/chunk_budget_experiment/run_api_smoke.sh
```

汇总：

```bash
python scripts/chunk_budget_experiment/aggregate_api_elapsed.py \
  --root outputs/chunk_budget/api_smoke \
  --out  outputs/chunk_budget/api_smoke/summary.csv
```

输出 CSV 列：`budget,doc_type,requests,elapsed_sum_s,elapsed_p50_ms,
elapsed_p95_ms,elapsed_max_ms,fail_requests`。

决策口径：
- 比较 `elapsed_sum_s`（总耗时账）：若降档后 sum 明显更低，可在主配置切换。
- 比较 `elapsed_max_ms`：单请求 P95 应明显下降（目前 76.8s 的尾巴是优化目标）。
- 若失败率显著上升或 `requests` 增加但 sum 反而上涨，保留 6M。

## 4. 退出条件

- 三档 dry-run 全部 `over_hard_chunks == 0`。
- API 小批量阶段无新增鉴权/超时错误。
- 选定档位写入 `configs/default.yaml.table.target_pixels/safe_max_pixels`，
  其余产物可整目录清理：`rm -rf outputs/chunk_budget/`。
