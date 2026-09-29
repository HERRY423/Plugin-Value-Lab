# 真实数据规模：磁盘计数与文件引用契约

原来的 `groups × genes <= 2,000,000` 是 **pseudobulk 样本 × 基因** 的内存 JSON 适配器限制，不是细胞 × 基因限制。旧入口仍保留资源保护；较大研究使用下面的磁盘入口。没有通过取消校验或提高 JSON 上限来假装支持大数据。

## 数据通路

`原始 counts h5ad → 有界读取 CSR/CSC/稠密块 → 磁盘样本聚合 → counts.h5ad + metadata.json + receipt.json`

- 输入可以是 `X` 或明确指定的 `layers/counts`。不猜测哪个矩阵是原始计数，不把标准化值、负数、NaN 或小数当作计数。允许浮点存储的精确整数原始计数。
- 支持标准 AnnData CSR、CSC 和稠密二维矩阵；稀疏索引必须有序且无重复。明确拒绝未支持的编码、HDF5 外部/软链接、虚拟数据集和外部原始存储，不偷偷转换或跟随外部文件。
- 计数工作数组随 `block_entries` 和单条基因向量变化；细胞身份去重索引及细胞到样本映射位于磁盘。基因/样本元数据另有 `metadata_mb` 预算，不将所有细胞元数据或所有计数读入内存。
- 原始单项计数上限为 int32 正范围，聚合用 int64 并检查溢出；过滤总数使用饱和求和，避免跨样本相加溢出。
- 保留唯一细胞/基因标识、样本身份一致性、至少三对完整供体、最小细胞数和零文库检查。技术重复不能被当成独立供体。
- 默认 `selection: strict` 拒绝不属于设计的细胞。研究者可在冻结计划中选择 `design`，只聚合设计声明的 cell type 和两种 condition；回执记录选入/排除数量，仍检查整个输入矩阵的计数合法性。
- 中断或错误留下 `FAILED`/`STARTED` 回执和局部工作文件；只有完整验证及末尾源文件哈希复核后才发布 `counts.h5ad` 和 `COMPLETE`。目前不自动重试、不从局部文件断点恢复；新尝试使用新目录。

输出是 AnnData 可直接以 `backed='r'` 打开的普通 h5ad。`metadata.json` 包含样本身份、细胞数、保留与排除基因，不包含计数矩阵。回执绑定源文件、设计、选择规则、协变量和输出 SHA-256。

## 冻结计划并运行

安装项目的 `science` 可选依赖。输入目录只放显式选择的本地数据和设计，计划使用相对 POSIX 路径：

```json
{
  "format": "pvl-backed-counts-plan-1",
  "design": {"path": "design.json", "sha256": "替换为设计文件SHA256"},
  "data": {"path": "counts.h5ad", "sha256": "替换为h5ad文件SHA256"},
  "matrix": "layers/counts",
  "obs_columns": {"sample": "sample_id", "donor": "donor_id", "condition": "condition", "cell_type": "cell_type"},
  "selection": "design",
  "sample_covariates": null,
  "block_entries": 262144,
  "metadata_mb": 128,
  "max_disk_bytes": 4294967296,
  "reserve_bytes": 536870912
}
```

设计沿用 `pvl-pseudobulk-design-1/2`；v2 协变量按样本精确连接，保留现有设计秩/混杂检查及 256 样本的设计审计边界。`suite_digest(load_json(plan_path))` 是计划承诺，不是文件原始字节哈希。更改矩阵、筛选规则、预算或设计必须重新冻结，不能沿用旧承诺。

```text
python scripts/science_scale.py plan.json --expected-id <计划承诺> --inputs <输入目录> --output <新的结果目录>
```

数据留在本地；命令只向标准输出打印小回执。`max_disk_bytes` 限制本次工作目录；还会预检工作矩阵、最终矩阵和磁盘保留空间。超预算明确失败，不截断数据、不输出部分通过。直接 Python 聚合入口是受信任的本地解析操作；处理不受信任程序请使用下一节 OS 隔离执行。

## 通用大文件重执行

`scripts/science_execute.py run` 同时支持原有 v1 和新的 `pvl-science-execution-2`。v2 在现有清单上增加必填 `resources`：

