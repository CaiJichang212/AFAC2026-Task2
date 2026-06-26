# # 跑全部评测数据（100张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
#   --work_dir outputs/run_A_full \
#   --output_csv outputs/run_A_full/submission_A_full.csv \
#   --config configs/default.yaml

# 跑小批量评测数据（每个目录前2张）
python -m finix_restore.cli \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
  --work_dir outputs/run_A_2_img-chunk-opt \
  --output_csv outputs/run_A_2_img-chunk-opt/submission_A_2_img-chunk-opt.csv \
  --limit_per_dir 2

# # 只跑长图数据集（50张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
#   --work_dir outputs/run_A_long \
#   --output_csv outputs/run_A_long/submission_A_long.csv \

# 只跑长图数据集（50张）
.venv/bin/python -m finix_restore.cli \
  --input_dir "data/AFAC A榜评测数据集/finix_huge_long_rest_A/images" \
  --work_dir outputs/long_eval_run_v2 \
  --output_csv outputs/long_eval_run_v2/submission_A_long_eval_run_v2.csv \
  --config configs/default.yaml \
  >outputs/long_eval_run_v2_stdout.log 2>&1 &

# # 只跑表格数据集（50张）
# python -m finix_restore.cli \
#   --input_dir "data/AFAC A榜评测数据集/finix_huge_table_rest_A/images" \
#   --work_dir outputs/run_A_table \
#   --output_csv outputs/run_A_table/submission_A_table.csv
