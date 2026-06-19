# # 跑全部评测数据（100张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
#   --work_dir outputs/run_A_full \
#   --output_csv outputs/run_A_full/submission_A_full.csv \
#   --config configs/default.yaml

# 跑 smoke（每个目录前5张）
python -m finix_restore.cli \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  --work_dir outputs/run_A_smoke \
  --output_csv outputs/run_A_smoke/submission_A_smoke.csv \
  --limit_per_dir 5

# # 只跑长图数据集（50张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
#   --work_dir outputs/run_A_long
#   --output_csv outputs/run_A_long/submission_A_long.csv \

# # 只跑表格数据集（50张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
#   --work_dir outputs/run_A_table
#   --output_csv outputs/run_A_table/submission_A_table.csv \
