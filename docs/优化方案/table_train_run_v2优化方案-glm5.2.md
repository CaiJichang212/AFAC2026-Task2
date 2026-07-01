# table_train_run_v2 评分分析与优化方案

> 评估对象：`outputs/table_train_run_v2/submission_A_table_train_run_v2.csv`（100 个 huge_table 样本）
> 评估口径：`finix_restore.eval`（Text Edit / Table TEDS / Read Order Edit 三项，Overall = 三项均值）
> GT 来源：`data/AFAC 训练数据集/finixdocbench_huge_table_100/mds/`（100 份 `<uuid>.md`）
> 评分产物：`outputs/table_train_run_v2/metrics/table_eval.json`、`outputs/table_train_run_v2/metrics/analysis.md`
> 生成日期：2026-07-01

---

## 一、评分结果总览

| 指标 | run_v2 | run_1（上一版） | 说明 |
|---|---|---|---|
| file_count | 100 | 100 | 全部匹配，无 missing |
| **mean Text Edit** | **1.9255** | 0.9820 | 越低越好；文本相似度仍很差，且较 run_1 进一步恶化 |
| **mean Table TEDS** | **18.07 / 100** | 20.76 / 100 | 越高越好；中位数仅 3.97，表格结构基本不达标 |
| **mean Read Order Edit** | **4.9799** | 5.5787 | 越低越好；>1 即异常（接缝重复/多表并列） |
| **Overall** | **17.68** | -145.10 | run_v2 已回正（run_1 负分源于 te/roe 未裁剪） |

> 注：run_1 的 Overall=-145.10 是因为评分器 `raw_overall` 未对 te/roe 裁剪到 [0,1]；run_v2 的 17.68 是裁剪后的 `overall`（即 `min(1.0, te)`、`min(1.0, roe)`），更贴近赛题实际口径。两个版本的均值口径不同，**不能直接对比绝对值**，但底层 te/teds/roe 三项可比。

### 1.1 分布统计（百分位）

| 指标 | min | p25 | 中位 | p75 | max | mean |
|---|---|---|---|---|---|---|
| text_edit | 0.0494 | 0.6102 | 0.8176 | 0.9258 | 38.5040 | 1.9255 |
| table_teds | 0.0000 | 0.6090 | 3.9660 | 28.7899 | 92.7175 | 18.0696 |
| read_order_edit | 0.2500 | 1.0000 | 1.0000 | 1.0848 | 204.8333 | 4.9799 |
| overall | 0.0000 | 3.2933 | 8.5187 | 27.4104 | 81.0305 | 17.6848 |

### 1.2 TEDS 分桶（关键诊断）

| TEDS 区间 | 样本数 | 占比 |
|---|---|---|
| [0, 1) | **31** | **31%** 完全失败 |
| [1, 10) | **30** | 30% 基本不达标 |
| [10, 30) | 15 | 15% |
| [30, 50) | 10 | 10% |
| [50, 70) | 6 | 6% |
| [70, 85) | 5 | 5% |
| [85, 95) | 3 | 3% |
| [95, 100] | 0 | 0% 无满分 |

> **核心结论：61% 的样本 TEDS < 10（表格结构基本失败），仅 8% 达到 70+。表格还原是当前绝对的得分短板。**

---

## 二、Top20 vs Bottom20 对比分析

### 2.1 Overall 最优 20 条（高分样本特征）

| rank | overall | teds | text_edit | roe | file_name |
|---|---|---|---|---|---|
| 1 | 81.03 | 92.72 | 0.068 | 0.429 | fd2907b4 |
| 2 | 71.12 | 92.18 | 0.074 | 0.714 | 051fa323 |
| 3 | 66.34 | 68.57 | 0.296 | 0.400 | 58f89fe3 |
| 4 | 63.53 | 84.72 | 0.191 | 0.750 | e3e19b92 |
| 5 | 58.98 | 31.48 | 0.295 | 0.250 | 8b49fd91 |
| 6 | 58.96 | 70.93 | 0.191 | 0.750 | f23fb56f |
| 7 | 58.28 | 64.35 | 0.395 | 0.500 | a6d0f1e0 |
| 8 | 56.93 | 81.63 | 0.233 | 0.875 | 18a56a77 |
| 9 | 56.77 | 75.23 | 0.049 | 10.000 | 090853cd |
| 10 | 56.25 | 73.87 | 0.051 | 10.000 | 790bec64 |

**高分样本共性**：
- **图片像素 < 16M**（4678×3308 ≈ 15.5M）居多，切片数 ≤ 3
- **GT 表格行数 < 100**，pred 行数与 GT 行数比 > 0.8
- text_edit 普遍 < 0.4，说明文本内容识别到位
- 单 chunk 或少量 chunk 即可覆盖整表，**无需跨 chunk 合并**

