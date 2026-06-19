#!/usr/bin/env bash
# scripts/chunk_budget_experiment/run_dry_run_all.sh
# Run dry-run chunking for 6M / 5M / 4M table budgets across:
#   - data/AFAC 训练数据集/finixdocbench_huge_long_100/images
#   - data/AFAC 训练数据集/finixdocbench_huge_table_100/images
#   - data/AFAC A榜评测数据集/finix_huge_long_rest_A/images
#   - data/AFAC A榜评测数据集/finix_huge_table_rest_A/images
#
# Read-only: only --input_dir into data/, all artifacts under outputs/chunk_budget/.
# No FINIX_API_KEY required (--dry_run skips API).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

OUT_ROOT="${REPO_ROOT}/outputs/chunk_budget/dry_run"
SCRIPT_CFG="${REPO_ROOT}/scripts/chunk_budget_experiment/configs"

TRAIN_LONG="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_long_100/images"
TRAIN_TABLE="${REPO_ROOT}/data/AFAC 训练数据集/finixdocbench_huge_table_100/images"
A_LONG="${REPO_ROOT}/data/AFAC A榜评测数据集/finix_huge_long_rest_A/images"
A_TABLE="${REPO_ROOT}/data/AFAC A榜评测数据集/finix_huge_table_rest_A/images"

# dataset_label : path
declare -a DATASETS=(
  "train_long|${TRAIN_LONG}"
  "train_table|${TRAIN_TABLE}"
  "a_long|${A_LONG}"
  "a_table|${A_TABLE}"
)

for budget in 6m 5m 4m; do
  cfg="${SCRIPT_CFG}/budget_${budget}.yaml"
  for entry in "${DATASETS[@]}"; do
    label="${entry%%|*}"
    path="${entry#*|}"
    work_dir="${OUT_ROOT}/${budget}/${label}"
    output_csv="${work_dir}/submission.csv"
    echo "=== dry-run budget=${budget} dataset=${label} ==="
    mkdir -p "${work_dir}"
    python -m finix_restore.cli \
      --input_dir "${path}" \
      --output_csv "${output_csv}" \
      --work_dir "${work_dir}" \
      --config "${cfg}" \
      --dry_run
  done
done

echo
echo "All dry-runs done. Aggregate with:"
echo "  python scripts/chunk_budget_experiment/aggregate_dry_run.py \\"
echo "    --root ${OUT_ROOT} --out ${OUT_ROOT}/summary.csv"
