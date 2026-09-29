# 工程易用性：从文件到可审阅结果

本次增加便捷入口，版本保持 0.7.0。只改工程操作，不把试跑变成非作者采用或科学验证。源码安装后可使用 `pvl`；未安装时在源码根目录使用 `python -m value_lab`。不要假定公共仓库中同版本包已包含本次修改。

## 一分钟内可尝试的入口（不是已测人工耗时）

```sh
python -m value_lab demo --output work/demo
```

打开 `work/demo/REPORT.md`。演示仅用标准库、合成 BH 表，不需要账户、模型、MCP 或科学库。重复演示使用新目录。

从当前源码安装计数处理依赖：

```sh
python -m pip install ".[science]"
pvl doctor
pvl inspect counts.h5ad
pvl aggregate counts.h5ad --cell-type "B cells" --control ctrl --treatment stim --output work/counts
pvl verify work/counts
```

`doctor` 只检查模块是否可发现，不证明运行时兼容；`inspect` 只读头部，不证明原始计数或供者设计有效。默认 `layers/counts`；只有 X 确实是原始计数时才传 `--matrix X`。默认列为 sample、donor、condition、cell_type，可通过对应 `--*-key` 映射。研究者必须指定细胞类型和对比方向；不自动猜测分组、归一化、取整或改名。

聚合要求至少三对供者。默认每样本至少 10 个细胞、全样本基因总计数至少 10。默认严格检查输入范围；混合细胞类型输入需要明确 `--select-design`，报告保留纳入和排除细胞数。此便捷入口覆盖配对计数聚合，不拟合差异表达；协变量设计、科学执行沙箱与其他数据类型仍走各自专用接口。

## Python 与工作流

```python
from value_lab.sdk import aggregate_counts, verify_run, PVLError

try:
    result = aggregate_counts(
        "counts.h5ad", output="work/counts", cell_type="B cells",
        control="ctrl", treatment="stim", reuse=True,
    )
    print(result.report)     # 可读报告
    print(result.counts)     # aggregation/counts.h5ad
    verify_run(result.directory, expected_id=result.commitment)
except PVLError as exc:
    print(exc.code, exc.hint)
```

API 不启动宿主或联网。配置、流式来源摘要、代码身份与报告自动保存。已有完成结果只有输入、设置、代码身份和结果文件均一致才可复用。`reuse=True` / `--reuse` 是完成结果复用，不是中断后的断点续算。更改输入路径也要求新目录；已完成结果可整体搬迁并独立校验。

参见[可运行模板](../../examples/workflow-integration/README.md)：同一 settings.json 可用于 CLI、Nextflow、Snakemake 和 Jupyter，模板附有独立可计算的合成输入及预期输出。工作流引擎有自己的缓存和目录清理规则，详见模板说明；引擎缓存命中不替代 `verify`。实际引擎验收状态见[本次证据](../evidence/engineering-usability-20260929.json)。

## 机器调用与恢复

```sh
pvl aggregate counts.h5ad --config settings.json --output work/counts --dry-run --json
pvl aggregate counts.h5ad --config settings.json --output work/counts --disk-budget 4GiB --json
pvl check differential-expression.csv --rule bh --output work/bh-check --json
```

配置文件使用 SDK 参数名；未知键报错，命令行显式参数覆盖配置。`--dry-run` 只检查头部和参数，不写文件，不校验完整计数、供者分组或磁盘峰值。聚合采用磁盘后端，默认分块 262144 个元素、元数据预算 128 MiB、磁盘预算 4 GiB、空闲保留 256 MiB；按实际资源显式调整。处理大文件会多次顺序读取以建立和核验来源身份，不能把耗时解释为挂起。

`--json` 将单个 JSON 对象输出到标准输出，阶段进度到标准错误。BH 检查要求 gene,p_value,q_value,log2fc 列，表格输入上限 64 MiB；该边界与 h5ad 的磁盘处理路径不同。必须显式指定 BH；检查只说明声明规则的一致性。

| 退出码 | 含义 |
| --- | --- |
| 0 | 操作完成、检查通过或预检完成；按 status 区分 |
| 2 | 参数、输入、依赖或运行环境错误；读取 code/message/hint |
| 3 | 检查明确失败 |
| 4 | 证据不足 UNKNOWN |
| 130 | 用户中断 |

已有目录不覆盖。运行中写 RUNNING，受控失败保留 failure.json 与 FAILED；完成后才写 COMPLETED。中断或进程崩溃可留下 RUNNING，必须视为未完成，检查后在新目录重试。预检阶段错误尚无结果目录，会直接返回修复提示。结果校验检查文件字节，不重跑分析；本地标记不提供身份认证，需要防篡改锚定时在独立位置保存 commitment。

真实非作者首次使用、理解时间、求助次数和自然使用收益仍未测量；继续按 [START](../START.md) 收集真实回执。安装测试、合成数据、机器执行耗时均不代替这些证据。

## 本轮实际验证

在源码目录之外安装构建的 wheel：标准库环境完成演示与校验，科学环境完成精确计数、结果复用，以及真实 Jupyter 内核的四个代码单元。科学依赖沿用本机已有安装，不宣称从空白机器重新解析了全部依赖。

Linux/WSL 上实际执行 Snakemake 9.27.0 和 Nextflow 25.10.4，并重复运行；两者输出均为预期的 6 × 2 矩阵，每行 `[78, 36]`，重复运行保持同一结果摘要。引擎测试发现 AnnData 0.13.4 / Pandas 3.0.6 的可空字符串索引兼容问题，已修复；缺失标识与异常掩码仍拒绝处理。

缓存 GSE96583 派生文件经新入口聚合，与原路径的 16 × 7,877 矩阵及两个坐标轴完全一致；未重新认证原始公开数据，也没有重拟合或独立科学验证。本机低磁盘空间触发了预期拒绝，失败保留后以明确的小文件预算重试，不将资源失败隐藏成成功。

安装、Notebook 和原生引擎验收脚本已接入 CI 配置；本地通过与尚未运行的托管 CI 分开记录。具体字节身份、测试数及失败尝试见[验收记录](../evidence/engineering-usability-20260929.json)。

最终本地完整回归为 **914 项通过、零失败、零跳过**。构建 wheel 的全部运行时源码字节与验收时工作区一致。新 CLI 处理 50,000 × 20,000 合成矩阵，输出 200 × 20,000，与之前独立计数校验过的结果逐元素、逐坐标轴相同；本机约 6.9 秒，进程树 RSS 每 20 ms 采样峰值约 89 MiB，共享页面可能重复计入。该数字是指定输入和机器上的观测，不是通用性能保证，也不是人工首次使用耗时。

完整回归发现测试后，同一工作区另有并行改动新增测试；保留这些修改，随后单独复验 native 14 项、research execution 10 项，均通过且无跳过。目前可发现 928 项，但不把两批运行合写成一次 928 项完整运行。运行时字节再次比对无漂移。
