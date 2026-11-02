# 企业知识问答 Agent

一个可运行、可替换知识库、可审计的 ReAct 风格问答 Agent。它在每一步执行“模型选择动作 → 工具执行 → 观察结果 → 模型调整或结束”，不会把固定工作流伪装成推理。

## 关键能力

- 文档检索与原文读取分离；未读取的文档不能被引用。
- 回答返回文档 ID、版本日期和逐字原文片段。
- 同一事项冲突时列出双方原文并请求确认，不按版本日期擅自裁决。
- 支持改写问题、带历史的追问、资料外问题、工具失败与最大步数保护。
- 控制器重新校验引用、动作前置条件和冲突；模型不能绕过工具或伪造成功。
- `openai` 是真实模型入口；`offline` 仅是明确标注的确定性流程 Mock。

## 目录

```text
data/documents.json       可替换的合成知识库
src/knowledge_agent/      Agent、模型决策、工具和 CLI
tests/                    26 项自动化测试
examples/                 实际输入、输出和 Trace
docs/                     需求、方案、评估、AI 使用、复盘
```

## 安装与运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[dev]'

# 离线可复现演示
knowledge-agent "年假要提前多久申请？"
knowledge-agent "费用发生后多久内报销？"
knowledge-agent "VideoPro 支持哪些字幕？" --fail-search-once

# 带上下文的追问
knowledge-agent "要提前多久？" \
  --history-json '[{"role":"user","content":"我想申请年假"}]'

# 真实模型入口（需自行设置密钥）
export OPENAI_API_KEY="..."
knowledge-agent "年假要提前多久申请？" --backend openai --model gpt-5-mini

pytest -q
```

CLI 输出为 UTF-8 JSON，包含 `answer`、`citations`、`conflicts`、`information_gaps`、`follow_up_question`、`task_status` 和完整 `trace`。

## Trace 示例

明确答案路径：

```text
search_documents → read_excerpt → finish(answered)
```

冲突路径：

```text
search_documents → read_excerpt(D01) → read_excerpt(D02)
→ finish(needs_clarification)
```

工具临时失败路径：

```text
search_documents(timeout) → search_documents → read_excerpt → finish(answered)
```

## 安全边界

- 数据均为合成数据，不含个人信息或真实公司制度。
- `.env` 已忽略，仓库不包含密钥。
- 检索是便于离线验收的轻量词法实现，不等同生产级向量检索。
- 冲突识别按同一 `topic` 的不同原文触发。生产环境应补充适用人群、地区、制度层级和失效日期元数据。
- 离线 Mock 只证明编排与护栏；真实模型质量需在配置 API Key 后单独评估。
