# 方案设计

## 动态循环

```text
模型选择动作
  → 控制器验证前置条件
  → 执行业务工具
  → 记录 observation 与步骤状态
  → 模型根据成本、耗时或失败结果重规划/保存/结束
```

初始尝试 premium 方案：成本 12、耗时 8 小时。lean 方案成本 8、耗时 5 小时。当预算为 10 时，模型观察 premium 超预算后必须生成 lean 脚本并重新估算，不能只改最终数字。

脚本工具发生一次可恢复故障时，模型保留已完成的素材检索结果，改用 lean 方案续跑。每次工具调用分别记录状态，因此不会把失败步骤覆盖成成功。

## 安全护栏

控制器校验主题、方案版本、最新脚本和最新估算；模型不能跳过步骤或使用陈旧估算保存。保存工具再次核验 `total_cost <= budget`、`estimated_hours <= deadline_hours`，并核对脚本和素材 ID 是否与方案版本一致。持久化记录包含脚本、素材清单、成本、耗时和业务任务。最终成功状态必须来自真实保存 observation；即使保存后恰好达到步数上限，也以真实落盘状态返回成功。

## 模型接入

真实模型使用 OpenAI Responses API 与 Pydantic Structured Outputs；离线策略 Mock 提供无密钥的可复现路径。Structured Outputs 写法依据 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。

未采用 Agent 框架；原生循环更便于展示状态保留、动态重规划和硬约束。生产环境应把 JSON 存储替换为带唯一约束和事务的数据库。
