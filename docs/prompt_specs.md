# FinixDoc-VL 调用与解析约束

## API 范围

本工程最终提交版本只允许调用赛题指定的 FinixDoc-VL API：

```text
POST https://finixdocapi.alipay.com/api/finix_doc/call_with_file
```

请求字段：

```text
userId
apiKey
fileName
file
```

当前赛题 API 调用说明未提供 prompt、system prompt、temperature 或其他文本控制参数。因此本工程不维护额外 prompt 模板，也不通过其他模型补全文本。

## 解析约束来源

所有解析约束通过以下本地流程实现：

- `ImageProfiler`：按尺寸、像素和长宽比判断文档类型。
- `LayoutSentry`：用灰度投影和白边检测提供切块提示。
- `Chunker`：按长条滑窗或表格网格控制单次 API 输入尺寸。
- `MarkdownNormalizer`：只做保守格式修复，不改写金融数字、条款号、备案号。
- `ReadingOrderResolver`：按坐标和网格顺序恢复阅读流。
- `DedupMerger`：只在相邻 overlap 坐标约束下删除接缝重复。
- `TableMerger`：修复 HTML 表格闭合，保留空 `<td></td>`。
- `QualityGate`：检查空输出、重复、HTML 破损、CSV schema 和输入重名。

## 禁止事项

- 不调用 OpenAI、Claude、通义、Qwen、Gemini 或其他大模型 API。
- 不使用测试集文件名特判输出。
- 不在日志、文档或提交包中写入真实 `apiKey`。
- 不对金额、百分比、备案号、条款号做语义改写。
