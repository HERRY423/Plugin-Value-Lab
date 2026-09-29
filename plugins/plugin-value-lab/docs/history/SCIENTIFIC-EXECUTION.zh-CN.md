# 可执行科学产物验证与盲评

2026-09-29 本机验收：853 项测试通过、无跳过；最终源码在真实 Linux/WSL2 离线沙箱执行了三次 PyDESeq2 拟合，验证正常重现、篡改结果不一致及程序失败。6 个合成供体、12 个样本、80 个基因，含连续剂量与分类批次协变量。PyDESeq2 改用均值离散度趋势及小残差自由度警告保留，不作为生物学验证。机器记录见[执行与评审证据](../evidence/scientific-execution-20260929.json)。

按用户指定，Grok Build 的 `grok-4.7`（回执为 `grok-4.7-build`）完成 8 个案例的匿名复核，标签为缺陷 5、合法 3；按这套标签，PVL 检出 5/5、误报 0/3，与作者同一子集一致。作者完整 22 例报告继续保留 null 的整体点估计。此次仅属外部模型复核；公开开发样本不证明未见过的真实事故泛化，更不计为人类专家盲标。原生 CLI 报告费用 $0.0673166，非独立结算凭证。远端 CI 尚未运行。

`detector-audit` 继续只做确定性产物核对，不隐式执行提交程序。需要验证重新生成时，显式运行 `scripts/science_execute.py`。MCP 录制回放仍然不新增计算。

## 重执行流程

1. 准备 Linux/WSL2、bubblewrap 和科学运行环境。可用 `/usr/bin/python3 scripts/prepare_science_runtime.py --output /tmp/pvl-runtime` 创建新环境；这一步需要联网安装依赖，失败不会换后台或自动重试。环境不得包含凭证、用户配置或参考答案。
2. `python scripts/science_execute.py freeze-runtime --runtime /tmp/pvl-runtime --package pydeseq2 --output /tmp/pvl-lock` 在离线沙箱内测量依赖文件、Python 身份、进程控制和 PVL 代码。锁记录在 `environment.lock.json`。
3. 在独立的 spec 目录写 `pvl-science-execution-1` manifest，冻结程序/输入文件字节、入口、参数、环境锁、提交产物及容差。用 `suite_digest(manifest)` 保存 manifest 的预期承诺。spec、inputs、submitted、output 目录与 runtime 分开，output 不得包含在其他输入目录里。
4. `python scripts/science_execute.py run /path/spec/manifest.json --expected-id <digest> --inputs /path/inputs --submitted /path/submitted --runtime /tmp/pvl-runtime --output /path/new-run`。输出目录必须不存在。

manifest 的精确字段：

```json
{
  "format": "pvl-science-execution-1",
  "files": {"pipeline.py": "<file sha256>", "data.json": "<file sha256>"},
  "entrypoint": "pipeline.py",
  "arguments": [],
  "environment": {"path": "environment.lock.json", "sha256": "<file sha256>"},
  "timeout_seconds": 300,
  "memory_mb": 4096,
  "outputs": [{
    "path": "result.json",
    "submitted": {"path": "result.json", "sha256": "<file sha256>"},
    "comparison": "json",
    "absolute": 0.0000001,
    "relative": 0.000001
  }]
}
```

程序使用 `/inputs` 读锁定输入，向 `/output` 写新结果。Python 以 `-I` 启动；如果需要提交的其他模块，程序须显式加入 `/inputs`。代码和数据一起列入 `files`，不会自动暴露整个项目。提交结果和比较器留在控制进程一侧，不挂载给程序。程序和控制器互不共享环境检查输出目录；测量过程也不会导入提交的程序。

已有离线沙箱提供网络、进程和挂载命名空间、只读输入、独立输出、进程树清理及资源限制。运行环境只读挂载在 `/runtime`；系统库使用现有 `/usr` 等只读挂载。环境和输入不匹配时不执行提交程序，无非沙箱后备路径。上下文中的宿主/系统运行库属于受信边界，锁尚未覆盖全部系统库和硬件。