### 2.2 Overall 最差 20 条（低分样本特征）

| rank | overall | teds | text_edit | roe | file_name | 像素 | GT行 | pred行 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.00 | 0.00 | 1.000 | 1.000 | ec745262 | 30.9M | 275 | **0** |
| 2 | 0.01 | 0.00 | 1.000 | 1.000 | a1aaef73 | 15.5M | 60 | **0** |
| 3 | 0.11 | 0.32 | 1.469 | 4.138 | a4924b6d | **386.6M** | - | - |
| 4 | 0.11 | 0.32 | 1.503 | 1.320 | 4f27636c | **228.9M** | - | - |
| 5 | 0.20 | 0.60 | 18.992 | 3.571 | 532dfde4 | 15.5M | - | - |
| 6 | 0.36 | 1.09 | 23.517 | 1.000 | 34e53b1c | 15.5M | - | - |
| 7 | 0.67 | 2.01 | 38.504 | 1.400 | 1674392a | 30.9M | - | - |
| 8 | 0.92 | 0.37 | 0.976 | 1.000 | 6950d267 | 30.9M | 316 | **8** |
| 9 | 0.96 | 0.06 | 0.972 | 1.000 | 2358594b | 30.9M | 250 | **1** |
| 10 | 1.47 | 0.08 | 0.957 | 1.000 | e8b578eb | 31.0M | 286 | **9** |
| 11 | 1.67 | 0.34 | 0.953 | 1.000 | 3c3f1666 | 30.9M | 181 | **10** |
| 12 | 1.75 | 0.38 | 0.951 | 1.000 | 6ab6b885 | 47.4M | 434 | **24** |
| 13 | 1.94 | 0.61 | 0.948 | 1.000 | 9c7857f3 | 15.5M | 214 | **4** |
| 14 | 1.97 | 0.49 | 0.946 | 1.000 | e56db050 | 47.4M | 307 | **3** |
| 15 | 2.13 | 6.38 | 2.447 | 1.125 | f0ab450d | **350.6M** | - | - |
| 16 | 2.15 | 6.46 | 2.404 | 1.571 | 0e8a501f | **350.6M** | 107 | **369** |
| 17 | 2.29 | 1.47 | 0.946 | 1.000 | 0878213b | 47.4M | 307 | **11** |
| 18 | 2.37 | 0.46 | 0.933 | 1.000 | 1b8718d0 | 15.5M | 165 | **10** |
| 19 | 2.39 | 0.01 | 0.928 | **152.25** | 6c205e72 | 15.5M | 214 | **1** |
| 20 | 2.42 | 7.27 | 9.893 | 1.000 | b44312da | 30.9M | 46 | **517** |

### 2.3 低分样本根本原因分类

| 失败模式 | 典型样本 | 根因 | 占比 |
|---|---|---|---|
| **A. pred 完全空/近空** | ec745262(0行)、a1aaef73(0行)、2358594b(1行) | API 空输出/限流，大图分块后内容丢失 | ~5% |
| **B. pred 严重截断（大表）** | 6950d267(GT316/pred8)、e8b578eb(GT286/pred9)、e56db050(GT307/pred3) | GT 行数 200+，切片覆盖不足，合并后只剩零星行 | ~20% |
| **C. pred 超长爆炸（碎片化）** | 34e53b1c(pred 388K字/2306行)、b44312da(pred 70K字/517行)、532dfde4(pred 284 chunk) | 极大图被切成数百片，无法合并，文本重复堆积 | ~10% |
| **D. 阅读流顺序崩溃** | 6c205e72(roe=152)、2554c249(roe=204) | pred 行数极少但块序完全错乱 | ~5% |
| **E. 超大图（>100M像素）整体失败** | a4924b6d(386M)、4f27636c(228M)、f0ab450d(350M) | 单图像素超 2 亿，切分+合并链路全断 | ~8% |

---

## 三、瓶颈定位（按影响权重排序）

### 瓶颈 A：超大表格（GT 行数 ≥ 200）的"内容截断"——TEDS 头号杀手

**实证（按 GT 行数分桶）**：

| GT 表格行数 | 样本数 | mean_overall | mean_teds |
|---|---|---|---|
| [0, 50) | 5 | 26.1 | 37.3 |
| [50, 100) | 26 | **29.4** | 29.9 |
| [100, 200) | 42 | 18.5 | 18.9 |
| **[200, 400)** | **25** | **3.2** | **1.1** |
| [400+) | 2 | 7.4 | 10.1 |

> **决定性发现：GT 行数 200-400 的 25 个样本，mean_overall 仅 3.2、mean_teds 仅 1.1，几乎全军覆没。这是拖低整体均值的最大权重。**

