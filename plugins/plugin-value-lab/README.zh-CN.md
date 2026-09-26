# Plugin Value Lab

评估插件，保留负向证据，再决定哪些任务值得试用。**0.6.0 · 新功能冻结至 2026-11-06。**

Python 3.11+，在解压目录运行。下面五条命令使用随包的**合成记录**，无需安装插件、注册账户或调用模型。每次尝试使用新的输出目录。

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
