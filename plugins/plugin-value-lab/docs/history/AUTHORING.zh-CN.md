# 目录化评估创建与迁移

> 后续修订：默认创建已转为当前宿主 Agent 的语义设计，见[研究人员对话式创建](RESEARCH-AUTHORING.zh-CN.md)。本文的旧模板需显式使用 `init --template`；目录格式、共享判据和迁移规则继续适用。

本次修订针对创建时需要手写嵌套配置、用例难审查和复用的问题。版本保持清单中的 0.7.0。

## 创建一个可审查的草稿

在 PVL 根目录执行，使用新输出目录：

```powershell
python scripts/value_lab.py init --plugin C:/path/to/plugin --interactive --output C:/path/to/new-study
```

向导询问任务、成功标准、不相关反例、缺证据用例、模型、宿主和环境。插件清单的名称、版本及 `skills/*/SKILL.md` 描述只作为输入数据；不会执行插件，也不会遵循文件中夹带的指令。多个清单的身份不一致会报错。

Agent 也可直接使用 `--goal "用户已确认的具体任务"` 非交互创建，再按实际插件能力审阅、细化生成的用例。这里的推荐是确定性草稿，不是已验证的插件能力或语义评估。默认 `human` 评分需要真实人工评审；可按输出类型改用精确 JSON 或已有产物校验器，文字匹配仅适合格式检查。

```text
new-study/
  suite.json                 # 仅指向 evals 的入口，没有第二份套件配置
  START.md                   # 下一步与证据边界
  authoring.json             # 识别依据、评分建议，DRAFT
  runs.jsonl                 # 空；没有模拟成实测的观测
  evals/
    suite.json               # 插件、条件、预算、阈值及顺序
    positive-task/
      prompt.md              # 用例元数据 + 实际提示
      graders/correctness.md # 评分元数据 + 人工 rubric
    negative-control/...
    missing-evidence/...
    graders/                 # 可选的共享评分规则
```

`init --format json --output ...` 保留单 JSON 编辑方式。`demo` 仍独立输出旧的教学套件和合成观测。初始化不创建锁，不运行模型，不安装或发布内容。

## 编辑、预检、冻结

```powershell
python scripts/value_lab.py suite-check C:/path/to/new-study
python scripts/value_lab.py freeze C:/path/to/new-study --lock C:/path/to/new-study/protocol.lock.json
python scripts/value_lab.py evaluate C:/path/to/new-study C:/path/to/new-study/runs.jsonl --lock C:/path/to/new-study/protocol.lock.json --output C:/path/to/new-report
```

创建完成后要填写实际插件身份、条件、资源限制、评估阈值及合法输入；草稿仍是 synthetic。`suite-check` 输出文件错误、套件摘要、用例清单和建议，不执行文件评分器；VALID 表示结构有效，不代表研究设计充分或已可得出增益结论。`freeze` 自动生成锁，无需手写。锁校验保持现有规则，不能覆盖旧锁。后续修改 prompt、评分器、共享规则或元数据都会改变展开后的套件摘要；旧观测不能冒充新协议的观测。

目录、项目入口 `suite.json` 都可用于 CLI 中接收套件路径的命令，包括冻结、评分、规则检查、评审包、原生导出和采集准备。注册与复用导出会保存完整展开 JSON 快照。核心对象 API 与 MCP 的套件参数仍接收字典，不新增宿主工具。Web 工作台不新增可视化目录编辑器。

## 文件格式与共享

frontmatter 只支持每行一个 `key: value`；值使用 JSON（包括行内对象、数组），或没有歧义的普通字符串。完整缩进 YAML、锚点、标签、隐式布尔值不受支持。解析不依赖 PyYAML，出错时报告路径与行号，不返回部分结果。

```markdown
---
id: positive-task
cluster: delivery
kind: task
grader_refs: ["graders/evidence.md"]
---
根据给定数据交付结果，并注明证据来源和限制。
```

共享文件 `evals/graders/evidence.md`：

```markdown
---
id: evidence
type: human
dimension: outcome
weight: 1
critical: true
---
检查每项结论是否有对应的输入证据；证据不足时保留未知，不补造结果。
```

可同时有 case 本地 `graders/*.md` 和 `grader_refs`。评分 ID 在每个用例内必须唯一。引用只能位于当前 evals 根目录的 `graders/` 下，不能越界或通过软链接跳出。共享规则直接展开为已有评分器，不会变成额外可执行代码。用例可以通过复制整个目录复用，修改 id 后需同步 `evals/suite.json` 的顺序列表。

导出的 `_case_order` 与 `_grader_order` 保留旧 JSON 的数组顺序，使迁移摘要一致。增删文件时同步这些顺序列表；也可同时移除两项，让目录按文件名确定顺序（顺序变化需要重新冻结）。case.yaml 若存在，仅接受 JSON 对象形式的额外用例元数据，不能覆盖 prompt 元数据。输入文件引用、标签、规则和评分器配置保留在展开套件中；迁移不复制外部数据或私有答案。

## 迁移现有配置

```powershell
python scripts/value_lab.py suite-convert C:/path/to/old-suite.json --format directory --output C:/path/to/fresh-evals
python scripts/value_lab.py suite-convert C:/path/to/fresh-evals --format json --output C:/path/to/compiled-suite.json
```

完整往返保留 prompt/rubric 的空白、中文、科学计数值、嵌套校验器和扩展用例字段。新输出不得覆盖旧文件。可比较命令输出中的 `suite_sha256`，并使用原锁进行一致性验证。PVL 的本地声明式格式与 Claude 原生 evals 不是同一执行契约；原生转换仍走 `export-claude` 并保留其已有拒绝条件与证据限制。

## 本次范围及验证边界

此次用户明确要求改进图中的创建和组织问题，因此只更新冻结接口清单中 init 的参数、suite-check / suite-convert 命令及 authoring / declarative 两个模块。冻结状态、五命令入口、MCP 签名、评分器种类和产品版本均不调整。测试覆盖创建、交互取消、迁移、共享规则、旧锁失效、坏配置、路径和冲突；这些是本地工程证据，不证明真实作者耗时下降、外部采用或插件增益。
