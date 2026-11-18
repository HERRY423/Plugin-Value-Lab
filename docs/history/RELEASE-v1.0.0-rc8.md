# Plugin Value Lab v1.0.0-rc8

本候选版修复 L1 筛查边界和报告来源标记，并更新外部实验室试用材料。插件版本为 `1.0.0-rc8`，Python 包版本为 `1.0.0rc8`。

## 本次变化

- `pvl screen` 按分数的十进制值计算配对差和均值。增益恰好等于冻结下限时满足质量条件，单任务退步恰好等于上限时仍在范围内。
- 冻结方案支持可选的 `evidence_type`。独立流转的结果、运行记录与使用卡同时保留声明的证据类型和本次取得记录的途径。旧方案的摘要可以继续用于导入，未声明的来源显示为 `unknown`。
- 首个外部实验室试用包增加了工时、作者支持、失败及未尝试项的记录方式。仓库另附评审者配对盲评方案，用于比较常规专家复核与加入 PVL 后的判断质量、工时及成本。

## 附件

- 首次 L1 试用用 `PVL-first-lab-L1-v1.0.0-rc8.zip`。
- Codex 或 Claude 本地市场用 `plugin-value-lab-marketplace-1.0.0-rc8.zip`，通用插件用 `plugin-value-lab-agent-plugins-1.0.0-rc8.zip`。
- Python CLI 和库用 `plugin_value_lab-1.0.0rc8-py3-none-any.whl`，源码分发为 `plugin_value_lab-1.0.0rc8.tar.gz`。
- 附件校验值在 `SHA256SUMS.txt`，工程验证记录在 `release-verification.json`。

正式版的外部实验室 L1 验收进度仍为 **0/1**。随包演练使用合成记录，评审者配对盲评尚待真实试验。

## English

This prerelease makes L1 threshold decisions consistent at exact decimal boundaries and carries evidence type and record source into standalone results and usage cards. It updates the offline first-lab kit and adds a paired reviewer study protocol. Verified external L1 completion remains **0/1**. The included rehearsal uses synthetic records, and the reviewer study awaits real data and participants.
