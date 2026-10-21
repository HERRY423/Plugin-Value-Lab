# 第一个外部实验室｜L1 试用包

**先做一次不调用模型的安装演练，再用实验室自己的 4 个任务做 L1。** 本包只负责冻结、导入与使用卡；不会自动安装被测插件、连接模型或启动付费任务。默认采用“已有机构内宿主执行，人工记录，PVL 导入”的路径，无须开发适配器。从 rc7 Release 下载 `PVL-first-lab-L1-v1.0.0-rc7.zip` 并解压；以 `PACKAGE-MANIFEST.json` 的提交与 wheel 哈希识别。源码目录是模板，完整安装包另附 wheel 和校验清单。

## 1. 最短安装与演练（Windows PowerShell）

前提：机构批准的 Python 3.11+，能运行 `python --version`；如果没有，交给本机构 IT 安装。把完整压缩包解压到机构批准的本地目录，打开该目录中的终端。以下步骤不联网、不激活环境、不修改系统 Python。

逐行执行；任一步报错就停在该步，保留报错，不继续后面的安装或演练命令。若 venv 报 ensurepip 不可用，请 IT 检查 Python 的 venv/pip 组件与本地临时目录写权限；不要因此改用系统环境或联网安装。

```powershell
python check_package.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps --find-links wheels plugin-value-lab==1.0.0rc7
.\.venv\Scripts\python.exe -I rehearsal.py --output rehearsal-01
```

预期：`REHEARSAL_PASS`；`rehearsal-01/complete/use-card.md` 为“停止”，表示合成记录没有达到增益阈值，**不是安装失败**；未知费用分支保留“证据不足”。此演练仅导入合成记录，无实际插件/模型运行，不计外部 L1。输出目录已存在时换名称，不删除旧记录重跑。macOS/Linux 对应命令是 `python3 -m venv .venv`、`.venv/bin/python`；本包此次仅实测 Windows。

## 2. 选定任务、完成数据与 L0 检查

先读 [数据治理说明](docs/DATA-GOVERNANCE.md) 和 [4 个任务模板](TASKS.md)，由实验室选定一种插件用途，换成自己的真实任务。保留一项正例、一项失败/拒答、一项边界，可用第 4 项补覆盖；共 3–5 项。每项两臂、每臂两次，默认 4 项共 16 次。不得将安装演练当作真实任务。

```powershell
Copy-Item templates work -Recurse
```

在 `work/plugins.json` 填插件 ID、确切版本、原包/内容 SHA-256；五项检查有真实依据才从 UNKNOWN 改为 pass，发现不适配填 fail。`evidence_ref` 指向机构内检查记录。填写 `work/tasks.json` 的 input、rubric、baseline；填 `work/study-setup.md` 的宿主/模型版本、快照/输入哈希、隔离方式、人员和批准记录。将共同设置与判据写进每项任务的 baseline/rubric，使其一同冻结。普通 PVL 文件只放经批准的最小任务材料，不能写入直接或编码的个体数据。

`work/settings.json` 默认每次 $0.10、总计 $1，实验室可在**冻结前**调整；费用单位为 USD micros。使用内网模型不代表费用自动为零。付费执行还须由实验室使用既有网关或提供方控制保证上限；导入命令本身不会拦截外部宿主的费用或网络。人工执行上限在 study-setup 中规定，`max_seconds` 仅适用于自动适配器，不是导入记录的耗时保证。

## 3. 冻结并生成空白配对表

```powershell
.\.venv\Scripts\pvl.exe screen --plugins work/plugins.json --tasks work/tasks.json --settings work/settings.json --output work/frozen-01
.\.venv\Scripts\python.exe -I make_record.py work/frozen-01/frozen-plan.json work/paired.json
```

此时“证据不足”是正常的：尚无运行记录。打开使用卡，**若仍列出 L0 缺字段或不适配，先停止执行**。修正后使用新的 frozen 目录和 paired 文件，旧文件保留。L0 齐备后才按 `schedule.json` 执行，冻结后不能改任务、模型、阈值或两臂设置。变更需要新版本记录，不用新目录重置同一研究的费用。

空白表也有 16 行；使用卡的“运行记录 16/16”是提交行数，不代表实际完成。以逐行执行状态、原始依据和验收清单核对完成情况，not_run 不能算一次尝试。

## 4. 在机构内完成两臂并记录

按生成顺序，在实验室已有宿主分别禁用/启用被测插件；保持模型、输入、其他工具与评分一致，每次使用隔离的新上下文。先确认该宿主允许插件控制且数据不会出机构；没有合适宿主或权限时停止，记录阻塞，不要求临时接云服务。

逐行填写 `work/paired.json`：`status` 为 completed 或 failed；分数遵守事前 rubric，失败不能删行、重试不能替换第一次。`evidence_ref/scoring_ref` 指向机构内原始输出、运行设置和评分记录。费用或分数不明填 null，不填 0；已核对的零 API 费填 0 并给 cost_ref。`correction_seconds` 是实际人工修正秒数。`critical_failure` 未核实填 null，有风险先停；核实为 true 时补 critical_verified_ref，立即停止后续执行。未尝试的行保留 not_run，不能填为 completed。保留所有额外重试、取消和其费用，在完成清单中单独说明。

## 5. 生成使用卡并验收

```powershell
.\.venv\Scripts\pvl.exe screen --plugins work/plugins.json --tasks work/tasks.json --frozen work/frozen-01/frozen-plan.json --results work/paired.json --output work/review-01
```

读取 `work/review-01/use-card.md` 和 result.json，逐项完成 [验收清单](ACCEPTANCE.md)。修正录入错误需保留旧文件和原因，再以新输出目录导入；不会重跑模型。“停止”不是命令失败；退出码 0 表示成功生成业务判定。输入错误则看终端提示。

## v1.0 正式版门槛与功能冻结

完整 L1 可得停止、证据不足或进入先导；不要求正向结果。未完成配对、安全早停、未取得外部实验室确认，均不能冒充完成。原始证据留机构；只有人工批准的完成证明、最小汇总和使用卡可对外。模型不代签，项目不自动发布。当前外部完成记录仍为 0/1；此包及本地演练不改变它。

卡住时在 `work/study-setup.md` 记录步骤、期望/实际行为、耗时及所需帮助；不要发送原始数据或整个 work 目录。当前阶段仅修复阻塞问题，不增加功能，也不要求联系外部供应商。
