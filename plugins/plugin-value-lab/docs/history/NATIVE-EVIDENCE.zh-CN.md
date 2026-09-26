> 归档于 2026-09-25；保留既有接口和实施历史，不代表当前主线或重新验收。当前入口见 [README](../../README.zh-CN.md) 与 [操作指南](../OPERATIONS.md)。

# 原生科研文件附加诊断

这条路径复用已有 Claude `prompt.md`、`case.yaml`、graders 和原生执行流程。PVL 只增加一个小型文件映射与科研评分合同，不把科研评分器转换成关键词检查，也不要求重写整套用例。

当前支持：受控 CSV/TSV 和 JSON 的内置离线检查。现有 `import-claude` 保持诊断导入边界。新接口不会把操作者提供的文件映射升级成可信宿主证明，不执行产物中的代码，也不启动模型。

## 1. 冻结附加合同

原有插件放在 `candidate/`，评分参考放在独立的 `scorers/`，计划放在 `study/`；三者不能互相包含。合同举例：

```json
{
  "schema_version": 1,
  "plugin_files": ["skills/csv-analysis/SKILL.md"],
  "cases": [{
    "name": "csv-analysis",
    "case_directory": "evals/csv-analysis",
    "repetitions": 3,
    "inputs": {"measurements": "input.csv"},
    "artifacts": {"result": "result.csv"},
    "graders": [{
      "id": "complete-bh-table",
      "type": "artifact",
      "artifact": "result",
      "verifier": {
        "kind": "de_table", "id_column": "gene", "p_column": "p",
        "q_column": "q", "effect_column": "effect", "min_rows": 3,
        "bh_tolerance": 0.000001,
        "testing_family": {"path": "family.json", "sha256": "REPLACE_WITH_ACTUAL_SHA256"}
      }
    }]
  }]
}
```

`family.json` 内容如 `{"ids":["A","B","C"]}`；摘要必须来自实际文件。`name` 必须精确匹配原生结果中的 case name；`repetitions` 必须与实际执行次数一致。`plugin_files` 明确列出本次想绑定的技能、代码和配置；工具另外保存首个插件清单中的名称、版本。未列出的依赖没有被冻结，报告会说明范围。

```sh
python scripts/value_lab.py prepare-native-evidence contract.json --plugin candidate --references scorers --output study
```

保存返回的 `plan_sha256` 到本次运行之外的记录。计划保留用例原始字节与规则摘要；此时没有模型调用。新增或修改用例、选定插件文件或参考材料后，须创建新计划。

## 2. 沿用原生执行

在已有原生命令上添加 `--keep-temp --no-publish`，明确指定模型和费用阈值。按原有用例保留工具、次数、对照臂、超时和工作区准备要求；不要为了补采集改变研究条件。文件写入需要原生 `--allow-tools Write`；脚本分析另需明确授予 shell，且 Windows shell 场景需要 WSL2。当前独立 `prepare-claude-collection` 仍限于只读审计，不能用它执行分析脚本。

官方说明：[执行选项、文件访问与保留工作目录](https://code.claude.com/docs/en/plugin-evals)。本地 CLI 帮助也需核对。PVL 不自动提高权限、执行 scaffold、启动真实 MCP 或发布报告。原生费用阈值是估算值，在途调用可能超出；真实账单未知时不填零。

**评分参考和 PVL 计划不能放入被测插件、工作目录或 `context.add_dirs`，也不能传给 Agent。** 路径分离只是必要条件，并非访问隔离证明。执行方须使用原生访问边界或独立受限账户/容器验证参考不可读取、不可改写。没有这种证据时，不宣称已建立盲法或防泄漏保证。

## 3. 绑定保留目录并收集

实测 Claude Code **2.1.278** 可直接沿原生 `tracePath` 与事件中的 `init.cwd` 生成映射，无需手填、也无需猜目录顺序：

```sh
python scripts/value_lab.py native-bindings aggregate-result.json --retained-root RETAINED_SANDBOX_ROOT --output bindings.json
```

这两个字段不属于官方 v1 汇总字段的稳定承诺，因此自动适配严格限于实测版本。其他版本使用下面的显式映射。使用自动映射时，后面的 `capture-native-evidence` 同时传入 `--retained-root RETAINED_SANDBOX_ROOT`；采集会再次检查 tracePath、cwd 与对应运行是否一致，拒绝串用日志。该映射来自宿主导出，不是独立认证的执行证明。

运行结束后，根据原生记录提供精确绑定；不按时间接近、目录排序或文件名猜测。`repetition` 是原生 arms 数组中从 1 开始的位置，不代表随机化配对。

```json
[
  {"case_id":"csv-analysis","arm":"with","repetition":1,"workspace":"/retained/run-with-1"},
  {"case_id":"csv-analysis","arm":"without","repetition":1,"workspace":"/retained/run-without-1"}
]
```

为全部已观察运行添加条目。缺失的目录可以不填，报告保留 UNKNOWN。若确实有原生 JSONL 事件导出，可在对应工作目录保存它并增加 `"events":"events.jsonl"`；使用 `--retained-root` 时 events 相对于该根目录，允许读取原生 out/ 下的 trace。不要合成不存在的日志。未知格式保留原始字节，不推测加载、调用、模型或会话信息。只有 init、没有 result 的失败日志仍保留实际观察到的加载与会话，但完成状态未知。

```sh
python scripts/value_lab.py capture-native-evidence study --plan-sha256 PLAN_DIGEST --plugin candidate --result aggregate-result.json --bindings bindings.json --references scorers --output collected
python scripts/value_lab.py verify-native-evidence collected --receipt-sha256 RETURNED_RECEIPT_DIGEST
```

打开 `collected/DIAGNOSIS.md`，逐项查看事实、缺口、产物与待检验修复解释。原生失败记录仍可得到局部文件诊断；没有文件则评分未知，不自动记成科学错误。收集只复制声明的输入、产物和事件，以及冻结的用例/选定插件文件/评分参考。**收集包包含评分参考，属于评分方材料，不能再交给被评估 Agent 或未经授权公开。**

每条记录绑定原生 JSON 指针、该条运行摘要及文件摘要。复制包到其他位置后可离线重算；外部保存的 receipt digest 用于检出整体篡改。摘要不认证文件是谁生成的，`comparison_eligible` 始终为 false；完整价值研究继续走原有冻结双臂研究合同。

## 修复与完整复测

只改候选插件，保留原用例、参考、阈值、次数与正常/错误对照；为新候选创建独立计划和采集包。不能只复跑曾失败的单个案例后宣称完整修复。记录诊断是否被实际采纳、误诊、投入时间、额外调用、负面反馈；未收到的信息用 null。

本次 NGS/BioNexus 的真实本地组件案例见 [P0 实施记录](P0-IMPLEMENTATION-20260924.zh-CN.md)。它与真实原生模型执行、完整 NGS 工作流和独立外部作者采用分别报告。

## 文件分析与修复复测入口

需要生成并执行分析脚本时，可用新增 `prepare-native-analysis` 准备官方原生用例。按需冻结 `execution_context`、`input_sha256` 与 `execution`，采集后用 `compare-native-repair` 对照两次完整复测；见[完整说明](NATIVE-ANALYSIS-REPAIR.zh-CN.md)。独立只读采集器的权限范围保持不变。
