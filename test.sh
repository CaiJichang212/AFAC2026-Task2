# 跑全部训练数据（100张）
python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --work_dir outputs/table_train_run_v2 \
  --output_csv outputs/table_train_run_v2/submission_A_table_train_run_v2.csv \
  --config configs/table_v2.yaml \
  > outputs/table_train_run_v2.log 2>&1 &
