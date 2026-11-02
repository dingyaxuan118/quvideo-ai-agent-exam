# 方案设计

## 调用流程

```text
用户请求
  → 决策模型选择动作
  → 工具执行并返回结构化 observation
  → 决策模型根据 observation 选择下一动作
  → 完成 / 待确认 / 阻断 / 失败 / 达到步数上限
```

模型可选择 `read_material`、`check_rules`、`query_slots`、`save_draft` 或 `finish`。Agent 控制器只负责执行动作、记录 observation 和限制步数，不替模型预设固定调用链。真实模型入口使用 OpenAI Responses API；离线策略模型提供确定性复现。

## 动态决策

- 素材缺字段：模型观察规则工具结果后停止并要求补充。
- 规则风险：模型阻断，不查询时段或保存草稿。
- 时段冲突：模型从工具提供的替代时段中选择建议；没有用户确认时结束为 `pending_confirmation`。
- 保存失败：模型观察失败后结束为 `failed`。
- 工具异常或未知结果：安全停止。

## 工程取舍

选择 Python 标准库实现业务层，减少评审环境依赖。真实模型使用 OpenAI SDK，并用 Pydantic Structured Outputs 约束动作名称、参数和结束状态。数据用 JSON 表达，便于替换内容验证答案是否随工具结果变化。

草稿保存使用稳定 request key 和确定性 draft ID 实现单进程演示所需的幂等性。生产环境应使用数据库唯一约束和事务。

## 安全边界

系统没有发布工具，保存记录始终标为 `draft`。控制器还会确定性校验素材 ID、原始时间和调用前置条件；模型不能跳过审核直接保存，也不能在没有真实保存 observation 时声称成功。即使模型生成未知动作，也会被工具白名单拒绝。最大步数默认 8，避免无穷工具调用。

## 框架说明

未使用 Agent 框架；循环、工具白名单、Trace 与步数限制均为小型原生实现。真实模型使用 `openai` Python SDK 的 Responses API，SDK 负责 HTTP 接入，不承担编排决策。

Structured Outputs 写法依据 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)，使用 `responses.parse(..., text_format=...)`，解析或拒绝异常由 Agent 记录为失败并安全停止。
