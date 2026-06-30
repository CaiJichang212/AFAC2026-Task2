# table_train_run_1 评分分析与优化方案

> 评估对象：`outputs/table_train_run_1/submission_A_table_train_run_1.csv`（100 个 huge_table 样本）
> 评估口径：`finix_restore.eval`（Text Edit / Table TEDS / Read Order Edit 三项，overall = 三项均值）
> GT 来源：`data/AFAC 训练数据集/finixdocbench_huge_table_100/mds/`（100 份 `<uuid>.md`）
> 评分产物：`outputs/table_train_run_1/metrics/table_eval.json`
> 生成日期：2026-06-30

---

## 一、评分结果总览

| 指标 | 值 | 说明 |
|---|---|---|
| file_count | 100 | 全部匹配，无 missing |
| table_sample_count | 100 | 100% 含表 |
| **mean Text Edit** | **0.9820** | 越低越好；接近 1 表示文本几乎完全不一致 |
| **mean Table TEDS** | **20.76 / 100** | 越高越好；中位数仅 4.1，极差 |
| **mean Read Order Edit** | **5.5787** | 越低越好；>1 即异常（见下） |
| **Overall** | **-145.10** | 负分，三项同时崩坏 |

### 1.1 分布统计（百分位）

| 指标 | min | p25 | 中位 | p75 | max | mean |
|---|---|---|---|---|---|---|
| text_edit | 0.017 | 0.358 | 0.829 | 0.882 | **26.18** | 0.982 |
| table_teds | 0.0 | 1.032 | 4.101 | 30.649 | 99.326 | 20.763 |
| read_order_edit | 0.4 | 1.0 | 1.0 | 1.0 | **309.58** | 5.579 |
| overall | -10281.74 | 2.205 | 7.043 | 24.811 | 72.426 | -145.10 |

### 1.2 TEDS 分桶

- `teds == 0`：**2 / 100**（完全失败）
- `teds < 50`：**80 / 100**（80% 样本表格结构基本不达标）
- `teds >= 90`：**1 / 100**（仅 1 个样本接近完美）

### 1.3 关键结论

> **这不是"分数偏低"，而是系统性结构失败**：80% 样本 TEDS < 50，三项指标同时异常，Overall 出现负分。问题不在"识别精度"边缘误差，而在**表格切分-合并链路的结构性破坏**与**评分器归一化缺陷**双重叠加。

---

## 二、瓶颈定位（按影响权重排序）

### 瓶颈 A：表格合并失败 —— Table TEDS 与 Read Order 的头号杀手

**实证**：低分样本 `0e8a501f-458e-...`（teds=0.1, roe=8.86）
- pred 把同一张表切成了 **33 个独立 `<table>` 块**，GT 只有 **1 个**。
- pred 198154 字符 vs GT 51395 字符（3.8 倍冗余）。
- 根因：`table_rowband_v2` 策略对超宽/超高大表做了多次切分，但 `TableRowAssembler` 没能把多 chunk 表拼回单表，输出散落 33 个表块。
- 连锁影响：`read_order_edit` 用 `distance / len(gt_blocks)`，pred 的 33 个表块 vs GT 的 1 个表块，编辑距离爆炸 → roe=8.86（远超 1）。

**质检佐证**：`qc/summary.json` 中 `2358594b-...jpg` 明确标注 `empty_output` + `api_failure_ratio_high`（4 chunk 中 3 个失败，api_failure_ratio=0.75），table_assembled_tables=0。被切分的 `06364357`、`a44505fa` 均出现 `html_broken` 装配警告。

