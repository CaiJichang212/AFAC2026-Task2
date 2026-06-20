# 官方对齐的离线自动化评测系统设计

## 背景

AFAC2026 Task2 线上自动化评测从三个维度综合裁决并给出 Overall 得分（满分 100）：

```
Overall = [ (1 - Text Edit) * 100 + Table TEDS + (1 - Read Order Edit) * 100 ] / 3
```

当前仓库已有 `finix_restore/local_eval.py`，但它只计算原始全文 normalized 编辑距离，
缺失官方三项核心指标（Text Edit 归一化口径、Table TEDS、Read Order Edit）与 Overall 公式，
且输入读取的是 `.md` 目录，而官方提交/GT 是 CSV（`file_name`, `ground_truth`）。

本设计新增一个与官方口径对齐的离线评测系统，用于在 A 榜本地复现线上打分，
辅助调参与回归，不接入线上、不依赖外部大模型。

## 目标

- 复现官方 Overall 三项指标：Text Edit、Table TEDS、Read Order Edit，并按官方公式合成 Overall。
- 输入对齐官方 CSV 格式（`file_name`, `ground_truth`），同时兼容 `id_mapping.csv + mds/` 目录的训练集 GT。
- 提供独立 CLI，跑完预测后手动算分；不绑定主 pipeline，职责清晰、可单测。
- 输出每文件明细 + 数据集汇总，写入 JSON 报告并打印汇总。

## 范围

- 纳入：评测打分逻辑、CSV/目录读取与文件名对齐、指标实现、CLI、单元测试。
- 不纳入：修改主 pipeline 自动触发评测、改动 `data/` 原始数据、调用任何外部模型 API。
- 保留：现有 `local_eval.py` 与其测试不变，新系统作为独立模块共存。

## 架构

新增独立评测包，按职责拆分小模块，互相通过明确接口通信，可独立理解与单测：

```
finix_restore/eval/
  __init__.py
  io.py            # 读取预测/GT（CSV 或 id_mapping+mds 目录），按 file_name 对齐成 (pred, gt) 对
  text_metric.py   # Text Edit：文本归一化 + 字级 Levenshtein 归一化损失，结果 ∈ [0,1]
  tables.py        # 从 Markdown/HTML 抽取表格并解析为带 colspan/rowspan 的节点树
  table_teds.py    # Table TEDS：基于 apted 求树编辑距离 → 归一化为 [0,100]
  reading_order.py # Read Order Edit：逻辑块切分 → 块级序列 Levenshtein 归一化，结果 ∈ [0,1]
  scorer.py        # 组合三指标 → Overall，聚合每文件明细 + 数据集汇总
  cli.py           # 命令行入口
```

## 数据流

1. `io.load_pairs(pred, gt, mapping)`：读取预测与 GT，输出对齐后的 `[(file_name, pred_text, gt_text)]`。
   - 预测：官方 CSV（`file_name`, `ground_truth`）。
   - GT：官方 CSV，或训练集 `id_mapping.csv + mds/`（uuid.md）；用 mapping 将 afts_id/uuid 对齐。
   - 记录缺失 GT、缺失预测的样本到报告，不静默丢弃。
2. 对每个 `(pred_text, gt_text)`：
   - `text_metric.text_edit(pred, gt)` → Text Edit ∈ [0,1]
   - `table_teds.table_teds(pred, gt)` → Table TEDS ∈ [0,100] 或 `None`（双方无表格）
   - `reading_order.read_order_edit(pred, gt)` → Read Order Edit ∈ [0,1]
3. `scorer` 套用公式得每文件 Overall；数据集层面：
   - Text Edit / Read Order Edit / Overall 取所有样本均值。
   - Table TEDS 仅在「含表样本」上取均值（见决策）。

## 指标实现细节

### Text Edit
- 文本归一化：统一换行/空白，去除首尾空白；默认贴近原文，不做激进 Markdown 清洗。
- 计算字级 Levenshtein 距离，除以 `max(1, len(gt))` 归一化。值越低越好。

### Table TEDS
- 表格抽取：
  - HTML `<table>...</table>` 直接解析（复用已有 `beautifulsoup4`/`lxml`）。
  - Markdown pipe 表格先转成等价 `<table>` 再解析。
- 树结构：节点保留标签（table/tr/td/th）、`colspan`/`rowspan`、单元格归一化文本。
- 距离：使用 `apted`（新增依赖）计算两棵树的编辑距离，按 TEDS 标准归一化：
  `TEDS = (1 - EditDist / max(|T_pred|, |T_gt|)) * 100`。
- 多表：按出现顺序一一配对，逐表 TEDS 后平均；表数量不一致的多余表按 0 计入平均。

### Read Order Edit
- 块切分：按标题（`#`~`######`）、表格块、列表块、空行分隔的段落切分为逻辑块序列。
- 每个块取归一化「身份签名」（如块类型 + 文本前缀/哈希）形成 token 序列。
- 对 pred 块序列与 gt 块序列做 token 级 Levenshtein，除以 `max(1, gt 块数)` 归一化。值越低越好。

### Scorer 输出
- 每文件：`file_name, text_edit, table_teds, read_order_edit, overall, has_table`。
- 汇总：`mean_text_edit, mean_table_teds(含表样本), mean_read_order_edit, mean_overall, file_count, missing_*`。
- 写 JSON 报告（沿用现有 `metrics.json` 习惯），并在 CLI 打印简表。

## 关键决策

- **输入格式**：以官方 CSV 为准，同时兼容训练集 `id_mapping.csv + mds/` 目录。
- **TEDS 实现**：复用现成库，新增 `apted` 依赖；表格解析复用 bs4/lxml。
- **无表样本**：Table TEDS 仅让「含表样本」参与均值；无表样本不拉高/拉低该项均值。
  单文件层面，双方都无表时该项记为 `None`（不参与 Overall 的该文件计算口径见下）。
- **集成范围**：独立评测模块 + CLI，不绑定主 pipeline。

### Overall 中无表样本的处理
- 官方公式三项等权。对无表样本，沿用「该项满分」最贴近线上对无表文档不惩罚的直觉：
  单文件 Overall 计算时，无表样本 Table TEDS 视为 100；
  数据集 `mean_table_teds` 仅统计含表样本以反映真实表格能力。
- 该口径在报告中显式标注，便于人工对照线上分。

## 错误处理

- 缺失 GT / 缺失预测：记入报告 `missing_gt` / `missing_pred`，不计入均值。
- 表格解析失败：该表 TEDS 记 0 并在报告标注，不中断整体评测。
- CSV 不可读 / 列名不符：CLI 报错并非零退出，提示具体问题。

## 测试

新增 `tests/test_eval_*.py`，覆盖：
- `io`：CSV 读取、id_mapping 对齐、缺失项记录。
- `text_metric`：已知字符串的归一化编辑距离数值。
- `tables` / `table_teds`：相同表 TEDS=100、单元格差异、colspan/rowspan、Markdown→HTML 解析。
- `reading_order`：相同顺序=0、块换位的归一化距离。
- `scorer`：Overall 公式数值、无表样本均值口径。

## 复用与依赖

- 复用：`beautifulsoup4`、`lxml`（已在 requirements）。
- 新增：`apted`（写入 requirements.txt）。

## 验证

- `pytest -q` 全绿（含新增评测测试，且不破坏现有 `test_local_eval.py`）。
- 在 A 榜训练集（含 GT）上用一份手工/已有预测 CSV 跑通 CLI，检查报告字段完整、数值合理。
