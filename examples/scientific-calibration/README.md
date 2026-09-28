# 三类科学判据的开发校准

本包 22 个公开制造案例，不是留出集、真实用户结果或独立专家认可的真值。标签在 manifest 中明确提供；正例、错误、合理变体、参考缺失与方法争议全部保留。`build.py` 可复建相同字节，配对参考使用手工可核算值，不调用待校准判据生成真值。

```powershell
python scripts/value_lab.py diagnose examples/scientific-calibration/manifest.json --audit --verifiers examples/scientific-calibration --output work/scientific-calibration-new
```

| 检查 | 合法变化 | 定向错误 | 不确定边界 |
| --- | --- | --- | --- |
| 完整检验集合上的 BH | 行重排、表示精度、零值和并列 p | 未做反向最小值、删除待检项、非有限效应 | 参考改变／产物缺失；BY 是否可接受取决于任务要求 |
| 实体对应的聚类分区 | 簇名置换、行重排 | 实体成员交换、缺失／重复 ID | 参考哈希失配；分区相同不证明生物标签正确 |
| 供体配对的精确检验 | 特征重排、合法不显著结果 | 用细胞数冒充重复、分析单位错误、效应方向反转 | 供体配对不完整；身份和可交换性仍是声明 |

BH 按指定方法检验。其适用假设见 [SciPy 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)。ARI 对簇标签置换不变，见 [scikit-learn 官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html)。实际校准测试另用 SciPy 的 BH 和配对置换检验交叉核算；独立软件实现不等于独立科学审阅。供体精确检验不能替代 pseudobulk 计数模型。

本包使用已有内置 artifact、numeric_tolerance、replicate_effect 判据。没有新增评分器，也不允许审计执行提交的程序。22 个案例的通过／失败／未知预期可在 `manifest.json` 查看；`disputed` 排除于二元检出率，不作为正确检出计数。

旧 `examples/detector-corpus` 中的漏检和误报继续保留。新包的定向检查不能覆盖被篡改的原始 p 值、未经认证的供体身份或所有合理替代方法，不能用新包“全符合预期”覆盖旧问题或宣称现场准确率。
