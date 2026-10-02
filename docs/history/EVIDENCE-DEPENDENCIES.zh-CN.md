# 使用卡的局部证据复核

2026-10-02，按用户明确要求增加本地依赖管理。版本保持 0.9.0；主 CLI、MCP 和旧卡失效规则保持兼容。新增独立模块入口 `python -m value_lab.evidence_dependencies`。这是源代码功能，不代表已安装宿主验收、真实节省、科学有效性或用户采用。

## 做到什么

既有使用卡保持不可变，旁边保存一份声明的依赖图和逐次复核记录：

`使用建议 → 支持结论 → 验证规则 → 原始产物 → 插件／工具／环境依赖`

建议用原卡的 JSON pointer 定位；整个原卡摘要绑定，避免把另一张卡的检查挪过来。每项规则记录影响原因、依赖路径、所需证据类型、保留理由和旧检查来源修订。重复更新不会把失败、未知、待重执行或待人工复核自动改成通过。没有映射的建议单独列出，仍按旧卡规则处理。

依赖图不是自动发现，也不证明关系完整。`coverage.complete` 和 `coverage.basis` 是操作者声明；当前 inventory 也是显式提供的身份快照，不是实时宿主检测。摘要只用于既有材料的本地绑定，没有新建签名、注册或中央平台。

## 哪些变化影响哪些路径

依赖叶子按插件、工具、模型、宿主、环境、任务分布、配置、预算、判据和新增证据分类。inventory 使用叶子 ID → 身份字符串；未确认身份填 null。插件必须记录内容摘要，模型／宿主记录明确修订，工具记录接口版本或内容摘要，不能只使用可漂移别名。新增失败、成本或复核材料也必须更新 `new_evidence`；它不是“没有变化”的默认开关。

两种规则范围决定如何追溯：

| 范围 | 路径与证据边界 |
| --- | --- |
| `historical_artifact` | 检查这份冻结旧文件。依赖追溯到文件为止，不把生产该文件的当前工具状态当作旧文件内容变化。显式挂在规则上的依赖仍生效。 |
| `current_behavior` | 继续追溯原产物的生产依赖；接口、插件字节、模型等改变后要求新的模型或科学计算执行。 |

例如 API 更新时，原文件字节及规则不变，旧 JSON 格式检查可保留；检索行为建议进入待复核。若格式规则本身改变，只重新评分该规则。若原文件缺失或摘要变化，相关检查保持 UNKNOWN，绝不偷偷重新绑定摘要。明确换了原始产物或规则，可以提供新的 graph，但相关建议仍需复核。

以下情况保守扩大到全部已声明规则：覆盖不完整、缺少必要变化类别、必要类别虽已声明但未连接到当前行为证据路径、依赖身份缺失／未知、inventory 出现未映射依赖、关系增删、覆盖声明改变、检查实现或运行时改变。删除的节点单独列入变更记录。所有 Python 运行时模块的内容摘要以及 Python／平台身份参与检查实现绑定。扩大复核不会自动启动模型或科学计算。

依赖关系声明错误仍可能遗漏影响；本机制不会据此自动认证整卡。它不能检测未被提交的接口变化、隐蔽模型别名漂移、未上报的新失败或任意第三方环境变化。

## 三种新证据分开记录

| 动作 | 实际新增内容 | 不支持的推断 |
| --- | --- | --- |
| `plan` | 影响路径和待办 | 没有执行检查 |
| `replay` | 原始字节仍与冻结摘要相符 | 不等于结果正确，更不等于再次检索或计算 |
| `rescore` | 对受影响旧产物运行已有内置判据；未受影响已完成检查保留 | 不等于模型重跑、科学计算重跑或实际收益 |
| `model_execution` / `scientific_execution` 待办 | 只列出独立执行需求 | 此模块不启动执行，也不接受一句“已执行”来清除待办 |

本版可执行局部检查覆盖自包含的 JSON 字段、标签表和 DE 表已有判据。任意可执行评分器、外部评分参考和其他格式暂不接入，避免遗漏它们的代码与参考依赖。DE 表检查只是数值契约检查，不会重新拟合科学模型，也不会授权科学实验。

当前行为检查从首次建图开始就标记 `REEXECUTION_REQUIRED`，因为旧卡没有足够的逐路径执行收据供安全导入；原卡结论另以 `SOURCE_GUIDANCE_ONLY` 保留且不升级。局部检查通过表示检查层已完成，不能自动证明支持结论成立。变化触发的建议保持 `REVIEW_REQUIRED`；完成实际重执行及原有评价后，生成新使用卡，再为新卡建立新的依赖修订。跨卡迁移、自动接收新执行收据和自动解除建议复核尚未实现。

## 本地运行

从仓库根目录运行，输出目录每次必须为新目录。可复制的例子见 [制造案例](../../examples/evidence-dependencies/README.md)。输入包括原 `card.json`、符合 [结构模式](../../schemas/evidence-dependencies.schema.json) 的 graph、当前 inventory，以及原始产物目录。

```powershell
python -m value_lab.evidence_dependencies rescore --card examples/evidence-dependencies/card.json --graph examples/evidence-dependencies/graph.json --inventory examples/evidence-dependencies/inventory-before.json --artifacts examples/evidence-dependencies --output work/dependency-first
python -m value_lab.evidence_dependencies rescore --card examples/evidence-dependencies/card.json --graph examples/evidence-dependencies/graph.json --inventory examples/evidence-dependencies/inventory-tool-changed.json --artifacts examples/evidence-dependencies --previous work/dependency-first/revision.json --output work/dependency-api-change
```

查看新目录的 `RECHECK.md` 和 `revision.json`。第二次格式评分次数应为 0，格式检查保留，检索建议需要复核。原卡的 `SIMULATION_ONLY` 上限不变。`plan` 和 `replay` 使用同样参数；随后可用 `rescore --previous ...` 完成尚未评分的局部检查。

结构模式只校验形状；运行时另行校验精确原卡绑定、重复 ID、层级、悬空依赖、路径安全及评分器支持范围。层级约束禁止环。输出保存旧修订摘要以追溯历史，但不认证提交者或执行真实性。

## 验证与下一步

`python -m unittest tests.test_evidence_dependencies -v` 验证定向失效、保留时确实不调用评分器、判据变化、未知影响扩大、文件缺失与修改、禁止执行代码、重复更新不会消除待办、计划与重放不能替代重评分、科学计算与模型执行区分，以及旧卡合成证据上限不升级。

`python scripts/check_evidence_dependencies.py --output work/dependency-acceptance` 在新目录运行四种可核对情形，保存每次 `revision.json`、`RECHECK.md` 和总体验收记录 `acceptance.json`：首次评分 1 次、接口变化后评分 0 次、未知变化后评分 1 次、仅重放时评分 0 次。

这些是制造案例和本地工程测试。下一步用真实使用卡人工核对依赖图，再比较局部补测与完整复测是否漏掉影响。只有该比较积累了证据，才能声称规则可靠或减少实际成本。共享脱敏失败模式仍需单独授权。
