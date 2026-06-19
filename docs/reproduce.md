# 复现说明

本文档说明如何在干净环境中复现 AFAC2026 Task2 复杂金融文档还原流程。工程只调用 FinixDoc-VL API，不接入其他外部大模型接口。

## 1. 环境准备

建议使用 Python 3.10 及以上版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. 配置凭据

复制 `.env.example` 为 `.env`，填入赛题提供的 FinixDoc-VL 调用信息。不要提交 `.env`。

```bash
cp .env.example .env
```

`.env` 示例结构：

```text
FINIX_API_KEY=填入赛题提供的值
FINIX_USER_IDS=finixA1001,finixB2002,finixC3003,finixD4004,finixE5005
FINIX_API_URL=https://finixdocapi.alipay.com/api/finix_doc/call_with_file
```

## 3. Dry-run 验证

Dry-run 不调用 API，只生成画像、切块、manifest、空结构 CSV 和质检记录，用于验证本地环境与目录配置。

```bash
python main.py \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  --output_csv outputs/dry_run/submission_A.csv \
  --work_dir outputs/dry_run \
  --config configs/default.yaml \
  --dry_run
```

## 4. A 榜运行命令

```bash
bash run.sh \
  "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images,data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  outputs/submission_A.csv \
  outputs/A \
  configs/default.yaml
```

生成结果：

- `outputs/submission_A.csv`：提交 CSV。
- `outputs/A/profiles/`：图片画像。
- `outputs/A/chunks/`：切块图片和 `manifest.json`。
- `outputs/A/api_raw/`：FinixDoc-VL 原始 Markdown 响应。
- `outputs/A/normalized/`：规范化中间结果。
- `outputs/A/merged/`：文件级合并 Markdown。
- `outputs/A/qc/`：单文件质检 JSON。
- `outputs/A/logs/`：运行日志和脱敏配置快照。

## 并发参数建议

- `runtime.image_concurrency` 控制同时处理的图片数量。
- `api.concurrency` 控制全局 FinixDoc-VL 请求数量上限。
- `api.per_user_concurrency` 控制单个 userId 的请求数量上限。

保守起步建议使用 `image_concurrency=2`、`api.concurrency=4`、`per_user_concurrency=1`。如果 `qc/summary.json` 中出现 `service_busy_html`、`api_failure_ratio_high` 或超时增多，先把 `image_concurrency` 降回 1，再降低 `api.concurrency`。

## 5. B 榜运行命令

B 榜目录发布后，替换输入目录即可，命令结构保持一致：

```bash
bash run.sh \
  "data/AFAC B榜评测数据集/finix_huge_long_rest_B/images,data/AFAC B榜评测数据集/finix_huge_table_rest_B/images" \
  outputs/submission_B.csv \
  outputs/B \
  configs/default.yaml
```

## 6. 本地训练集评估

```bash
python -m finix_restore.local_eval \
  --pred_dir outputs/train_long/merged \
  --gt_dir "data/AFAC 训练数据集/finixdocbench_huge_long_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_long_100/id_mapping.csv" \
  --output outputs/train_long/metrics/long_eval.json
```

## 7. 提交前检查

```bash
python -m pytest -q
git diff --check
python - <<'PY'
import pandas as pd
df = pd.read_csv("outputs/submission_A.csv")
assert list(df.columns) == ["file_name", "ground_truth"]
assert not df["file_name"].duplicated().any()
print(len(df))
PY
```

## 8. 审计说明

- `.env`、`outputs/`、API 缓存和日志不提交。
- 日志和配置快照中 `api_key` 必须脱敏。
- 不允许按测试集文件名硬编码输出、切块策略或拼接内容。
- 不允许调用 FinixDoc-VL 以外的大模型 API。
