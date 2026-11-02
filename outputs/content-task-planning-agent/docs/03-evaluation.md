# 测试与评估

## 运行

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 验收矩阵

| 场景 | 预期 | 证据 |
|---|---|---|
| 正常完成 | premium，成本 12，完整脚本和素材清单保存成功 | `examples/01-normal.json` |
| 缺预算 | 不调用工具，返回 incomplete | `examples/02-missing-input.json` |
| 工具失败 | premium 脚本失败，保留检索结果并以 lean 续跑 | `examples/03-tool-failure-recovery.json` |
| 预算超限 | 12 超过预算 10，切换为成本 8 的 lean | `examples/04-budget-replan.json` |
| 无可行方案 | premium/lean 均不满足，返回缺口 | `examples/05-no-feasible-plan.json` |
| 重复执行 | plan ID 相同，第二次 already_saved | `examples/06-duplicate.json` |
| 保存失败 | 明确 failed，不虚报保存 | `examples/07-save-failure.json` |

完整测试输出见 `examples/test-results.txt`。

## 结论与限制

离线评测验证了动态重规划、部分成功状态保留、幂等、失败处理和最大步数。真实模型适配器已通过结构化输出模拟测试，但未在仓库中保存真实 API 调用结果；配置 API Key 后应补跑真实模型案例。

JSON 文件不支持生产级并发；成本和耗时是合成单位，未包含真实供应商报价、日历和时区。