**截断证据**（pred 行数 / GT 行数）：
- ec745262：GT 275 行 → pred **0 行**（完全空）
- 2358594b：GT 250 行 → pred **1 行**
- e56db050：GT 307 行 → pred **3 行**
- 6950d267：GT 316 行 → pred **8 行**

**根因链**：
1. 大图（像素 30M-386M）被 [table_image_policy.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_image_policy.py) 切成多个 row_band，每 band 又被横向切。
2. 每个 chunk 调 FinixDoc-VL 时，**模型对密集数字表格的输出存在 token 上限截断**：一个 chunk 可能含 50+ 行数字，模型只输出前几行就停了。
3. [table_assembler.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) 的 `_assemble_row_band` 要求"行数完全一致"才横向缝合，行数不等直接返回 `None` → fallback 输出残缺表。
4. 多 band 纵向拼接时，`_row_matches_header` 阈值 0.92 过严，表头行被误判为重复而丢弃。

### 瓶颈 B：极大图（像素 > 100M）的"切片爆炸"——无法合并

**实证（按图片像素分桶）**：

| 图片像素 | 样本数 | mean_overall | mean_teds |
|---|---|---|---|
| < 16M | 54 | **23.3** | 24.7 |
| 16-35M | 16 | 14.2 | 18.3 |
| 35-100M | 22 | 10.6 | 5.7 |
| **100M+** | **8** | **6.2** | 7.1 |

**典型灾难案例**：
- a4924b6d（16527×23390 = 386M 像素，36 chunk）→ overall 0.1
- 4f27636c（12721×17990 = 228M 像素，23 chunk）→ overall 0.1
- f0ab450d / 0e8a501f（22277×15740 = 350M 像素，75 chunk）→ overall ~2

**根因**：
- `row_band_target_pixels=10M`、`row_band_safe_pixels=14M` 对 2 亿像素图会切出 20-75 个 band，每个 band 再切列。
- [table_assembler.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) 的 `_assemble_group` 按 `table_group_id` 分组合并，但**跨 group 的行无法纵向拼接**，且单个 group 内多 chunk 横向合并一旦失败就整体 fallback。
- 极大图切片数过多 → 合并复杂度爆炸 → 结构彻底散架。

### 瓶颈 C：切片数与分数的"倒 U 型"关系

**实证（按切片数分桶）**：

| 切片数 | 样本数 | mean_overall | mean_teds |
|---|---|---|---|
| ≤ 3 | 50 | **24.2** | 25.3 |
| 4-5 | 24 | 11.1 | 12.5 |
| 6-30 | 12 | 11.6 | 4.4 |
| 31-100 | 5 | 4.3 | 6.7 |
| 100+ | 9 | 14.9 | 17.1 |

> **切片越少分数越高（≤3 切片 mean_overall 24.2）。但 100+ 切片反而比 31-100 切片略好（14.9 vs 4.3），因为 100+ 切片对应的多是中等像素图被细切，至少能拼出部分；而 31-100 切片对应的多是极大图，合并彻底失败。**

**结论**：当前切分粒度对中等表（15-47M 像素）过度切分。4678×3308（15.5M 像素）的图本可整页上传（<16M 硬上限），却被切成 3 片。

### 瓶颈 D：格式属性全面缺失——Text Edit 次要损耗

**实证**：
- **100% 样本 pred 缺 `border` 属性**（GT 全部为 `<table border="1" cellpadding="8" cellspacing="0">`）
- **36% 样本 pred 缺 `<th>` 标签**（GT 有 th 但 pred 全用 td）
- **18% GT 含 colspan/rowspan**，但 pred 多数未还原跨度

**对评分影响**：
- `border`/`cellpadding` 属性：[tables.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/tables.py) 解析时忽略属性，**对 TEDS 无影响**，但拉高 text_edit（字符层面差异）。
- `<th>` vs `<td>`：TEDS 树结构中 th/td 是不同节点，**直接影响 TEDS**（GT 表头用 th，pred 用 td → 表头行全部错配）。
- colspan/rowspan：跨度错误导致树结构拓扑不一致，TEDS 重罚。

### 瓶颈 E：评分器归一化缺陷（放大失分）

text_edit max=38.5、read_order_edit max=204.8，均远超 1.0。
- [finix_restore/eval/text_metric.py:31](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/text_metric.py)：`distance / max(1, len(gt))`，pred 远长于 GT 时比值 >1。
- [finix_restore/eval/reading_order.py:65](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/reading_order.py)：`distance / max(1, len(gt_blocks))`，同样问题。

> **不能改赛题评分器**。但优化方向必须把 te/roe 压回 [0,1]：即让 pred 长度/块数贴近 GT，避免 pred 爆炸（瓶颈 C）和空产出（瓶颈 A）。

---

## 四、技术调研：超大表格切分与重组的前沿方法

基于联网调研，业界处理超大表格图片的主流技术路线如下：

### 4.1 Split-Merge 范式（TABLET / SEM）

