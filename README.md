# 小影科技 2027 校招 AI Agent 笔试项目

本仓库包含四道项目题的完整 Python 实现。每个项目均可独立安装和运行，包含源码、合成数据、自动化测试、实际输入输出与 Trace，以及题目要求的五份设计文档。

| 题号 | 项目 | 入口 |
|---|---|---|
| 1 | 素材审核与发布排期 Agent | [`outputs/material-scheduling-agent/`](outputs/material-scheduling-agent/) |
| 2 | 内容任务规划 Agent | [`outputs/content-task-planning-agent/`](outputs/content-task-planning-agent/) |
| 3 | 企业知识问答 Agent | [`outputs/enterprise-knowledge-agent/`](outputs/enterprise-knowledge-agent/) |
| 4 | 短视频脚本 Agent | [`outputs/short-video-script-agent/`](outputs/short-video-script-agent/) |

各子项目的 `README.md` 提供环境安装、CLI 命令、真实模型入口、离线 Mock 边界和已知限制。所有业务资料均为合成数据，仓库不包含 API Key 或个人隐私数据。

## 快速评审

```bash
cd outputs/short-video-script-agent
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[dev]'
pytest -q
```

其他题目的安装与运行方式见对应目录。真实模型入口使用 OpenAI Responses API；未配置 `OPENAI_API_KEY` 时可使用明确标注的离线策略验证编排与安全护栏。