比较方式为 `json`、`pseudobulk`（按基因/样本身份规范排序）或 `bytes`。JSON 核对完整结构，整数精确比较，浮点按声明的绝对/相对容差比较；NaN、Infinity 和布尔数值替代不能通过。容差上限为 `1e-4`。输入最多 32 MiB，运行最多 300 秒、4096 MiB。更大的真实研究需另行明确扩展契约，不截断为通过。

结果分开报告：

| 状态 | 含义 |
|---|---|
| `REPRODUCED` | 新运行完成，环境前后相符，所有声明输出一致 |
| `RESULT_MISMATCH` | 新运行完成，但至少一个产物与提交结果不符 |
| `EXECUTION_FAILED` | 程序失败或超时，比较结果未知 |
| `UNRESOLVED` / `BLOCKED` | 环境、输入、产物读取或隔离前提不成立 |

`REPRODUCED` 只说明这份程序在当前测量环境能重新生成声明输出。程序可能把答案硬编码；相同代码也可能重复同一科学错误。此结果不自动证明方法正确、环境可在另一台机器重建、独立复现或生物学有效。

## 第一项任务族扩展：供体配对 pseudobulk DE 加协变量

`pvl-pseudobulk-design-2` 在现有供体配对任务上增加 `covariates`：连续型为 `{"kind":"continuous"}`；分类型为 `{"kind":"categorical","levels":["reference","other"]}`。输入增加 `sample_covariates`，以样本 ID 为键且必须覆盖所有样本。细胞仍按声明供体和条件聚合原始整数 counts。

检查包括协变量缺失/非有限值、样本关联、未观察到的分类水平、供体/条件混杂、设计矩阵秩不足和无残差自由度。矩阵检查使用归一化列和重正交化，阈值 `1e-10`；近混杂保守拒绝。拟合前核对 PyDESeq2 实际矩阵，产物检查重新构建设计矩阵。数值秩不等于协变量选择合理或因果效应可识别。

公式固定为 `~ donor + <covariates> + condition`，目前只支持加性项、完整配对，最多 256 个样本。不自动删协变量、删样本或更改对比。年龄等供体内恒定变量与供体固定效应重合时会阻断；不得为了跑通而静默移除。非配对设计、交互、混合模型、批次整合和空间统计仍未覆盖。

后端沿用 [PyDESeq2 的公式设计接口](https://pydeseq2.readthedocs.io/en/stable/api/docstrings/pydeseq2.dds.DeseqDataSet.html)，固定 PyDESeq2 0.5.4；不重新实现差异表达模型。

## 独立参考工作流

`scripts/blind_review.py prepare` 接受 corpus、显式 selection（`case_id/task/materials`）和独立输出目录。每个 material 为中性 `name` 与 `{path,sha256}` 引用。导出随机案例 ID、洗牌后的产物和任务输入；作者标签、案例名称、检测器判定和内部映射留在 `controller.private.json`。只交付 `reviewer` 子目录。编写 task 时须人工检查是否泄露答案。

`scripts/blind_review.py score` 要求 packet/controller 承诺和逐例标签，保留 unknown/disputed；缺失、重复和错包标签不能被当作完成。输出分别包含作者完整 corpus、作者相同子集和评审者相同子集的计分及分歧。unknown 检测器结果保留在分母并将点估计设为 null，附缺失结果上下界；没有真实总体抽样，不能解释为总体检出率。

评审身份分为 `human` 和 `model`。模型复核永远记为 `EXTERNAL_MODEL_REVIEW`。人工身份、专业资质、无冲突和盲法声明不靠 SHA-256 自动认证；公开开发样本也不因匿名而成为未见过的真实事故。非作者领域专家和真实外部环境重建继续单独待验证。

## 必须运行的验收

`/usr/bin/python3 scripts/check_science_execution.py --runtime /tmp/pvl-runtime --output /tmp/new-acceptance` 会在真实离线沙箱拟合合成 pseudobulk（供体 + 连续协变量 + 分类批次 + 条件），重算并比较，再验证篡改提交结果与程序失败。环境或后端缺失直接失败，不跳过、不用 mock 替代。单元测试只能证明状态机和边界行为，不能替代此验收。
