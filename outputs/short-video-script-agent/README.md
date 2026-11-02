# 短视频脚本 Agent

一个以事实素材为边界、能够根据时长与品牌检查结果动态修稿的 Python ReAct Agent。

## 能力

- 输入主题、受众、平台、目标时长和风格，输出标题、分镜、旁白/字幕、预计时长、素材 ID、风险和状态。
- 动态执行 `检索 → 生成首稿并估时 → 超时压缩 → 重新估时 → 规则检查 → 结束`。
- 无素材时采用不同查询补充检索；工具临时失败由模型观察后决定重试。
- 最终成功必须基于同一脚本指纹的真实时长与规则检查，不能复用旧结果。
- 时长按分镜取旁白时长、字幕阅读时长和最低展示时长的最大值。
- 拒绝未检索来源、素材外数字效果、绝对化用语和未支持的产品功能。
- 最终来源还必须与原始主题达到最高相关度，不能用无关但已检索的素材绕过。
- 提供 OpenAI Responses API 真实模型入口；离线策略只是流程 Mock。

## 安装运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[dev]'

script-agent \
  --topic "VideoPro 字幕功能" \
  --audience "短视频创作者" \
  --platform "抖音" \
  --duration 30 \
  --style "简洁"

# 故障路径
script-agent --topic "VideoPro 字幕功能" --audience "创作者" \
  --platform "抖音" --duration 30 --style "简洁" --fail-estimate-once

# 真实模型入口
export OPENAI_API_KEY="..."
script-agent --topic "VideoPro 字幕功能" --audience "创作者" \
  --platform "抖音" --duration 30 --style "简洁" --backend openai

pytest -q
```

默认最大 12 步，耗尽后返回 `incomplete`。数据位于 `data/materials.json`，均为合成素材。

## 两条代表路径

```text
正常但首稿超时：search_materials → estimate(超时) → estimate(压缩稿合格)
                 → check_rules → finish(completed)

无素材：search_materials(空) → search_materials(改写后仍为空)
       → finish(needs_input)
```

## 边界

词法检索、时长公式和规则检查是可重复验收的本地模拟。真实语速会受停顿、英文读法和配音风格影响；生产环境应接入 TTS 时长测量和更完整的事实抽取。离线策略不代表真实模型决策质量，真实入口需配置 API Key 后另行评测。
