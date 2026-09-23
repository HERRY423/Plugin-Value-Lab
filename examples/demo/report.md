# 插件价值评估

**example-plugin · 0.0.0-demo**

研究：tutorial-value-study  
证据类型：合成演示  
当前结论：**仅为模拟演示**

> **合成演示 · 不代表真实收益。** 分数、成本与差异只展示流程，不能宣称插件已被验证有效。

## 质量与成本

| 指标 | 未启用插件 | 启用插件 | 差值（启用 − 未启用） |
| --- | ---: | ---: | ---: |
| 结果质量 | 50.0% | 100.0% | +50.0 个百分点 |
| 成本 | 2.0100 USD | 1.0200 USD | -0.9900 USD |

成本缺失保持未知；估算金额不等于已结算费用。只有结果判据贡献质量评分。

## 样本完整性

- 计划运行：18
- 观察运行：18
- 完整配对：9
- 任务簇：3

同一案例的重复运行不等于独立样本。

成本汇总口径：mean per planned arm execution; positive delta costs more

## 阻断项

未记录阻断项；仍需结合完整性与结论边界判断。

## 需要关注

- Costs must include retries, model judges, setup, correction and review allocated consistently; omitted categories cannot be inferred

## 不确定性

- 状态：DESCRIPTIVE\_ONLY
- 计算方法：task-family cluster bootstrap, percentile 95%
- low：0.0
- high：0.8333333333333334
- resamples：2000
- seed：20260922
- 任务簇数：3
- caution：Exploratory interval, unstable with few families; family independence is declared, not verified. No causal test.

## 排除与未纳入项

未提供单独的排除汇总。

## 结论边界

- causal\_benefit：NOT\_ESTABLISHED
- external\_validation：NOT\_ESTABLISHED
- scientific\_authorization：NONE
- independence：DECLARED\_NOT\_VERIFIED
- decision\_scope：Descriptive within the frozen submitted task suite only
- human\_time：Declared timer records; authenticity not independently verified
- costs：Submitted USD values; estimates are not settled charges

## 逐案例证据

| 案例 | 类型 | 任务簇 | 未启用 | 启用 | 质量差 |
| --- | --- | --- | ---: | ---: | ---: |
| structured-delivery | task | delivery | 16.7% | 100.0% | +83.3 个百分点 |
| unrelated-request | negative | negative-control | 100.0% | 100.0% | +0.0 个百分点 |
| insufficient-science | abstention | evidence-boundary | 33.3% | 100.0% | +66.7 个百分点 |

### structured-delivery

- 启用插件 / 重复 1 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 1 / completed：质量 50.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 2 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 2 / completed：质量 0.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 3 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 3 / completed：质量 0.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "source",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "limits",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]

### unrelated-request

- 启用插件 / 重复 1 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 1 / completed：质量 100.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 2 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 2 / completed：质量 100.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 3 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 3 / completed：质量 100.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "answer",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": false,<br>    "weight": 1<br>  },<br>  {<br>    "id": "over-trigger",<br>    "passed": true,<br>    "rationale": "Literal absence check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  }<br>\]

### insufficient-science

- 启用插件 / 重复 1 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 1 / completed：质量 100.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 2 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 2 / completed：质量 0.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 启用插件 / 重复 3 / completed：质量 100.0%，成本 1.0200 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": true,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]
- 未启用插件 / 重复 3 / completed：质量 0.0%，成本 2.0100 USD。
  - 评分明细：\[<br>  {<br>    "id": "limit",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": true,<br>    "critical": true,<br>    "weight": 1<br>  },<br>  {<br>    "id": "activation",<br>    "passed": false,<br>    "rationale": "Literal content check (not semantic truth verification)",<br>    "scored": false,<br>    "critical": false,<br>    "weight": 1<br>  }<br>\]

## 来源

- 方案 SHA-256：c4727c53139b2051495e911dea84e923fcda5f25e0cf1496fe2da9e5632fad42
- records\_sha256：a70687cbbc3fc226677b4bb2ebfb114dcb3f57630ed335ca6d14973a90a4eb77
- engine：plugin-value-lab/0.1.0-alpha.1
- local\_lock：{<br>  "schema\_version": 1,<br>  "suite\_sha256": "c4727c53139b2051495e911dea84e923fcda5f25e0cf1496fe2da9e5632fad42",<br>  "frozen\_at": "2026-09-22T13:26:41.713459+00:00",<br>  "expected\_runs": 18,<br>  "attestation": "LOCAL\_CONSISTENCY\_ONLY"<br>}
- hash\_scope：Byte consistency only; no proof of execution, authorship, or preregistration time

方案锁用于一致性核验，不构成独立见证的预注册。外部来源不自动表示独立评审、因果归因或科学认证。

全部字段（包括扩展字段）保留在同目录的 `report.json`；交互式逐案例视图见 `report.html`。
