## FinixDoc-VL 输入图片尺寸

### 一、可接受的尺寸范围（像素预算 pixel budget）

来自 FinixDocBench 公开 JSON schema 的 `min_pixels` / `max_pixels` 字段（即模型预处理流程实际记录的预算）：

| 字段 | 值 | 含义 |
|------|----|----|
| `min_pixels` | **4096 像素**（约 64×64） | 单图像下限，低于此模型基本无法识别 |
| `max_pixels` | **16,777,216 像素 = 16M（约 4096×4096）** | 单次推理的图像像素上限 |

也就是说，**单张图（或单个切片）的总像素建议落在 ≈4 K 到 ≈16.78 M 之间**。超过 16M 像素的页面会触发 split-then-merge 流程，由系统先切分再合并，而不是整页直接喂给 VLM。

技术报告中也明确指出：当文档"超过 1 亿像素（>100 M pixels）"时，单次直接送入 VLM 几乎无法处理（要么下采样丢细节，要么 token 超限），必须切分后再合并；FinixHuge-Long / FinixHuge-Table 子集的极端样本峰值已达 287 M / 386 M 像素，仅供"系统级可处理性"评测使用，不是常规可直接调用的尺寸。

### 二、最佳尺寸（推荐工作点）

综合 README_zh 的 schema 示例（`resized_width=992, resized_height=1408`，约 1.4 M 像素）以及 [API 文档第六节](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/FinixDoc-VL的API调用说明.md#L66-L72)对"切片不要过大、否则超时"的提示：

- **最佳单图/单切片像素**：≈ **1 M – 4 M 像素**，对应常见纸面尺寸大约 **1000×1400 ~ 2000×2000**（A4 200–300 DPI 扫描件正好落在这个区间）。
- **硬上限**：`max_pixels = 16,777,216`（≈ 4096×4096），逼近此值时延迟会显著增加，应主动切片。
- **下限**：`min_pixels = 4096`（约 64×64），过小图（如缩略图）会被拒识或精度急剧下降。
- 长边建议 ≤ 4096 px；超长票据/超大表格建议先按段切分到 ~3000×3000 以内再调用，符合赛题方"合理控制大图切片尺寸"的官方建议。

### 三、本项目可执行的结论

针对 Task2 提交流水线，建议在预处理阶段：
1. 长边超过 4096 或总像素超过 16 M 的页面，按 `max_pixels=16,777,216` 做等比缩放或切片；
2. 目标工作点放在 **总像素 ~1–4 M、长边 1500–3000** 区间，兼顾识别精度与超时风险；
3. 极小图（<4096 px²）做最近邻放大到至少 ~256×256 再送入，避免触发下限。

Sources:
- [FinixDocBench README_zh.md](https://huggingface.co/datasets/inclusionAI/FinixDocBench/blob/main/README_zh.md)
- [FinixDoc 技术报告 PDF](https://openreview.net/notes/edits/attachment?id=cB3BkE2K1R&name=pdf)
- [FinixDoc-VL的API调用说明.md](file:///Users/lzc/TNTprojectZ/AprojectZ/AFAC2026-Task2/docs/FinixDoc-VL的API调用说明.md)