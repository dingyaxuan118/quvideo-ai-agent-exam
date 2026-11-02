# 测试与评估

## 执行方式

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 验收矩阵

| 场景 | 输入 | 预期 | 实际材料 |
|---|---|---|---|
| 正常排期 | M01, 19:00 | 审核通过并保存草稿 | `examples/01-normal.json` |
| 信息缺失 | M02, 19:00 | 列出缺字段，不保存 | `examples/03-missing-data.json` |
| 规则风险 | M03, 19:00 | 阻断并给原因 | `examples/05-rule-risk.json` |
| 时段冲突 | M01, 18:00 | 建议 19:00，等待确认 | `examples/02-conflict.json` |
| 重复提交 | 同一正常请求两次 | draft ID 相同，第二次为 already_saved | `examples/06-duplicate.json` |
| 保存失败 | M01, 19:00 + 故障注入 | 明确失败，不声称成功 | `examples/04-save-failure.json` |
| 步数上限 | 循环模型，max_steps=2 | 返回 incomplete | 自动测试 |
| 越权动作 | 模型跳过审核直接保存 | 控制器拒绝，文件不落盘 | 自动测试 |
| 虚假成功 | 模型未保存却返回 draft_saved | 归一化为 failed | 自动测试 |
| 模型异常 | 模型抛出解析错误 | 返回 failed Trace，不崩溃 | 自动测试 |

## 评估结论

离线模式验证了工具编排、状态边界、失败处理、幂等保存和步数限制。冲突路径与保存失败路径均体现 observation 改变下一动作。
完整测试运行结果见 `examples/test-results.txt`。

## 已知限制

- 示例 Trace 来自离线策略 Mock，只证明流程和安全边界；真实模型决策质量需配置 API Key 后单独评测。
- JSON 草稿文件不支持多进程并发；生产环境需数据库唯一键和事务。
- 示例只比较 ISO 字符串；生产系统需时区解析、窗口容量与渠道规则。
- 本地规则为精确词匹配，不能替代专业内容安全审核。
