# 内容任务规划 Agent

第二题的 Python CLI 实现。Agent 根据主题、预算和剩余截止时间检索素材、生成脚本、估算成本；观察到超预算、超时或工具失败后会重规划，并保留已成功步骤。只有满足约束的方案才能保存。

## 评审入口

- Agent 循环与安全护栏：`src/content_planner/agent.py`
- 模型决策：`src/content_planner/decision.py`
- 业务工具：`src/content_planner/tools.py`
- 可执行测试：`tests/test_agent.py`
- 实际运行记录与测试结果：`examples/`
- 需求、方案、评估、AI 使用与复盘：`docs/`

## 安装

要求 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 运行

离线评审模式：

```bash
content-planner --theme 新品推广 --budget 10 --deadline-hours 12
```

预算为 10 时，Agent 会先观察到 premium 方案成本为 12，再改用成本为 8 的 lean 方案，重新生成、估算并保存。

故障恢复：

```bash
content-planner --theme 新品推广 --budget 10 --deadline-hours 12 \
  --fail-script-once
```

真实模型模式：

```bash
export OPENAI_API_KEY=your_key
content-planner --mode openai --model gpt-5-mini \
  --theme 新品推广 --budget 10 --deadline-hours 12
```

不安装项目也可运行测试：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 输出

- `task_plan`：最终业务任务、产物和可执行状态。
- `step_status`：每次工具步骤的成功、失败状态；失败历史不会被覆盖。
- `tool_results`：结构化工具结果；失败步骤不会标为成功。
- `script` / `asset_ids`：最终脚本和素材清单。
- `selected_variant`：最终选择的 premium 或 lean 方案。
- `total_cost` / `estimated_hours`：最终估算。
- `save_status`：`not_attempted`、`saved`、`already_saved` 或 `failed`。
- `task_status`：`plan_saved`、`incomplete` 或 `failed`。
- `trace`：动作、参数、工具 observation 和简短决策依据。

## 边界

- 默认最多 10 个决策步骤，达到上限明确返回未完成。
- 控制器强制“检索 → 生成 → 估算 → 约束检查 → 保存”的前置条件，模型不能绕过。
- 保存工具会再次核验预算和截止时间。
- 保存记录包含最终脚本、素材 ID、成本、耗时和三项业务任务，不只是方案元数据。
- 相同主题、预算和截止时间使用稳定幂等键，即使重规划结果变化也不会重复创建。
- 离线模型用于可复现流程验证，不证明真实模型决策质量。
