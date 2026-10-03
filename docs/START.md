# Getting started / 从一项具体任务开始

**配对、冻结、可复算地判断插件对一项具体任务有没有增益。**

**Determine whether a plugin improves a specific task through paired comparisons, frozen plans, and recomputable results.**

## In chat / 在对话中开始

If PVL is installed and callable, give the plugin name, one real task and what success means. Use the [English request](../README.md#start-with-one-question) or [中文示例](../README.zh-CN.md#从一个问题开始). The host coordinates available tools; PVL checks the plan and computes from supplied records.

1. **Pair / 配对：** use the same task and authorized inputs, comparable model/budget conditions, and independent with/without records.
2. **Freeze / 冻结：** review the success criteria and sample-size assumptions before collection. Repeated runs do not replace independent tasks.
3. **Recompute / 可复算：** retain original outputs, apply frozen rules, and read the difference with its uncertainty and missing evidence.

没有可靠基线、独立记录或可比条件时，先交付方案或已有证据诊断，保留“尚不能证明增益”。工具可调用不代表宿主能自动组织独立两臂运行。

## Local tutorial / 本地复现

Use Python 3.11+ from the unpacked project root. Follow the identical five commands in the [English developer appendix](../README.md#developer-appendix-local-reproduction-and-file-reports) or [中文开发者补充](../README.zh-CN.md#开发者补充本地复现与文件报告). They process synthetic paired records without model calls.

1. Run `doctor`; `offline_engine_ready: true` is required. Optional host/dependency gaps do not block this tutorial.
2. Follow the remaining commands in order. Open `work/first-run/usage/USAGE.md`, `work/first-run/report/report.md` and `work/first-run/comparison.json`.
3. Expect `SIMULATION_ONLY`. Explain one failure or missing-evidence item before interpreting the example.
4. For another attempt, consistently replace `work/first-run` with a fresh directory and preserve prior attempts.

Windows、macOS、Linux 均可用标准库分析所提供记录。本教程无需 API key、模型账户、WSL 或隔离引擎；随包合成记录不是真实插件收益证据。对它们执行冻结只演示一致性，不声称事前预注册。

真实研究的费用、执行和隔离要求见[操作说明](OPERATIONS.md)。样本量与置信区间的方法见[方法学](METHODOLOGY.md#plan-task-counts-and-repetitions-before-collection)。其他能力统一从[高级指南](history/ADVANCED.md)进入。
