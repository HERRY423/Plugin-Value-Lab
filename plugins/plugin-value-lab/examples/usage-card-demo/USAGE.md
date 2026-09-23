# 插件使用卡

**example\-plugin · 0.0.0\-demo**

研究：tutorial\-value\-study

状态：仅供设计试用，不能据此推荐实际使用

重新计算的结论：SIMULATION\_ONLY

仅对记录中的具体任务提供条件性参考。评分不会产生安装、权限或卸载操作。

## 适用范围

- 决策范围：仅限本次提交的具体任务及固定条件；不会自动外推到同类或新任务。
- 目标：quality
- 固定条件：{&quot;budget&quot;: {&quot;max\_turns&quot;: 10}, &quot;environment&quot;: &quot;synthetic\-fixture\-v1&quot;, &quot;host&quot;: &quot;offline\-tutorial&quot;, &quot;model&quot;: &quot;SIMULATED\-NO\-MODEL&quot;, &quot;tools&quot;: \[\]}
- 方案 SHA-256：c4727c53139b2051495e911dea84e923fcda5f25e0cf1496fe2da9e5632fad42
- 运行记录 SHA-256：a70687cbbc3fc226677b4bb2ebfb114dcb3f57630ed335ca6d14973a90a4eb77
- 条件 SHA-256：eb9bd8566defb2dc67fee1852aa7d39c2d8a1034d43f3b6ee95b0c483265c5ec

## 何时可优先试用

当前证据不能给出优先使用建议。

## 何时基线可能已足够

尚无可支持的基线优先观察。

## 先调查什么

### structured\-delivery

任务：Deliver a task result with a source reference and explicit limitations.

包含合成演示，不能转化为实际使用建议。

质量差（启用 − 未启用）：0.8333333333333334；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

### unrelated\-request

任务：What is 2 \+ 2? Give only the number.

包含合成演示，不能转化为实际使用建议。

质量差（启用 − 未启用）：0.0；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

### insufficient\-science

任务：Do passing local software tests prove clinical effectiveness? Explain the evidence limit.

包含合成演示，不能转化为实际使用建议。

质量差（启用 − 未启用）：0.6666666666666667；平均成本差（USD）：\-0.9899999999999998。

运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 6, &quot;planned\_runs&quot;: 6, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}

## 接下来怎么做

- 先冻结真实任务、两组相同的授权输入及比较条件，再收集真实运行和完整成本。
- 合成案例只用于演练记录和判读流程。
- 安装、连接、权限或卸载需求交由宿主及 Plugin Management 处理；本卡不授予任何变更权限。

## 何时重新核验

- 插件版本、配置、权限或依赖变化时重新核验。
- 模型、宿主、工具、运行环境或资源预算变化时重新核验。
- 任务、输入数据、数据访问范围、评分标准或质量与效率目标变化时重新比较。
- 出现新的失败、回退、人工纠正或成本证据时复核；此清单不创建定时监控。

## 证据阻断

未记录；不代表证据已获独立认证。

## 需要关注

- Costs must include retries, model judges, setup, correction and review allocated consistently; omitted categories cannot be inferred

## 限制

- 使用卡是观察范围内的临时参考，不是插件的通用质量认证或长期有效承诺。
- 来源、外部参与者、任务独立性与人工计时均为提交者声明；程序重算和哈希不证明数据真实性、实际执行或独立验证。
- 本地增益信号不建立因果收益、外部适用性或科学与临床有效性；科研结论仍需领域证据和研究者判断。
- 成本来自提交记录及人工费率折算；均值按每个案例每组的计划运行计算，估算费用不等于已结算支出。
- 基线足够的观察不构成自动停用、卸载、扩权或修改其他插件的授权。
- 原始任务文字保留在本地卡片中；向他人分享前应由用户检查其中的私有资料。

## 来源与完整性

- 证据类型：synthetic
- 证据层级：SIMULATION\_ONLY
- 运行计数：{&quot;failed\_runs&quot;: 0, &quot;missing\_runs&quot;: 0, &quot;observed\_runs&quot;: 18, &quot;planned\_runs&quot;: 18, &quot;runs\_with\_issues&quot;: 0, &quot;skipped\_runs&quot;: 0}
- 来源记录：{&quot;engine&quot;: &quot;plugin\-value\-lab/0.2.0\-alpha.1&quot;, &quot;hash\_scope&quot;: &quot;Byte consistency only; no proof of execution, authorship, or preregistration time&quot;, &quot;local\_lock&quot;: {&quot;attestation&quot;: &quot;LOCAL\_CONSISTENCY\_ONLY&quot;, &quot;expected\_runs&quot;: 18, &quot;frozen\_at&quot;: &quot;2026\-09\-22T13:26:41.713459\+00:00&quot;, &quot;schema\_version&quot;: 1, &quot;suite\_sha256&quot;: &quot;c4727c53139b2051495e911dea84e923fcda5f25e0cf1496fe2da9e5632fad42&quot;}, &quot;records\_sha256&quot;: &quot;a70687cbbc3fc226677b4bb2ebfb114dcb3f57630ed335ca6d14973a90a4eb77&quot;, &quot;suite\_sha256&quot;: &quot;c4727c53139b2051495e911dea84e923fcda5f25e0cf1496fe2da9e5632fad42&quot;}

来源真实性未获独立验证。完整字段保存在同目录的 `card.json`。
