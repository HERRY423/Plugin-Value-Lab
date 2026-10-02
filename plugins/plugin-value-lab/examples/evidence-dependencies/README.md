# Local dependency recheck fixture / 局部复核制造案例

All data and dependency identities are manufactured. `SIMULATION_ONLY` remains unchanged. The graph maps two existing display rows solely to exercise routing; it is not a scientifically validated explanation of those rows.

从仓库根目录运行 [操作说明](../../docs/history/EVIDENCE-DEPENDENCIES.zh-CN.md#本地运行) 中的两条命令。第一次只运行旧 JSON 格式检查；第二次模拟检索 API 变化，保留该格式检查并标记检索建议待复核。

To exercise an unknown change, replace the second inventory with `inventory-unknown.json` and choose another fresh output directory. Every declared rule must then be revisited. `plan` only creates pending work; `replay` checks frozen bytes; `rescore` runs supported old-artifact checks. None launches a model or scientific computation.

文件：

- `card.json`：由已有演示评价器产生的原始合成使用卡。
- `graph.json`：卡摘要绑定、逐层依赖、完整性声明、规则范围。
- `retrieved.json`：冻结的模拟旧产物。
- `inventory-before.json`：模拟原条件。
- `inventory-tool-changed.json`：只有工具接口身份发生变化。
- `inventory-unknown.json`：新增无法映射的变化，要求扩大复核。

真实使用时须由操作者核对图与原卡的关系，使用真实内容摘要和修订身份，覆盖新增失败、成本、复核及任务分布变化。此例中的 `fixture-v1` 不可作为真实身份。
