# 02 方案设计

`DecisionModel` 每步从 `search_materials`、`estimate_duration`、`check_rules`、`finish` 中选择动作。工具结果作为下一步观察传回模型，控制器维护检索来源、草稿指纹、估时和规则检查状态。

时长工具按每秒 4 个中文字符/英文词的合成口播速度估算。规则工具检查素材事实、绝对化用语、无依据百分比和未支持产品陈述。检索按关键词相关度排序，因此改变主题会改变素材选择。

安全护栏：来源 ID 必须来自检索；规则检查前必须对完全相同草稿估时且不超限；`completed` 必须同时存在相同指纹的合格估时和通过检查。修改标题、分镜或来源都会改变指纹，旧检查自动失效。

真实模型通过 `responses.parse` 使用严格 Pydantic Structured Outputs。`OfflinePolicyModel` 只用于无密钥复现流程。
