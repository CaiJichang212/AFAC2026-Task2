# AFAC2026 Task2 - Finix 文档还原

复杂金融文档图片还原工具，基于 FinixDoc-VL API 将扫描文档转换为 Markdown 格式。

## 项目设计思路

### 核心问题
- 高分辨率长图/表格超出 API 单次处理能力上限
- 分块识别后需要正确拼接和去重
- 表格跨块分割后需要智能合并修复

### 设计理念
1. **分而治之**：将大图片智能切割为可处理的小块
2. **流水线架构**：各阶段独立且可缓存，支持断点续跑
3. **容错设计**：多用户轮询 + 重试机制，保证稳定性
4. **质量管控**：全流程质量检查，及早发现问题

### 关键技术
- 基于图像投影分析的智能分块（空白带对齐）
- 基于文本相似度的重叠去重
- HTML 表格结构修复和跨块合并
- 全链路缓存机制（基于 SHA1 校验）

---

## 代码运行流程

```
输入图片目录
    ↓
[配置加载] 读取环境变量和配置文件
    ↓
[输入验证] 检查图片完整性和文件名重复
    ↓
[逐图处理]
    ├─ 画像分析 → 分类文档类型（长图/表格/普通）
    ├─ 布局分析 → 检测空白带、裁剪框、表格密度
    ├─ 智能分块 → 按类型选择分块策略，生成重叠块
    ├─ API调用 → FinixDoc-VL 识别（优先缓存）
    ├─ 标准化 → 统一格式、过滤错误信息
    ├─ 顺序还原 → 按阅读顺序排序块
    ├─ 去重叠合并 → 精确匹配+模糊匹配去重
    ├─ 表格修复 → 补全标签、合并相邻表格
    └─ 质量检查 → 字符数、重复率、API失败率校验
    ↓
[输出CSV] 生成提交文件并验证格式
```

---

## 如何使用

### 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（.env 文件或直接设置）
FINIX_API_KEY=your_api_key
FINIX_USER_IDS=user1,user2,user3
# 可选：FINIX_API_URL=https://custom-endpoint.com/api
```

### 基本使用

```bash
python -m finix_restore.cli \
  --input_dir data/test_images \
  --output_csv outputs/submission.csv \
  --work_dir outputs/run
```

### 常用参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input_dir` | 输入图片目录（可多次指定） | 必填 |
| `--output_csv` | 输出 CSV 文件路径 | 必填 |
| `--work_dir` | 工作目录（缓存、日志、中间结果） | `outputs/run` |
| `--config` | 配置文件路径 | `configs/default.yaml` |
| `--limit` | 仅处理前 N 张图片 | 全部 |
| `--no-resume` | 忽略缓存强制重跑 | - |
| `--force-api` | 强制调用 API 忽略缓存 | - |
| `--dry-run` | 仅分块不调用 API | - |

### 配置文件示例（configs/default.yaml）

```yaml
api:
  timeout_seconds: 240
  max_retries: 3
  concurrency: 4
  per_user_concurrency: 1

chunk:
  long_window_height: 4000
  long_vertical_overlap: 320
  max_chunk_pixels: 12000000
  table_full_page_max_pixels: 16000000
  table_horizontal_overlap: 160
  table_vertical_overlap: 220

merge:
  dedup_window_chars_long: 1200
  dedup_window_chars_table: 600
  dedup_similarity_threshold: 0.88

quality:
  max_duplication_ratio: 0.18
  max_api_failure_ratio: 0.20
```

### 输出目录结构

```
outputs/run/
├── profiles/      # 图片画像 JSON
├── chunks/        # 切割后的图片块 + manifest
├── api_raw/       # API 原始返回（缓存）
├── normalized/    # 标准化后的分块内容
├── merged/        # 合并后的完整 Markdown
├── qc/            # 每张图片的质量报告
└── logs/          # 运行日志和配置快照
```

---

## 支持的图片格式

- `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`