**代码定位**：
- [finix_restore/table_assembler.py:138-162](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py#L138) `_assemble_row_band`：仅当所有 chunk「每个恰好含 1 个表 + 行数完全一致」才横向缝合，否则返回 `None` → 退化为 fallback（各自独立 `<table>`）。
- [finix_restore/table_assembler.py:164-182](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py#L164) `_align_by_anchor`：要求行数严格相等 + 首列相似度 ≥0.90，大表跨块行数常因表头重复/分页不一致而失败。
- 一旦任一 band 装配失败，整组走 fallback，**多个 chunk 表原样并列输出**，TEDS 归零。

### 瓶颈 B：评分器归一化缺陷 —— Overall 负分的直接成因

**实证**：text_edit max=26.18、read_order_edit max=309.58，均远超 1.0。

**代码定位**：
- [finix_restore/eval/text_metric.py:31](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/text_metric.py#L31)：`return distance / max(1, len(gt_norm))` —— 分母用 GT 长度，pred 远长于 GT 时比值 >1。
- [finix_restore/eval/reading_order.py:65](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/reading_order.py#L65)：`return distance / max(1, len(gt_blocks))` —— 同样问题。
- [finix_restore/eval/scorer.py:18](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/scorer.py#L18)：`overall = ((1-te)*100 + teds + (1-roe)*100)/3`，te/roe >1 时 `(1-te)`、`(1-roe)` 为大负数 → overall 被拉到 -10281。

> 注意：评分器是赛题方提供的固定口径，**不能改评分器**。但这解释了为何 overall 如此极端——它放大了结构失败的成本。优化方向必须把 te/roe 压回 [0,1] 区间，即让 pred 长度/块数贴近 GT。

### 瓶颈 C：API 失败导致单文件空产出 —— 确定性失分

**实证**：`2358594b-...jpg` 的 `chars=0`、`failed_chunks=3/4`、`api_failure_ratio=0.75`。该样本三项指标全为最差（te=1.0, teds=0, roe=1.0, overall=0），单项拉低均值。

### 瓶颈 D：表格属性与列对齐细节缺失 —— TEDS 中段的次要损耗

**实证**：相对高分样本 `b44312da-...`（teds=40.5）仍 te=1.3：
- pred `<table>` 无属性，GT 为 `<table border="1" cellpadding="8" cellspacing="0">`（评分器 [tables.py:33-47](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/tables.py#L33) 解析时忽略属性，此项不损 TEDS，但损 text_edit）。
- pred 每行比 GT 少一个尾部空 `<td></td>`（列数差 1），TEDS 的 APTED 按整格计错。
- 文本格式：GT 用全角括号 `（性别： 男）`，pred 用半角；数字精度/空格不统一。

---

## 三、优化改进方案（按 ROI 排序）

### P0 — 修复表格合并链路（预期 TEDS +30~50，Overall 回正）

这是唯一能把 overall 从负分拉回正数的杠杆。当前 80% 样本因合并失败导致 TEDS≈0。

**措施 P0.1：放宽横向缝合条件**
- 现状：`_assemble_row_band` 要求「每个 chunk 恰好 1 表 + 行数完全相等」，大表跨块几乎必败。
- 改造 [table_assembler.py:138-162](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py#L138)：行数不等时按「最大公共行数」对齐缝合，多余行作为独立行追加；chunk 含多表时按顺序串接而非整体放弃。

**措施 P0.2：anchor 对齐容错**
- 现状：`_align_by_anchor` 首列相似度阈值 0.90 过严，且行数不等直接失败。
- 改造 [table_assembler.py:164-182](file:///data/liyc2026/.../table_assembler.py#L164)：行数不等时以「左块行数为基准」对齐，右块多出的行单独成行；相似度阈值降到 0.80，并用「前 3 列指纹」而非仅首列。

**措施 P0.3：fallback 时强制单表包裹**
- 现状：装配失败 → 各 chunk 表原样并列输出 N 个 `<table>`。
- 改造：fallback 路径下，把同组所有 chunk 的 `<tr>` 收集到一个 `<table>` 内输出（即使列不齐，也保证「单表」结构，让 TEDS 按行匹配而非按表数量惩罚）。

**措施 P0.4：html_broken 自愈**
- qc 显示 `html_broken` 警告。在 [table_assembler.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) 输出前用 BeautifulSoup 重解析，补全未闭合标签、剔除孤立的 `<tr>`/`<td>`。

### P1 — 消除空产出（预期 Overall +1~2）

**措施 P1.1**：对 `2358594b-...jpg` 单独重跑，`per_user_concurrency` 临时降到 1 排除限流；调高 chunk 重试次数（当前 rerun_count=2 仍失败）。
**措施 P1.2**：pipeline 末端加「非空断言」：任何 chunk 空输出强制重试，而不是进入 qc 后判 failed。对应 [quality_gate.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/quality_gate.py) 的 `max_api_failure_ratio` 触发后改为「阻断提交」而非「放行带病样本」。

### P2 — 收敛切分粒度（降低合并难度）

**措施 P2.1**：对纯表格图优先单页处理。当前 [configs/table_v2.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_v2.yaml) `target_pixels=5000000`、`allow_horizontal_split: true` 对大表触发频繁切分。建议：表格图 `allow_horizontal_split` 默认 false，仅当宽度 > `full_page_max_pixels`（8000000）才横向切，且切割线必须落在空列间隙（用 [layout_sentry.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/layout_sentry.py) 检测）。
**措施 P2.2**：A/B 验证 [configs/table_grid.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_grid.yaml)（target_pixels=4000000、overlap=160/220）是否改善列对齐。

### P3 — Prompt 与格式归一化（TEDS 中段 + Text Edit 增益）

**措施 P3.1**：prompt 强制输出 HTML `<table>`（非 markdown 表格——markdown 不携带 colspan/rowspan，见 [tables.py:62-65](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/tables.py#L62) 的转换会丢跨度）；要求每 chunk 输出完整 `<tr>` 边界；跨 chunk 复用上一块列数。
**措施 P3.2**：表格专用归一化（在 [normalizer.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/normalizer.py)）：全角括号/逗号转半角、`(负数)`→`-`、去尾部 `.0`、统一百分号空格。**注意**：必须与 prompt 同步要求模型按此格式输出，否则后处理会引入新差异。
**措施 P3.3**：输出 `<table>` 补齐 GT 常见属性（border/cellpadding）以缩小 text_edit——但需先确认评分器是否计入（当前 [tables.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/tables.py) 解析时忽略属性，故对 TEDS 无效，仅对 text_edit 有效）。

### P4 — 评分器归一化（仅本地诊断用，不改赛题口径）

本地诊断时把 te/roe 裁剪到 [0,1]：`min(1.0, distance/max(len_pred,len_gt))`。这能让本地 overall 反映真实结构差距，避免负分掩盖单项进展。**赛题提交评分不可改**。

### P5 — 验证与回归

- 每次 pipeline 改动后跑 `python -m finix_restore.eval.cli ...` 生成 metrics，对比 mean_table_teds 与 `teds<50` 样本数是否下降。
- 用 [scripts/chunk_eval/summarize_table_failures.py](file:///data/liyc/test/AFAC2026-Task2/scripts/chunk_eval/summarize_table_failures.py) 聚合最差 N 样本，定位是「合并失败」（多 `<table>`）还是「识别错」（单表但内容差）。
- 建立基线：当前 `teds<50 = 80/100`，目标 P0 落地后降至 `<30/100`。

---

## 四、执行优先级与预期收益

| 优先级 | 措施 | 预期 Overall 增量 | 难度 | 依赖 |
|---|---|---|---|---|
| P0.1-0.4 | 表格合并链路重构 | **+100~200**（overall 回正） | 高 | table_assembler.py |
| P1.1-1.2 | 消除空产出 | +1~2 | 低 | 单文件重跑 |
| P2.1-2.2 | 切分粒度收敛 | 间接（降低 P0 难度） | 中 | configs + layout_sentry |
| P3.1-3.3 | Prompt + 格式归一 | +5~15（TEDS 中段） | 中 | prompt_specs + normalizer |
| P4 | 本地评分归一化 | 0（仅诊断） | 低 | eval/* |
| P5 | 回归基线 | — | 低 | scripts/chunk_eval |

> **核心判断**：P0（表格合并）是唯一决定性的杠杆。在 P0 落地前，其他优化收益都被合并失败掩盖（80% 样本 TEDS≈0）。建议集中资源先做 P0.1-P0.4，用 `teds<50` 样本数作为验收指标。

---

## 五、复现命令

```bash
cd /data/liyc/test/AFAC2026-Task2
python -m finix_restore.eval.cli \
  --pred outputs/table_train_run_1/submission_A_table_train_run_1.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_table_100/id_mapping.csv" \
  --output outputs/table_train_run_1/metrics/table_eval.json
```

依赖：`rapidfuzz`、`apted`、`beautifulsoup4`、`lxml`（已通过 `pip install --break-system-packages` 装入当前环境）。

## 六、最差样本清单（用于定向修复）

### TEDS 最差 15（结构失败集中区）

| teds | text_edit | roe | overall | file_name |
|---|---|---|---|---|
| 0.0 | 1.000 | 1.0 | 0.0 | 2358594b（空产出） |
| 0.0 | 0.973 | 1.0 | 0.9 | ec745262 |
| 0.0 | 0.931 | 1.0 | 2.3 | e8b578eb |
| 0.0 | 0.976 | 1.0 | 0.8 | 6950d267 |
| 0.1 | 0.570 | 9.0 | -252.3 | f501eee1 |
| 0.1 | 0.358 | 6.25 | -153.6 | f0ab450d |
| 0.1 | 0.836 | 1.0 | 5.5 | 97c4c182 |
| 0.1 | 2.872 | 8.857 | -324.2 | 0e8a501f（33 表合并失败） |
| 0.2 | 0.882 | 1.2 | -2.7 | 583ac07b |
| 0.2 | 1.469 | 7.125 | -219.7 | cabe16d5 |
| 0.3 | 0.966 | 1.0 | 1.2 | 6ab6b885 |
| 0.4 | 0.805 | 0.96 | 8.0 | db515dd2 |
| 0.4 | 0.951 | 1.0 | 1.8 | 6c205e72 |
| 0.4 | 0.951 | 1.0 | 1.8 | c6632f54 |
| 0.5 | 0.874 | 13.5 | -412.3 | 38d6f9d0 |

### Read Order 最差 10（合并失败副作用）

| roe | text_edit | file_name |
|---|---|---|
| 309.58 | 0.882 | 141edbb1 |
| 33.33 | 0.188 | 090853cd |
| 33.33 | 0.188 | 790bec64 |
| 30.0 | 0.347 | 94352240 |
| 13.5 | 0.874 | 38d6f9d0 |
| 9.0 | 0.570 | f501eee1 |
| 8.857 | 2.872 | 0e8a501f |
| 8.0 | 0.722 | b5caddc4 |
| 7.125 | 1.469 | cabe16d5 |
| 6.25 | 0.358 | f0ab450d |

> 这些样本的共同特征：pred 含多个 `<table>` 块（合并失败），导致 read_order 块数远超 GT 的 1 个表块。修复 P0 后这批样本的 roe 会自然回落到 [0,1]。
