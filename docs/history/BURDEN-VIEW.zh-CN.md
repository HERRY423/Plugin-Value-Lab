# 独立负担视图

2026-10-01，按用户要求增加上下文压力、费用、耗时的取舍视图，版本保持 0.8.0。原评分、组合可行性、最小插件选择、并列处理和自动操作权限均不改变。

## 阅读结果

组合分析返回 `burden_view`，现有 `plan-use` 导出的 PLAN.md 增加独立章节；ChatGPT/Codex 可解释 MCP 返回的同一对象。历史记录仍显示费用和耗时，缺失上下文保持未知。原可行性 FAILED/UNKNOWN 的候选保留，不进入两两排序。

比较范围是通过全部原逐任务质量、成功率、费用、耗时、关键检查和回归护栏的候选。费用为原评分器重算的完整声明费用，含人工折算与附加成本，不认证账户结算。耗时沿用原 duration_seconds，不擅自称为端到端或人工时间。

- LEFT_DOMINATES / RIGHT_DOMINATES：每个任务的三项负担均不更差，至少一项更低。
- TRADEOFF：完整观察中存在相反方向的差异，可能来自不同指标或不同任务；列出任务、指标和差值。
- EQUAL：差异在 1e-12 算术容差内，不表示统计等效。
- UNKNOWN：任一所需值缺失，保留已有方向，不推断完整关系。

每个任务先平均重复运行，再对任务等权汇总。表格均值仅用于浏览，支配判断使用全部逐任务指标，不能抵消某任务上的退步。没有合格候选为 NOT_ASSESSED；仍有可行性或上下文未知候选时为 PARTIAL。fully_observed_nondominated 只列完整观察中未被支配的候选，不排除未解决候选。没有加权总分、自动择优或新推荐。

## 可选上下文材料

既有 plugin_combination 分析请求可选增加 burden_observations，不改旧设计、原观察或其摘要。完整结构见[组合请求 Schema](../../schemas/plugin-combination.schema.json)。这是补充观察，不认证预注册、执行、来源或覆盖真实性。

顶层字段为 format（pvl-context-observations-1）、design_sha256、measurement、runs。

measurement 包含 host、model、host_version、source、sampling、context_window_tokens。host/model 必须匹配原冻结条件；其余字段声明统一宿主版本、来源和正整数窗口容量。本版只支持 sampling=each_main_agent_request，覆盖主代理每次请求，不混入子代理。不同模型、窗口、宿主或采样语义不能合并冒充同一种测量；提交者须据原始记录声明一致性。

每行包含 case_id、repetition、arm、session_id、record_sha256、coverage、expected_samples、samples。运行必须已在原观察中出现，会话和原 record 的规范 JSON 摘要必须匹配。coverage 为 complete 或 partial；samples 为按 request_index 递增的 {request_index,input_tokens} 列表，索引从 1 开始。重复、越界、未知运行、错配摘要、负数、非有限值及布尔 token 均拒绝。每运行最多 10000 样本，材料总计最多 100000 样本。

指标为每运行最大采样输入 token / 固定窗口容量，再按重复、任务汇总。需要 complete 声明且所有预期请求索引存在；partial、空序列或缺请求仅保留已观察峰值，不进入完整峰值比较。真实零值允许，缺失不补零。压缩后下降不抹去先前峰值；不推测压缩原因、累计消费、语义质量或因果关系。

报告分别保存原设计、原观察、新材料摘要，标明 SUBMITTED_NOT_HOST_ATTESTED。合成研究始终为 SIMULATION_ONLY，上下文材料不提升旧证据等级。未传可选字段时旧调用继续工作。

## 演示与验证

```text
python examples/plugin-combinations/burden_demo.py --output work/burden-view-demo
python scripts/value_lab.py plan-use work/burden-view-demo/tradeoff-context.json --output work/burden-view-cli
python -m unittest tests.test_burden_view tests.test_plugin_combinations
```

四个制造场景覆盖支配、费用与上下文/时间取舍、持平和缺失上下文；经过既有规划入口和原评分器，不调用真实模型或插件。输出目录必须未存在。

验证覆盖原推荐和旧报告字段不变、输入不变、逐任务反转、缺失/部分采样、压缩式下降、会话与摘要错配、污染与未知成本/耗时、Schema、Markdown 和既有 MCP 入口。真实宿主采集器和真人收益评估不在本次范围。

[本地验收记录](../evidence/burden-view-20261001.json)：专项 47 项通过，完整回归 1092 项通过、零跳过；接口冻结、插件结构、镜像及差异格式检查通过。验收绑定源码摘要，未发布或更新已安装宿主插件。
