# Plugin Value Lab

评估插件，保留负向证据，再决定哪些任务值得试用。**0.7.0 · 接口范围冻结至 2026-11-06。**

创建评估时，直接请当前 Agent 理解插件并推荐研究任务、可用结果与证据边界。默认 `init` 提供 Agent 阅读的来源包；Agent 设计方案后，`init --proposal ... --materials ...` 自动装配并校准检查规则。研究人员审阅中文方案，不必填 verifier JSON。单独终端不会启动 LLM；手工模板需显式 `--template`。参见[研究人员对话式创建](docs/history/RESEARCH-AUTHORING.zh-CN.md)。版本仍为 0.7.0，下方五命令入门路径不变。

Python 3.11+，在解压目录运行。下面五条命令使用随包的**合成记录**，无需安装插件、注册账户或调用模型。每次尝试使用新的输出目录。

在线原生采集改用断网子进程与父进程模型网关，旧宿主根遮蔽计划不再执行；新增的原生 Windows Hyper-V 后端仍需实际运行环境验收。见[在线隔离边界与配置](docs/history/ONLINE-ISOLATION.zh-CN.md)。

科学结果现在可自动保存环境锁并在无科学库环境中回放；真实 MCP 工具会话可直接生成 cassette。见[环境漂移检查与自动录制](docs/history/ENVIRONMENT-RECORDING.zh-CN.md)。回放不等于重新拟合。

新增标准 `metamorphic` 科学 Grader：检查矩阵重排、尺度变化、聚类分区和对比反转关系，保留缺失运行与具体反例。见[科学蜕变评测器](docs/history/METAMORPHIC-GRADERS.zh-CN.md)。关系一致性需要与任务正确性证据配合。

支持生成 4/8 臂组件消融计划、重新评分的跨模型饱和度诊断，以及带逐项偏差约束的 `equivalence` 配对 TOST Grader。见[组件评测方法与操作](docs/history/COMPONENT-METHODOLOGY.zh-CN.md)。配置声明和统计一致性不自动升级为因果收益或科学有效性。

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

打开 **work/first-run/usage/USAGE.md**；同目录 `ENVELOPE.html` 是单页卡。最后一条比较随包的两份教学记录，不是新修复实验。出现“模拟”或“证据不足”是诚实结论，不是安装失败。

[English](README.md) · [开始与首次使用计时](docs/START.md) · [实际操作](docs/OPERATIONS.md) · [证据边界](docs/EVIDENCE.md) · [六周冻结](docs/FREEZE.md)

**尚未建立完整自然使用修复闭环，也没有非作者首次使用计时。** 教学记录与种子审计不证明实际收益。原有专用命令仍可调用，首次使用无需接触。
