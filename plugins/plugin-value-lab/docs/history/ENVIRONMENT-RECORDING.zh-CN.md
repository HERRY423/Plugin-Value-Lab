# 科学环境锁与真实 MCP 自动录制（0.7.0）

用户在 2026-09-28 明确要求修复科学环境漂移与手工 transcript 录制问题。本次是限定范围的冻结例外，不改变版本、评分门槛或五步主流程。

## 先确定要复现什么

| 目的 | 路径 | 是否运行科学计算 | 环境要求 |
| --- | --- | --- | --- |
| 测试 Agent 如何使用外部工具 | MCP cassette 回放 | 否，返回已录制响应 | 标准库 Python |
| 测试报告、验证器如何处理科学结果 | 科学 artifact 回放 | 否，恢复已记录文件 | 标准库 Python |
| 重新拟合 PyDESeq2 | `pseudobulk-reference` 加环境锁 | 是 | 匹配锁定环境，仍需真实科学依赖 |

快照不拦截任意 Python `import`，也不消除重新拟合的依赖。第三方 Agent 在自身进程中直接计算时，必须由其集成显式的计算边界；本次自动集成覆盖 PVL 的 PyDESeq2 reference 路径。不能把 MCP 回放成功写成科学模型重新运行成功。

## 研究人员：一次计算，后续回归不装科学库

原来的 `pseudobulk-reference` 命令会自动增加：

- `environment.lock.json`：Python 可执行文件、平台、线程/哈希种子环境变量、PVL 源码、PyDESeq2 活跃传递依赖及其实际安装文件摘要。环境标记按当前平台求值，测试/文档 extras 不被误带入。
- 运行前捕获和运行后再核验；安装文件被修改即使版本号没变，也拒绝完成。
- `artifact-manifest.json`：绑定输入、设计、完整结果、验证器、执行记录和环境锁。命令输出 `artifact_sha256` 与 `environment_sha256`。

锁定操作需要环境中已有 `packaging`（PyDESeq2 科学栈的传递依赖）；回放不需要。不会自动安装或升级依赖。

```powershell
# 在准备好的科学环境中执行；不需要先写 transcript
python scripts/value_lab.py pseudobulk-reference design.json data.json --output reference-v1

# 新机器/CI：不加载 site-packages，也不重新拟合
python -S scripts/science_env.py replay-reference reference-v1 --expected-id <artifact_sha256> --output regression-inputs
```

回放文件放在 `regression-inputs/recorded/`，新的 `playback.json` 明确标记 `scientific_execution=false`、`new_observations=0`、`NOT_RECOMPUTED`。原始 execution 记录留在 recorded 中，避免将旧运行当成新实验。输入/输出/清单被改动、目录已存在或文件链接不合规则阻断。

## 真正重算：先检查原环境锁

```powershell
python scripts/science_env.py check reference-v1/environment.lock.json --expected-id <environment_sha256>
python scripts/value_lab.py pseudobulk-reference design.json data.json --output reference-v2 --environment-lock reference-v1/environment.lock.json --environment-id <environment_sha256>

# 也可在运行前单独冻结某个安装好的计算环境
python scripts/science_env.py freeze --package pydeseq2 --output environment.lock.json
```

环境不匹配时在模型拟合前失败并报告字段路径，不自动降级、不替换包、不将新环境伪装成旧环境。建议在专用虚拟环境和新 Python 进程中运行；通过 `python -I scripts/value_lab.py ...` 可排除用户 site 和 `PYTHONPATH` 注入。冻结、检查、重算应使用相同的解释器启动选项；锁也记录隔离/忽略环境等标志。`-I` 会忽略 `PYTHONHASHSEED`，记录变量不代表该变量已生效。

这是**漂移检测与产物回放**，不是可自动重建环境的 wheelhouse/容器镜像。系统外部动态库、CPU/GPU、内存中已加载或注入的模块、未登记文件和跨平台浮点差异不由该锁完整覆盖；匹配锁不能证明数值必然一致。锁不是恶意进程隔离边界。需要重建环境时仍应由研究团队保存经核验的镜像或包制品，并单独验证数值容差。

## 将录制代理设为 MCP 客户端的 server

以前 `record transcript.json` 的手工导入仍可用。现在将客户端原来的 server 命令包在 `record-live` 后面，真实工具运行一次，客户端断开后自动生成 cassette：

```text
python scripts/offline_eval.py record-live --output captures/run-001 --tool matrix_sum --public-data --timeout 300 -- python public_science_server.py
```

把这整个命令配置为 MCP 客户端的 stdio server；不要只在终端执行后期待它自行构造实验。客户端照常初始化、列出工具、调用工具。代理向客户端暴露选中的工具目录，按请求顺序保存响应，保留 `structuredContent`、`isError` 和 JSON-RPC error；多个请求响应乱序时仍按请求顺序形成确定性 cassette。不自动重试真实工具。

客户端正常关闭后查看 `captures/run-001/recording.json`。只有 `RECORDING_COMPLETE` 和其中的 `cassette_sha256` 才可用于回放：

```text
python -S scripts/offline_eval.py serve captures/run-001/cassette --expected-id <cassette_sha256>
```

后续 CI 使用该 serve 命令作为 MCP server。回放不启动原 server，不访问真实数据源，无匹配调用立即失败，不进行网络兜底。

## 有意保留的边界

- `record-live` 明确执行所选本地 server，可触发真实工具的网络、计算或费用；它不是沙箱。工具授权、服务端凭据、预算及科学数据使用权仍由调用者配置。录制 receipt 的费用默认 `UNKNOWN`，不宣称免费。
- `--public-data` 是调用者对所选工具输入、输出已公开或脱敏的确认。默认拒绝常见 credential 键、Bearer/私钥/API-key 样式及 JSON 文本内的凭据；不自动发现本地数据，不保存 server stderr/raw transcript。该检测**不等同于 PHI/PII 脱敏**，未脱敏研究数据不能仅靠这个开关安全处理。
- 超时、崩溃、取消、缺响应、超预算、协议错误或凭据检测失败不发布成功 cassette。先在暂存目录写入，通过后才重命名发布；失败或进程被硬杀留下的暂存文件不能当作完成证据。receipt 保留已开始的调用数，未知调用结果不自动重试。
- 当前仅支持 tools-only JSONL stdio、已知 MCP 协议、无分页目录；不支持 HTTP/SSE transport、server sampling/elicitation/roots、动态目录更新。现有协议协商可将更新版本回退到支持的版本。
- 总期限默认 300 秒、上限 3600 秒；单消息 1 MiB、会话累计 8 MiB、请求最多 10,000。Linux 清理进程组；Windows 只管理直接启动的受信任 server，任意派生进程不受 OS 沙箱保证。

本地合成 server 和 SDK 往返测试证明录制/回放协议链路；真实 PyDESeq2 的合成输入测试仅证明本地计算链路。两者都不证明生物学有效性、跨平台位级重现或独立审查。
