# 判定边界复测

本轮开始：2026-09-28T01:57:04.529892+00:00；完成：2026-09-28T01:58:09.242282+00:00。

这是已暴露反例上的开发集修正复测，未增加独立任务或获得独立标注。旧实验的 22/24 报警、19/24 配对净检出保持不变。

保留原八类、每类三个变异与合法对照；使用新的冻结契约和已修改检测器。96 次主要本地进程执行之外，另有 6 次只阻断评估文件访问的干预执行。无模型调用、真实宿主或付费。

| 类别 | 无访问观察：报警 | 无访问观察：配对净检出 | 加受控访问观察：报警 | 配对净检出 | 正常对照误报（去重） |
| --- | ---: | ---: | ---: | ---: | ---: |
| 多重检验错误 | 3/3 | 3/3 | 3/3 | 3/3 | 0/2 |
| ID 错位 | 3/3 | 3/3 | 3/3 | 3/3 | 0/2 |
| 伪重复 | 3/3 | 3/3 | 3/3 | 3/3 | 0/1 |
| 参考泄漏 | 1/3 | 1/3 | 3/3 | 3/3 | 0/2 |
| 静默后端回退 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 |
| 标签语义互换 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 |
| 过度拒答 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 |
| 触发失败 | 3/3 | 3/3 | 3/3 | 3/3 | 0/2 |

## 每项检查到底说明什么

- 决定、交付与正确性分开：over_refusal 保留 decision-only 语义；冻结的独立字段／任务答案检查负责发现空答案和错误答案。无有效 decision 时未知，不算确定拒答。
- 标签别名在运行前明确冻结；歧义或跨类碰撞拒绝。ARI/NMI 仍只检查划分，不改成字符串比较。
- 训练 ID 只在声明 unordered_paths 时按无重复集合检查；顺序变化不再报警，隐藏访问仍不能从声明判断。
- Skill 与读取候选内容分别记录。Read 必须有匹配的成功响应，并绑定冻结候选文件的完整内容；仅在保留原始字节及校验摘要时允许换行规范化。文件被读过不证明执行或因果贡献。格式化、截断或未知传输仍未知。
- 受控 Python 宿主在插件之外设置访问 hook，记录指定资源的 open 尝试，并用新进程阻断评估资源。它不读插件自报 model-state 来下判据，也不把结果相同当无泄漏。
- 访问尝试不等于已传输数据；hook 只覆盖本受审阅 Python 样例，不是通用原生宿主监控、恶意代码防护或 OS 沙箱。缺失／未完成观察保持未知。

## 干预原始结果

- reference-leakage-1 / with: exit=1, FORBIDDEN_ACCESS_ATTEMPT, 同源=True, 同输入=True, 同输出=False。
- reference-leakage-1 / without: exit=0, NO_FORBIDDEN_ACCESS_IN_OBSERVED_SCOPE, 同源=True, 同输入=True, 同输出=True。
- reference-leakage-2 / with: exit=1, FORBIDDEN_ACCESS_ATTEMPT, 同源=True, 同输入=True, 同输出=False。
- reference-leakage-2 / without: exit=0, NO_FORBIDDEN_ACCESS_IN_OBSERVED_SCOPE, 同源=True, 同输入=True, 同输出=True。
- reference-leakage-3 / with: exit=1, FORBIDDEN_ACCESS_ATTEMPT, 同源=True, 同输入=True, 同输出=False。
- reference-leakage-3 / without: exit=0, NO_FORBIDDEN_ACCESS_IN_OBSERVED_SCOPE, 同源=True, 同输入=True, 同输出=True。

正常样例在阻断下仍应保持原结果；变异样例受阻只说明这段受控程序对该访问有依赖，不能外推真实插件泄漏覆盖率。

协议摘要：`594fc146c602595a872c6f5159c612423dae951da47b4aedb32d85e124ab5549`。原始目录：`C:/Test/pvl-boundaries-20260927-r2`。
作者主动时间、真实误报处理成本、未见事故检出能力、自然触发概率和 PVL 净收益均未建立。
