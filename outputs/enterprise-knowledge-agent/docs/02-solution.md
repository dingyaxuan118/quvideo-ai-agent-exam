# 02 方案设计

## 架构

`KnowledgeAgent` 维护已检索文档 ID、已读取可信原文和观察历史。`DecisionModel` 每步只能选择 `search_documents`、`read_excerpt` 或 `finish`。`KnowledgeTools` 从 JSON 知识库重新读取数据，不接受模型传入的正文。

真实模型使用 OpenAI Responses API 的 `responses.parse` 与 Pydantic Structured Outputs。离线策略只用于无密钥演示和确定性测试，代码中明确标为 Mock。

## 动态决策

- 初次检索无结果：模型可改写并补充检索。
- 检索命中：逐个读取候选原文，再决定回答或继续查证。
- 临时检索失败：根据 `retryable` 观察重试。
- 非临时读取失败：停止并标记失败。
- 同主题多份原文不一致：列出冲突并请求权威确认。

这些路径由观察结果驱动，不是工具内部的自动重试。

## 双层护栏

控制器只允许读取真实检索结果；故障注入参数来自用户请求，模型不能关闭。结束时逐条验证文档已读、版本相同、quote 是 excerpt 的非空子串。同主题检索候选必须全部读取后才能回答，避免只读一份冲突制度。`answered` 必须至少有一条有效引用，最终答案由已验证原文重建；同主题结构化 claim 冲突即使被模型误报为 `answered`，也会强制改为 `needs_clarification`。

最大执行步数默认为 10，耗尽时返回 `incomplete`。
