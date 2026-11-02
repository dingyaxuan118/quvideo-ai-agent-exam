# 素材审核与发布排期 Agent

第一题的 Python CLI 实现。Agent 会读取素材、审核规则、查询排期，并根据工具返回动态决定继续、建议替代时段、请求确认、阻断或停止。它**只保存草稿，绝不执行真实发布**。

## 评审入口

- 核心循环：`src/material_agent/agent.py`
- 模型决策：`src/material_agent/decision.py`
- 业务工具：`src/material_agent/tools.py`
- 可执行测试：`tests/test_agent.py`
- 实际运行记录及测试结果：`examples/`
- 设计与评估：`docs/`

## 环境与安装

要求 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

安装完成后运行测试：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 运行

离线评审模式（无需 API Key）：

```bash
PYTHONPATH=src python -m material_agent.cli \
  --material-id M01 \
  --desired-time 2026-11-01T19:00 \
  --draft-file /tmp/material-agent-drafts.json
```

冲突场景：

```bash
PYTHONPATH=src python -m material_agent.cli \
  --material-id M01 \
  --desired-time 2026-11-01T18:00
```

用户确认替代时段后：

```bash
PYTHONPATH=src python -m material_agent.cli \
  --material-id M01 \
  --desired-time 2026-11-01T18:00 \
  --confirmed-time 2026-11-01T19:00
```

真实模型模式：

```bash
export OPENAI_API_KEY=your_key
PYTHONPATH=src python -m material_agent.cli \
  --mode openai \
  --model gpt-5-mini \
  --material-id M01 \
  --desired-time 2026-11-01T19:00
```

真实模型通过 OpenAI Responses API Structured Outputs 每一步选择下一动作。离线 `OfflinePolicyModel` 无需 API Key，是可复现的流程 Mock，只用于验证编排、边界和异常处理，不作为真实模型决策效果的证明。

## 输出字段

- `review_status`：审核结果。
- `risk_reasons`：风险或缺失原因。
- `requested_time` / `suggested_time`：原始要求及建议时段。
- `pending_confirmation`：需要用户确认的事项。
- `draft_save_status`：`not_attempted`、`saved`、`already_saved` 或 `failed`。
- `task_status`：`draft_saved`、`pending_confirmation`、`blocked`、`incomplete` 或 `failed`。
- `trace`：每步动作、参数、工具返回摘要及下一步依据。

## 安全与边界

- 工具集中没有“发布”能力，保存结果固定为 `status: draft`。
- 控制器会硬性校验“已读取 → 审核通过 → 查询时段 → 获得确认 → 保存”前置条件；不能仅靠模型声称成功。
- 冲突时默认只建议替代时间并等待确认。
- 幂等键由素材、原始时段和最终时段组成，重复提交不会新增草稿。
- 默认最多执行 8 步；达到上限明确返回 `incomplete`。
- 不记录模型内部思维过程，只保存面向评审的简短决策依据。