**核心思想**（参考 [TABLET, arXiv:2506.07015](https://arxiv.org/html/2506.07015v1)、[SEM, arXiv:2107.05214](https://ar5iv.labs.arxiv.org/html/2107.05214)）：
1. **Split**：先用 FCN/Transformer 把表格切成细粒度网格（row/column separator 预测，而非 bbox 回归）。
2. **Embed**：对每个网格单元用 RoIAlign 提取视觉+文本融合特征。
3. **Merge**：用 Transformer encoder 对网格单元分类（OTSL 语言），自回归合并相邻单元，恢复 colspan/rowspan。

**对本项目启示**：
- 当前 pipeline 是"几何切图 → VLM 识别 → 后处理合并"，**切分与识别脱耦**。TABLET 的优势在于切分本身由模型驱动，切线天然落在行/列分隔线上。
- 受赛题限制（只能用 FinixDoc-VL + <10M 本地小模型），无法引入 TABLET 的深度模型，但可借鉴其"**切线必须落在行间隙**"的约束，用轻量版面分析（<10M 模型或 OpenCV 投影）指导切分。

### 4.2 Image Tiling + Global Context（Monkey / Flash-VL）

**核心思想**（参考 [Monkey, CVPR24](https://arxiv.org/abs/2512.11167)、[Flash-VL 2B, arXiv:2505.09498](https://arxiv.org/pdf/2505.09498v1)）：
- 将超大图切成 N×M 个 tile，每个 tile 独立编码，再融合。
- **关键改进：Dynamic Overlapping Cropping**——tile 之间有重叠，避免边界信息丢失。
- **Implicit Semantic Stitching**（Flash-VL）：在 LLM 解码层隐式缝合 tile 语义，而非简单拼接文本。

**对本项目启示**：
- 当前 `horizontal_overlap=160`、`vertical_overlap=280` 对超大图偏小。金融表格单数字宽度可能仅 20-40px，160px 重叠约覆盖 4-8 列，**切线极易落在数字中间**导致列错位。
- 应**增大重叠 + 基于空白列动态定位切线**（借鉴 [图片切分优化方案.md](file:///data/liyc/test/AFAC2026-Task2/docs/图片切分优化方案.md) 的 blank_band_search 思路，但需真正落地到 table 策略）。

### 4.3 金融保险费率表的领域特点

**数据观察**（本批 100 样本全部为现金价值表/费率表）：
- **双索引表头**：行=投保年龄，列=保单年度，表头常含 `<th rowspan="2">投保年龄</th><th colspan="N">年度</th>` 嵌套结构。
- **密集数字矩阵**：单格多为 4 位小数（如 434.7289），单行可达 50+ 列。
- **无框线/少框线**：GT 用 HTML 属性表达结构，图像本身可能是白底黑字无网格线 → 传统线检测失效。
- **跨页续表**：大表在图像上是多页拼接（如 18a56a77 GT 含"第2页 共66页"），需识别续表表头并去重。

**领域优化方向**：
- 这类表的**行间有固定留白**（每行高度一致），可用水平投影极小值定位行切线。
- **列首锚点固定**（投保年龄、年度编号），可作为跨 chunk 对齐的强锚点。

### 4.4 Table2LaTeX-RL 的双奖励思路

[Table2LaTeX-RL, NeurIPS25](https://openreview.net/pdf?id=0bvc7Zslu3) 提出结构奖励 + 视觉渲染奖励的双奖励 RL。虽本项目不能训练模型，但其**评估思想可借鉴**：TEDS-Structure 侧重树拓扑，而视觉渲染一致性（CW-SSIM）能捕捉 TEDS 漏检的细粒度错位。本地诊断时可辅以渲染对比定位"TEDS 相似但视觉错位"的样本。

---

## 五、优化改进方案（按 ROI 排序）

### P0 — 提升大表（GT 行数 ≥ 100）的内容完整度（预期 TEDS +15~25，Overall +8~12）

**这是当前最大权重短板**：42 个样本 GT 行数 100-200（mean_overall 18.5），25 个样本 GT 行数 200-400（mean_overall 仅 3.2）。

#### P0.1：单 chunk 内强制完整输出（防 token 截断）

**问题**：FinixDoc-VL 对密集数字表格存在输出长度限制，单 chunk 含 50+ 行数字时易截断。

**措施**：
- 在 prompt 中明确要求"**必须输出该切片内全部表格行，不得省略，不得用省略号**"。
- 对表格类 chunk，**降低单 chunk 的行密度**：将 `row_band_target_pixels` 从 10M 降到 6M（[configs/table_v2.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_v2.yaml)），使每 band 含 30-50 行而非 80+ 行，避开模型输出上限。
- chunk 末尾增加"**行计数校验**"：prompt 要求模型在表末输出 `<!-- rows: N -->`，后处理比对图像行数与输出行数，不一致则重试。

**代码位置**：[prompt_specs.py](file:///data/liyc/test/AFAC2026-Task2/docs/prompt_specs.md)、[configs/table_v2.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_v2.yaml) `row_band_target_pixels`。

#### P0.2：放宽横向缝合条件（修复行数不等导致的合并失败）

**问题**：[table_assembler.py:174-194](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) `_align_by_anchor` 要求 `len(merged_rows) == len(right_rows)`，行数不等直接返回 None → fallback 输出多表 → TEDS 崩溃。

**措施**（借鉴 TABLET 的容错合并）：
- 行数不等时，以**左块行数为基准**，按行索引 zip；右块多出的行作为独立新行追加到末尾。
- anchor 相似度阈值从 0.80 降到 0.65，并用"前 2 列指纹"而非仅首列（金融表首列常是投保年龄数字，跨 chunk 易重复）。
- 对齐策略改为**双向对齐**：同时尝试左对齐和右对齐，取 TEDS 局部得分更高者。

#### P0.3：fallback 时强制单表包裹

**问题**：装配失败 → 各 chunk 表原样并列输出 N 个 `<table>`，TEDS 按表数量重罚。

**措施**（已在 run_1 方案提出，需落地）：
- fallback 路径下，把同组所有 chunk 的 `<tr>` 收集到**单个** `<table>` 内输出。即使列不齐，也保证单表结构，让 TEDS 按行匹配。
- 代码位置：[table_assembler.py:94-105](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) `_fallback_group_by_columns`，改为始终合并到主桶。

#### P0.4：纵向 band 拼接的表头去重容错

**问题**：[table_assembler.py:136-141](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) `_row_matches_header` 阈值 0.92，跨页续表的表头（如"第2页"重复表头）可能因页码差异被误判为非表头而保留，或正常数据行被误判为表头而丢弃。

**措施**：
- 表头判定改为**结构匹配 + 位置约束**：仅对每个 band 的**第一行**做表头判定，且要求该行与已合并表头的相似度 ≥ 0.85 且该 band 后续行均为数字行。
- 对含"第X页"字样的行单独剥离为文本块，不进入表格行。

---

### P1 — 收敛极大图（像素 > 100M）的切分粒度（预期这 8 个样本 Overall +5~15）

**问题**：8 个 100M+ 像素样本 mean_overall 仅 6.2，切片数 23-75，合并全断。

#### P1.1：极大图优先降采样整页参考 + 行带细切

**措施**：
- 当前 `_build_reference` 已生成降采样整页参考（[table_image_policy.py:53-67](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_image_policy.py)），但**参考图只用于提示文本，未参与表格结构**。
- 改造：对像素 > 100M 的图，**参考图提供表头结构与列定义**，行带 chunk 只输出数据行，后处理时将列定义注入每个行带输出，强制列对齐。
- 这样即使行带切成 30 片，每片都能正确补全表头列数，纵向拼接只需拼接数据行。

#### P1.2：行带切线基于水平投影精确定位

**措施**（借鉴 [图片切分优化方案.md](file:///data/liyc/test/AFAC2026-Task2/docs/图片切分优化方案.md) Phase 3，落地到 table）：
- 对每个 row_band 候选切线，在 `±cut_search_px`（当前 360）范围内计算**水平投影墨迹密度**，选择密度极小值点作为切线。
- 金融表格行间有固定留白，投影极小值可靠定位行间隙。
- 用 OpenCV（<10M 级别）或纯 numpy 实现，符合赛题"本地小模型 <10M"约束。

#### P1.3：超大图分阶段降级策略

**措施**：
- 像素 > 200M：先 2× 下采样到 50M 级别，再按 P1.1 切行带。下采样会损失小字精度，但金融表数字大、对比度高，2× 降采样后仍可识别。
- 像素 100-200M：1.5× 下采样到 50-90M，行带切分。
- 在 prompt 中告知模型"本图为降采样版本，数字可能略显模糊，请仔细辨认"。

---

### P2 — 格式属性补全（预期 Text Edit -0.1~0.2，TEDS +3~5）

#### P2.1：统一补齐 `<table border="1" cellpadding="8" cellspacing="0">`

**问题**：100% pred 缺 border 属性，拉高 text_edit。

**措施**：
- 在 [table_assembler.py:252](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) `_render_table` 中，把 `<table>` 改为 `<table border="1" cellpadding="8" cellspacing="0">`。
- **注意**：[tables.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/eval/tables.py) 解析时忽略属性，对 TEDS 无影响，但能缩小 text_edit（占 Overall 1/3 权重）。

#### P2.2：表头强制使用 `<th>`

**问题**：36% 样本 GT 用 `<th>` 但 pred 全用 `<td>`，TEDS 树节点类型不匹配。

**措施**：
- prompt 强制要求"**表格第一行（表头）必须用 `<th>` 标签，数据行用 `<td>`**"。
- 后处理：对每个 `<table>` 的第一行，若全为 `<td>` 且内容为"投保年龄/年度/性别"等表头关键词，自动转为 `<th>`。
- 代码位置：[table_parser.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_parser.py) 增加 header 检测。

#### P2.3：colspan/rowspan 精确还原

**问题**：18% GT 含跨度，pred 多未还原。

**措施**：
- prompt 中给出金融表常见跨度范例：`<th rowspan="2">投保年龄</th><th colspan="24">保险合同周年末</th>`。
- 后处理：检测 pred 中"表头跨多列但写成重复 `<td>`"的情况，合并为 colspan。

---

### P3 — 消除空产出与碎片化（预期 Overall +2~4）

#### P3.1：空产出强制重试

**问题**：ec745262、a1aaef73 等完全空输出。

**措施**：
- [quality_gate.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/quality_gate.py) 触发 `empty_output` 后，强制重试而非放行。
- 重试时降低该文件 `per_user_concurrency` 到 1（排除限流），增加 `max_retries` 到 5。

#### P3.2：中等图（15-47M）避免过度切分

**问题**：15.5M 像素图（4678×3308）本可整页上传（<16M 硬上限），却被切 3 片。

**措施**：
- [configs/table_v2.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_v2.yaml) 调整：`full_page_max_pixels` 从 8M 提到 15M（接近硬上限 16.78M 但留余量）。
- `target_pixels` 从 5M 提到 8M，减少中等图切片数。
- 验证：切片数 ≤ 3 的 50 个样本 mean_overall 24.2，是 4-5 切片（11.1）的 2 倍，**少切明显有利**。

---

### P4 — 阅读流顺序修复（预期 ROE 回落，间接提升 Overall）

#### P4.1：表格块统一为单块

**问题**：6c205e72 roe=152、2554c249 roe=204，源于 pred 含多个孤立块。

**措施**：P0.3（单表包裹）落地后，表格天然变为单块，roe 自动回落。

#### P4.2：表格前后文本与表格的顺序校验

**措施**：在 [reading_order.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/reading_order.py) 后处理中，确保"表格标题文本 → 表格主体"的固定顺序，避免标题被误排到表后。

---

## 六、执行优先级与预期收益

| 优先级 | 措施 | 预期 Overall 增量 | 难度 | 依赖 |
|---|---|---|---|---|
| **P0.1** | 单 chunk 防截断 + 行计数校验 | **+5~8**（大表完整度） | 中 | prompt + config |
| **P0.2** | 放宽横向缝合条件 | **+4~6**（合并成功率） | 高 | table_assembler.py |
| **P0.3** | fallback 单表包裹 | **+3~5**（TEDS 兜底） | 中 | table_assembler.py |
| **P0.4** | 纵向表头去重容错 | +1~2 | 中 | table_assembler.py |
| **P1.1** | 极大图参考图注入列定义 | **+3~6**（8 个 100M+ 样本） | 高 | table_image_policy + assembler |
| **P1.2** | 行带切线水平投影定位 | +2~3 | 中 | cutline_planner + OpenCV |
| **P1.3** | 超大图分阶段降采样 | +1~2 | 低 | chunkers |
| **P2.1** | 补齐 table 属性 | +0.5~1（text_edit） | 低 | table_assembler |
| **P2.2** | 表头强制 th | +2~3（TEDS） | 中 | prompt + table_parser |
| **P2.3** | colspan/rowspan 还原 | +1~2 | 中 | prompt + 后处理 |
| **P3.1** | 空产出强制重试 | +1~2 | 低 | quality_gate |
| **P3.2** | 中等图少切分 | +2~4 | 低 | config |
| **P4** | 阅读流修复 | +1~2 | 低 | 随 P0 落地 |

> **核心判断**：P0（大表内容完整度）是最大杠杆。当前 GT 行数 200+ 的 25 个样本 mean_overall 仅 3.2，若通过 P0.1-P0.4 将这部分提升到 15-20，整体均值可从 17.68 提升到 25-30。P1（极大图）是第二杠杆，针对 8 个 100M+ 样本。P2/P3 是稳定增益。建议按 P0 → P3.2（快速验证）→ P1 → P2 顺序推进。

---

## 七、验收指标与回归

### 7.1 核心验收指标

| 指标 | 当前（run_v2） | P0 后目标 | P0+P1 后目标 |
|---|---|---|---|
| mean_overall | 17.68 | 25-28 | 30-35 |
| mean_table_teds | 18.07 | 28-32 | 35-40 |
| TEDS < 10 样本数 | 61/100 | < 40/100 | < 25/100 |
| TEDS ≥ 70 样本数 | 8/100 | 15/100 | 25/100 |
| GT行数≥200 样本 mean_overall | 3.2 | 12-15 | 18-22 |

### 7.2 回归命令

```bash
cd /data/liyc/test/AFAC2026-Task2

# 1. 重跑评分
python -m finix_restore.eval.cli \
  --pred outputs/table_train_run_v2/submission_A_table_train_run_v2.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_table_100/id_mapping.csv" \
  --output outputs/table_train_run_v2/metrics/table_eval.json

# 2. 逐条分析
python scripts/table_run_v2_analyze.py

# 3. 重点对比 GT 行数 200+ 样本
# （用本报告第三节的方法重新分桶）
```

### 7.3 定向验证样本

| 样本 | 当前 | 目标 | 验证点 |
|---|---|---|---|
| ec745262（GT275行/空产出） | overall 0.0 | > 15 | P0.1 + P3.1 |
| 6950d267（GT316行/pred8行） | overall 0.9 | > 12 | P0.1 截断修复 |
| e8b578eb（GT286行/pred9行） | overall 1.5 | > 12 | P0.1 + P0.2 |
| a4924b6d（386M像素/36chunk） | overall 0.1 | > 8 | P1.1 + P1.3 |
| 34e53b1c（pred 2306行爆炸） | overall 0.4 | > 10 | P0.3 单表包裹 + 去重 |
| fd2907b4（高分基准） | overall 81.0 | 保持 ≥ 80 | 回归不退化 |

---

## 八、复现命令与依赖

```bash
cd /data/liyc/test/AFAC2026-Task2

# 评分（复现本报告数据）
python -m finix_restore.eval.cli \
  --pred outputs/table_train_run_v2/submission_A_table_train_run_v2.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_table_100/id_mapping.csv" \
  --output outputs/table_train_run_v2/metrics/table_eval.json

# 逐条分析脚本
python scripts/table_run_v2_analyze.py
# 产物：outputs/table_train_run_v2/metrics/analysis.md
```
使用uv管理python开发环境/data/liyc/test/AFAC2026-Task2/.venv
依赖：`rapidfuzz`、`apted`、`beautifulsoup4`、`lxml`、`Pillow`（已通过 `pip install --break-system-packages` 装入当前环境）。

---

## 九、附录：调研文献索引

1. **TABLET**: Table Structure Recognition using Encoder-only Transformers, arXiv:2506.07015, 2025 — Split-Merge 范式，RoIAlign + Transformer 合并网格单元，专为大密集表优化。
2. **SEM**: Split, Embed and Merge, arXiv:2107.05214, ICDAR 2021 Task-B 复杂表第一 — FCN 切网格 + 自回归合并 + 注意力机制。
3. **Monkey**: Image Tiling for High-Resolution Reasoning, CVPR24 / arXiv:2512.11167 — Tile 切分 + Global Context 恢复空间一致性。
4. **Flash-VL 2B**: arXiv:2505.09498, 2025 — Dynamic Overlapping Cropping + Implicit Semantic Stitching。
5. **Table2LaTeX-RL**: NeurIPS 2025 — 结构奖励 + 视觉渲染奖励（CW-SSIM）双奖励 RL，TEDS-Structure 评估。

> **合规说明**：以上文献仅作为技术调研参考，用于指导切分/合并算法的工程实现。最终提交工程仅使用 FinixDoc-VL API + 本地 <10M 小模型（如 OpenCV/numpy 投影分析），不引入任何外部大模型 API，符合赛题规则。

---

## 十、本轮已执行改动记录（2026-07-01）

本章节记录已落地的代码改动，便于后续复跑验证与回归对比。

### 10.1 已实施清单

| 编号 | 措施 | 文件 | 状态 |
|---|---|---|---|
| P3.2 | 中等图少切分（target_pixels 5M→8M，full_page_max 8M→15M） | [configs/table_v2.yaml](file:///data/liyc/test/AFAC2026-Task2/configs/table_v2.yaml) | 已完成 |
| P0.1（部分） | 降低单 band 行密度（row_band_target_pixels 10M→6M） | configs/table_v2.yaml | 已完成 |
| P0.2 | 放宽横向缝合：行数不等容错 + 阈值 0.80→0.65 + 前 2 列指纹 | [finix_restore/table_assembler.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_assembler.py) `_align_by_anchor` | 已完成 |
| P0.3 | fallback 强制单表包裹（按最宽列补齐，合并为单表） | finix_restore/table_assembler.py `_fallback_group_by_columns` | 已完成 |
| P0.4 | 纵向表头去重阈值 0.92→0.85 | finix_restore/table_assembler.py `_row_matches_header` | 已完成 |
| P2.1 | 补齐 `<table border="1" cellpadding="8" cellspacing="0">` | finix_restore/table_assembler.py `_render_table` | 已完成 |
| P2.2 | 表头自动检测 th（金融表关键词触发） | [finix_restore/table_parser.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/table_parser.py) `_mark_header_row` | 已完成 |
| P3.1 | 空产出强制重试 + 并发降为 1 + max_reruns 2→3 | [finix_restore/retry_planner.py](file:///data/liyc/test/AFAC2026-Task2/finix_restore/retry_planner.py) + configs/table_v2.yaml | 已完成 |

### 10.2 配置变更摘要（configs/table_v2.yaml）

```yaml
table:
  target_pixels: 5000000 → 8000000       # P3.2: 中等图减少切片
  safe_max_pixels: 7000000 → 12000000    # P3.2: 与全局 safe 对齐
  full_page_max_pixels: 8000000 → 15000000  # P3.2: 15.5M 图可整页
  row_band_target_pixels: 10000000 → 6000000  # P0.1: 降低行密度防截断
  row_band_safe_pixels: 14000000 → 10000000   # P0.1
quality:
  max_reruns_per_file: 2 → 3             # P3.1: 空产出更多重试机会
```

### 10.3 核心代码改动详解

**P0.2 `_align_by_anchor` 行数不等容错**：
- 旧逻辑：`if len(merged_rows) != len(right_rows): return None` → 行数不等直接放弃合并。
- 新逻辑：`pair_count = min(...)`，按最小行数对齐缝合，左/右块多出的行各自追加到末尾，不丢失数据。
- 相似度指纹从"首列"改为"前 2 列"，阈值 0.80→0.65。

**P0.3 `_fallback_group_by_columns` 单表包裹**：
- 旧逻辑：按列数分桶，输出多个 `<table>` → TEDS 按表数量重罚。
- 新逻辑：以最宽列数为主桶，不足的行右侧补空 `ParsedCell`，全部合并为单一 `<table>`。

**P2.2 `_mark_header_row` 表头检测**：
- 解析表格后，若第一行全为 `td` 但含 `_HEADER_KEYWORDS`（投保年龄/保单年度/性别/现金价值等），自动转为 `is_header=True`，渲染时输出 `<th>`。

### 10.4 测试验证结果

```
新增测试 6 个（全部通过）:
  test_table_row_assembler_renders_table_with_border_attributes   (P2.1)
  test_table_row_assembler_aligns_uneven_rows_left_longer         (P0.2)
  test_table_row_assembler_aligns_uneven_rows_right_longer        (P0.2)
  test_table_parser_marks_header_row_for_financial_keywords       (P2.2 正例)
  test_table_parser_does_not_mark_pure_data_rows_as_header        (P2.2 反例)
  test_retry_planner_forces_api_and_low_concurrency_for_empty_output  (P3.1)

全量测试: 198 passed, 7 failed
（7 个失败为预先存在的历史问题，与本次改动无关，已通过 git stash 验证）
```

### 10.5 待后续执行（需 API 调用验证）

以下措施需要实际调用 FinixDoc-VL API 才能验证，建议下一轮跑全量数据时启用：

| 编号 | 措施 | 说明 |
|---|---|---|
| P0.1（完整） | prompt 增加行计数校验 `<!-- rows: N -->` | 需修改 prompt_specs，跑数据后比对图像行数与输出行数 |
| P1.1 | 极大图参考图注入列定义 | 需改 table_image_policy + assembler，针对 100M+ 像素样本 |
| P1.2 | 行带切线水平投影定位 | 需引入 OpenCV/numpy 投影分析（<10M 本地模型） |
| P1.3 | 超大图分阶段降采样 | 需改 chunkers，针对 200M+ 像素图 |
| P2.3 | colspan/rowspan 精确还原 | 需 prompt 工程 + 后处理 |

### 10.6 复跑命令

```bash
cd /data/liyc/test/AFAC2026-Task2

# 1. 用新配置重跑 100 条训练数据
nohup .venv/bin/python -m finix_restore.cli \
  --input_dir "data/AFAC 训练数据集/finixdocbench_huge_table_100/images" \
  --work_dir outputs/table_train_run_v3 \
  --output_csv outputs/table_train_run_v3/submission_A_table_train_run_v3.csv \
  --config configs/table_v2.yaml \
  > outputs/table_train_run_v3.log 2>&1 &

# 2. 评分对比
.venv/bin/python -m finix_restore.eval.cli \
  --pred outputs/table_train_run_v3/submission_A_table_train_run_v3.csv \
  --gt "data/AFAC 训练数据集/finixdocbench_huge_table_100/mds" \
  --mapping_csv "data/AFAC 训练数据集/finixdocbench_huge_table_100/id_mapping.csv" \
  --output outputs/table_train_run_v3/metrics/table_eval.json

# 3. 对比 run_v2 (Overall 17.68) 与 run_v3 的 mean_overall / mean_table_teds
```