```json
{"input_bytes": 21474836480, "output_bytes": 10737418240,
 "file_bytes": 10737418240, "reserve_bytes": 2147483648}
```

这些是本次研究的显式字节预算，不是预分配容量，也不是证明已经验证了 20 GiB。`file_bytes <= output_bytes`，字节预算的契约上限为 16 TiB；v2 超时上限为 7 天，进程地址空间上限为 1 TiB。实际可运行规模仍受机器、磁盘、方法和验证记录限制。

输入及提交答案都按块校验/复制，不进入 Python bytes 字典。预检计入双份输入暂存、答案留存、输出预算和保留空间；不使用硬链接或直接挂载可变原文件。冻结的环境、文件哈希和隔离方式仍需匹配。大 FASTQ/BAM/VCF 可作为不透明文件运输并做字节重生成核对；这不提供比对、变异检测或这些格式的科学语义验证。相应流程需要自行声明并固定专业工具及参考资源。

比较方式：

- `bytes`：流式全文件 SHA-256 精确比较，能检测末字节变化。
- `h5ad_counts`：对本入口生成的 `X/obs/var` 计数产物分块精确比较。样本/基因顺序与完整元数据必须一致，容差必须为零；拒绝额外顶层字段。它不是任意 h5ad、embedding、标准化值的通用比较器。
- `json` / `pseudobulk`：仍只接受最多 32 MiB 的小型结构化结果，避免将大矩阵重新灌入 JSON。

隔离执行依旧要求 Linux/WSL2 + bubblewrap，拒绝无隔离回退。v2 在实际进程中执行单文件大小、地址空间、CPU 和墙钟限制，并每 250 ms 检查输出总大小、条目数和磁盘余量。**轮询不是文件系统硬配额**，并发写入可能在停止前暂时超过总预算；高对抗性或严格多租户部署还需要 cgroup/文件系统配额。stdout/stderr 也受单文件限制。预算不足、环境漂移和执行失败不会变成 `REPRODUCED`。

## 差异表达拟合

`value_lab.pseudobulk_backed.fit_backed_reference(design, directory, expected_receipt_id, max_fit_bytes=...)` 将磁盘聚合结果接入与旧入口相同的版本固定 PyDESeq2 方法。返回 `pvl-backed-pseudobulk-result-1`，JSON 中仅保存计数文件与聚合回执引用，数值结果仍保留效应、标准误、区间、p/q 值、方法和设计矩阵。

PyDESeq2 拟合本身需要内存。适配器只加载缩小后的样本矩阵，以 `40 × dense_int64_bytes + 256 MiB` 做保守事前估算并拒绝超出 `max_fit_bytes` 的任务；这不是实际峰值的保证。需要硬约束时，将调用放进 v2 OS 执行清单并设置 `memory_mb`。聚合能完成不代表任意规模的模型一定能拟合，也不会自动换统计方法。均值趋势等后端行为保留在 `observed_dispersion_trend`，不伪装成请求的参数趋势。

## 验收入口与证据边界

- `scripts/check_data_scale.py --output <新目录>`：50,000 × 20,000、1,000 万非零计数、200 × 20,000 聚合结果；独立闭式算术答案逐项核对，独立子进程测量内存。`--cells 100200` 还跨过旧 100,000 细胞限制。测试工具额外需要 psutil。
- `scripts/check_data_scale_execution.py`：在真实 Linux 沙箱中重新聚合上述冻结数据，并通过 v2 环境检查和 h5ad 比较；沙箱不可用即失败。
- `scripts/check_backed_research.py --source <缓存计数包> --output <新目录> --fit`：缓存真实数据衍生物的全矩阵核对与两次真实后端拟合对照；不重新认证原始来源，不证明生物学结论或独立正确性。

机器结果见 [规模验收记录](../evidence/data-scale-20260929.json)。GB/TB 的契约容量、合成规模测量、真实来源数据衍生物、隔离执行、科学正确性和独立专家验证是不同证据层级。

本次按用户明确提出的数据规模修复要求，冻结清单仅追加 `science_storage` 和 `pseudobulk_backed` 两个模块；没有重采样整个接口清单，没有变更五步主入口、MCP 工具或版本号。
