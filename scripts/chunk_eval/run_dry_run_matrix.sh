#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

OUT_ROOT="${REPO_ROOT}/outputs/chunk_eval/s1_dry_run"
CFG_ROOT="${REPO_ROOT}/scripts/chunk_eval/configs"

TRAIN_LONG="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_long_100/images"
TRAIN_TABLE="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_table_100/images"

declare -a CONFIGS=(
  "baseline_5m"
  "table_4m_safe"
  "balanced_6m"
  "long_4m_table_4m"
  "large_8m_probe"
)

for name in "${CONFIGS[@]}"; do
  cfg="${CFG_ROOT}/${name}.yaml"
  for subset in long table; do
    if [[ "${subset}" == "long" ]]; then
      input_dir="${TRAIN_LONG}"
    else
      input_dir="${TRAIN_TABLE}"
    fi
    work_dir="${OUT_ROOT}/${name}/${subset}"
    echo "=== dry-run config=${name} subset=${subset} ==="
    mkdir -p "${work_dir}"
    python -m finix_restore.cli \
      --input_dir "${input_dir}" \
      --output_csv "${work_dir}/submission.csv" \
      --work_dir "${work_dir}" \
      --config "${cfg}" \
      --dry_run
  done
done

python scripts/chunk_budget_experiment/aggregate_dry_run.py \
  --root "${OUT_ROOT}" \
  --out "${OUT_ROOT}/summary.csv"

echo "Dry-run matrix complete: ${OUT_ROOT}/summary.csv"
