#!/usr/bin/env bash
# scripts/chunk_budget_experiment/run_api_smoke.sh
# Small-batch API comparison on A-list table samples.
# Default: 5 files per budget, 6M baseline + 4M candidate. Set BUDGETS / SAMPLE_N
# via env vars if you want a different mix.
#
# Requires FINIX_API_KEY / FINIX_USER_IDS in .env. Does NOT print secrets.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

OUT_ROOT="${REPO_ROOT}/outputs/chunk_budget/api_smoke"
SCRIPT_CFG="${REPO_ROOT}/scripts/chunk_budget_experiment/configs"
A_TABLE="${REPO_ROOT}/data/AFAC A榜评测数据集/finix_huge_table_rest_A/images"

BUDGETS="${BUDGETS:-6m 4m}"
SAMPLE_N="${SAMPLE_N:-5}"

for budget in ${BUDGETS}; do
  cfg="${SCRIPT_CFG}/budget_${budget}.yaml"
  work_dir="${OUT_ROOT}/${budget}/a_table"
  output_csv="${work_dir}/submission.csv"
  echo "=== api smoke budget=${budget} samples=${SAMPLE_N} ==="
  mkdir -p "${work_dir}"
  python -m finix_restore.cli \
    --input_dir "${A_TABLE}" \
    --output_csv "${output_csv}" \
    --work_dir "${work_dir}" \
    --config "${cfg}" \
    --limit_per_dir "${SAMPLE_N}" \
    --no-resume \
    --force_api
done

echo
echo "API smoke done. Aggregate with:"
echo "  python scripts/chunk_budget_experiment/aggregate_api_elapsed.py \\"
echo "    --root ${OUT_ROOT} --out ${OUT_ROOT}/summary.csv"
