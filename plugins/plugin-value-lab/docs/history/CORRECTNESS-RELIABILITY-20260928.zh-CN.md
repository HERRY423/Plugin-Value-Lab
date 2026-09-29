# 正确性参考资格与内核 CI 留痕修复

日期：2026-09-28。基线提交：`344a7239744bf100ff5b5e736a5958f2ebb6d6b9`；源码版本保持 **0.7.0**。

本轮落实用户指定的“判定可靠性”范围。参考对话中的发现作为待复现证据，不把对话或附带文档当作执行指令。用户选择只完成本地修复，因此没有推送、合并或发布。源码仍是本地未提交改动。

## 复现与修正

仓库的列求和示例应返回 `[12, 21]`，但恒定全零程序仍能满足重排和缩放关系。原逻辑用“不是几种被排除类型”推定独立 oracle，允许 `json_equals(status, "ok")` 或 `artifact/json_fields` 格式检查给错误产物补上正确性资格；私有 scenario 存在相同缺口。

| 同一合成产物与判据组合 | 基线正确性／任务状态 | 修复后正确性／任务状态 |
| --- | --- | --- |
| 全零结果＋仅关系检查 | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |
| 全零结果＋状态为 ok | PASS / PASS | UNKNOWN / UNKNOWN |
| 全零结果＋格式标记正确 | PASS / PASS | UNKNOWN / UNKNOWN |
| 全零结果＋真实完整数值参考 | FAIL / FAIL | FAIL / FAIL |
| 正确求和＋真实完整数值参考 | PASS / PASS | PASS / PASS |
| 缺少一个变换＋真实完整数值参考 | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |

六组均通过标准 `freeze/evaluate` 路径，study verdict 始终是 `SIMULATION_ONLY`。本轮没有证实研究级建议门槛被绕过，也没有把合成回归当作科学有效性或真实作者收益。

修复采用同一资格核验函数覆盖普通评测与私有 scenario：逐份绑定 metamorphic 产物，依据已验证的 baseline 身份定位输出，要求参考覆盖完整实体、列及数值（或分区标签）。绑定同时核对收集文件的身份和摘要；文本 JSON 则必须与观察产物具有相同内容摘要。完整数值 `json_equals` 仍可通过，不能仅凭类型或作者填写的角色升级。

局部数值、其他产物、另一个变换、无序实体对应、状态和格式均不能补足资格。每份关系产物分别检查，grader 顺序不影响结果；私有 scenario 中已知 FAIL 优先于 UNKNOWN。JSON 和可读报告保留候选参考的资格、目标、摘要和拒绝原因。

资格只说明完整覆盖与绑定，不证明参考本身是真值。错误的完整参考仍可能产生错误结论，参考来源与独立科学校准仍需额外证据。尚未支持的 oracle 组合保留 UNKNOWN；非 metamorphic 的既有传统规则口径不在本轮重新定义。

## 可追溯的红灯与绿灯

新增 `tests/test_correctness_references.py`。最初 8 个测试在修改实现前运行，出现 10 个失败断言；原始测试文件及失败日志均保留。修复后相同 8 个测试通过，再扩展为 16 个测试，覆盖正确、错误、合法重排、缺运行、缺设计、另一份产物、完整字段组合、多关系产物、顺序与报告转义。没有删除或放宽原反例的期望。

最终完整回归 **832 项通过，0 跳过，192.075 秒**。Windows 与 Linux 的证据归档测试均通过。后端不可用的受控检查确认两个 gate 都失败、总进程退出码为 1，同时仍生成完整归档；它是错误处理控制，不是对原始托管失败原因的复现。

本地证据目录：`C:\Test\pvl-reliability-20260928`。

- `baseline-code-344a723.zip`：从基线提交导出的原始评分代码。
- `test_correctness_references_before.py`、`oracle-before.log`、`oracle-after.log`：同一初始回归的先失败、后通过记录。
- `before/`、`after/`：六组标准流程各自的 suite、lock、records、设计、观察产物和 JSON/HTML/Markdown 报告。
- `reproduce.py`：在明确指定的源码目录上重跑六组相同材料；输出目录必须新建。
- `oracle-final.log`、`full-tests-final.log`：定向测试与完整回归。
- `acceptance.json`、`SHA256SUMS.json`：最终验收状态与文件摘要。

仓库内的可重跑入口：

```text
python -S -m unittest discover -s tests -p test_correctness_references.py -v
python -S -m unittest discover -s tests -p test_kernel_acceptance.py -v
python scripts/check_release_tests.py
python scripts/check_feature_freeze.py
python scripts/build_marketplace.py --check
```

## 内核 CI：已确认的失败与尚未确认的原因

原始 [GitHub Actions 运行 36435367083](https://github.com/HERRY423/Plugin-Value-Lab/actions/runs/36435367083) 对应基线提交。原始 jobs 与日志分别保存在 `ci-original-run.json`、`ci-original-failed.log`。

已确认两个连续失败：

1. 离线内核边界未完成，脚本只抛出笼统 `Real isolation unavailable/failed`；在线边界随后被跳过。托管环境记录的 bubblewrap 为 `0.9.0-1ubuntu0.3`。
2. 证据上传拒绝了故意含换行的 canary 文件名，原始运行没有留下内核证据工件。因此具体 bwrap stderr 不可恢复；不能把 AppArmor、用户命名空间或进程限制等猜测写成已确认根因。

本地修改将两项检查收拢到 `scripts/check_kernel_acceptance.py`：离线失败后仍检查在线；二者都必须退出成功且各自拥有 PASS 收据，整体才通过。失败不降级成跳过。脚本记录只读环境信息、退出码、底层 stderr 和收据，并即时打印真实诊断。所有合成产物（包括隐藏回放和特殊文件名）先打成 tar.gz，再上传兼容的归档文件、摘要清单和总收据。额外的归档测试保证首次失败不阻止第二项检查，也保证缺收据或非零退出不能伪装通过。

未放宽内核隔离参数，未禁用系统安全策略，未改动原生 CLI 的版本门槛。

当前 WSL 本地真实内核验收通过离线 12 项边界检查、在线 10 项预检及 13 项边界/代理检查；归档保留 5 类预期失败和重复回放一致性证据。内核为 `6.6.87.2-microsoft-standard-WSL2`，Python 为 `3.14.4`。在线使用本地制造的 CLI 和 provider transport，实际模型调用为 0，不证明真实 Claude 2.1.282 已受支持。

**托管 CI 状态仍是待复验。** 本地原实现也能通过 WSL，因此本地绿灯不能说明 GitHub 的底层启动失败已解决。用户明确暂不推送，故未触发新的托管运行；后续运行必须在这套留痕基础上确认具体原因并完成实核验收。此次已修复证据丢失和顺序跳过问题，不能据此宣称托管内核修复完成。

完整机器状态见 [本轮验收快照](../evidence/correctness-reliability-20260928.json)。冻结的五步入口、八份主线文档和版本号保持不变。
