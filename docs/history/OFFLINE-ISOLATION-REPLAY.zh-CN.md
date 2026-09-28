# 离线隔离与工具快照回放

> 后续在线隔离改动见[在线隔离与 Windows 后端](ONLINE-ISOLATION.zh-CN.md)：本文记录的在线根目录遮蔽已退役，旧计划仅可离线恢复；本文其余离线回放契约继续适用。

本次范围依据用户 2026-09-28 明确要求深度推进“OS 级隔离”和“MCP Mock/录制回放”。版本保持 0.7.0。

## 核查与范围

当前生产源码未找到 `AccessObserver` 类。现有 `native_session.py` 已有 bubblewrap，但在线采集把宿主 `/` 只读挂载后遮蔽指定参考根，保留模型网络和账户配置；不能把它称为禁网的最小文件系统沙箱。原来的 `replay.py` 是材料检查/报告重算，不能替代工具协议回放。

按此次明确请求作一个有界功能例外：增加 `scripts/offline_eval.py` 开发者工具及两项独立 CI 门禁，在已有运行时模块实现隔离和快照逻辑。没有新增主 CLI 子命令、MCP 产品工具、评分器或运行时模块，也未覆盖冻结清单来使检查通过。这个脚本确实是新增能力，不因放在 scripts 中就称为原功能修错。原有在线原生执行不能直接改为全面断网，否则模型请求无法工作；离线回归因此需要单独入口。

## 隔离契约

`run_offline` 必须在已有 Linux/WSL2 + bubblewrap 环境运行。缺少平台、后端或内核权限均失败；不自动安装，不退回 Python Hook、普通子进程或联网路径。

- 空根文件系统只挂载只读 `/usr`、`/bin`、`/lib`、`/lib64`，明确选定且复制的公开 `/inputs`，以及新建可写 `/output`。不挂载宿主 `/`、HOME、`/etc`、`/run`、`/mnt/c`、`/init` 或评分参考。
- 独立 user/PID/network/IPC/UTS 等命名空间；显式映射非零 UID/GID，禁止嵌套 user namespace、删除 capabilities、隔离终端、随父进程终止。
- 清空继承环境，关闭额外文件描述符；只有 stdin/stdout 的限定协议通道和 stderr 日志跨边界。没有注入密钥或网络代理。
- 标准库启动器设置 CPU、地址空间、文件尺寸、文件描述符与进程数量上限；父进程控制墙钟超时和进程组清理。协议行/累计大小和消息数量有上限，响应写入非阻塞，同一超时包含客户端拒读。
- 输入明确列举，拒绝链接、目录穿越、硬链接和 `.replay` 材料；参考答案和快照留在父进程。新目录不可覆盖，保留输入哈希、计划、开始标记、日志、产物和回执。

这不是完整恶意代码防护产品：信任宿主内核、bubblewrap、系统运行时和操作者对“公开输入”的选择；不检测原任务已经含有答案，不阻止先前污染，不证明第三方独立盲法。系统运行时目录仍可读；不要把私密数据放在这些目录。每文件/进程限制不是聚合磁盘配额，namespace 不是独立内核；资源耗尽/内核漏洞等更强威胁仍需专用 VM、cgroup/磁盘配额及独立审计。新入口不自动替换所有已有执行器。

在线 `prepare-native-session` 的计划与披露明确增加 `ONLINE_NAMED_ROOT_MASKING`、`network_isolated=false`、`host_root_mounted=true`，防止混淆证据。旧在线会话未自动重跑。

## 快照契约

`.replay/cassette.json` 含工具目录、按序 request/response 和来源说明。`record` 只导入操作者显式提供并已脱敏的转录，不联系后端、读取账户或自动抓取私有会话。`origin=recorded` 是来源声明，不是认证；`manufactured` 必须保留。哈希由调用方另外保留，防止快照在回放前被意外改写，不证明作者身份。

支持 MCP JSON-RPC 的初始化/版本协商、initialized 通知、ping、tools/list、tools/call。工具请求按名称、精确 JSON 参数和顺序匹配；仅对象键顺序和传输 `_meta` 不影响匹配。不进行自然语言相似匹配、不改路径、不排序数组、不把 false/0/null/缺字段互换。结构结果、内容块、`isError` 工具失败以及 JSON-RPC error 都原样保留。未知工具/参数、重复 ID、遗漏调用、过量调用、畸形/超大 JSON 不能成为完整通过；没有现场调用兜底。

每个回放实例有独立游标；WITH/WITHOUT 或重复运行需新建实例，不能跨组共享消费状态。沙箱的父进程 broker 读取快照，只给子进程返回匹配的工具响应，快照文件本身不挂入子进程。单独 `serve` 适合受控 MCP 客户端接入；把宿主客户端配置成这个 server 本身不会自动隔离该客户端，需同时使用 `run` 或宿主独立的可靠隔离。

所有回执标记 `OFFLINE_CONTRACT_REPLAY`、`backend_calls=0`、`new_observations=0`、`scientific_execution=false`。`REPLAY_COMPLETE` 表示完整复现约定交互，包含正确重现失败响应；不等于被测任务成功。回放结果不生成 live backend receipt，不升级原始报告证据等级。PyDESeq2 真运行及严格版本校验保持原样。

## 使用

准备有限、脱敏的 transcript.json，含 `tools`、`exchanges`、`provenance`。每条 exchange 为 `{"request":{"name":"tool","arguments":{}},"response":{"result":{"content":[]}}}` 或 `response.error`；来源包括 `origin: manufactured|recorded` 与非空 `description`。

```text
python -S scripts/offline_eval.py record transcript.json --output .replay
python -S scripts/offline_eval.py serve .replay --expected-id <record 输出的 cassette_sha256>
```

`serve` 的 stdout 仅输出协议，结束回执在 stderr。缺少调用的 EOF 返回非零码。Linux/WSL 内使用：

```text
python3 -S scripts/offline_eval.py run --inputs public --file client.py --output run-001 --cassette .replay --expected-id <sha256> --timeout 30 -- /usr/bin/python3 -I /inputs/client.py
```

带 cassette 时，子进程 stdout/stdin 是 MCP 请求/响应通道，普通日志写 stderr，最终产物写 `/output`。不带 cassette 时可执行离线程序，stdout/stderr 都保留为日志。只允许明确选择的输入；不要选择评分器、答案、凭据或完整私有项目。

## 分层验收

1. `python -S -m unittest discover -s tests -p test_offline_replay.py -v`：无 site-packages 的标准库回放契约测试，适合快速 CI。
2. `test_offline_mcp.py`：实际 MCP SDK 客户端与标准库服务端握手、工具发现、结构结果、两种错误的互操作；放在完整依赖验收中，不伪装为无依赖测试。
3. `/usr/bin/python3 -S scripts/check_offline_boundary.py --output NEW_DIRECTORY`：真实 kernel 门禁，无 skip。制造参考含空格/换行；尝试 Python open、os.open、libc、cat、符号链接、父 PID 路径；检查独立网络、宿主 TCP/Unix socket、环境清理、只读输入。两次工具回放按字节比较，超时、畸形请求、参数不匹配、未消费和响应背压必须失败。
4. 原有完整 release tests 和科学依赖矩阵继续保留。新 CI 的快速契约、真实 kernel、完整科学环境是三个不同门禁；任何一个通过都不能替代另一个。远端 CI 在实际运行前仅为已配置，不能报告为通过。

## 上游依据

采用 [bubblewrap 官方安全模型](https://github.com/containers/bubblewrap#sandbox-security) 的显式策略与 [参数契约](https://github.com/containers/bubblewrap/blob/main/bwrap.xml)，而不是将工具名视为安全证明。工具响应和错误依据 [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)，初始化依据 [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。这些上游文档定义机制，不代替本项目实际验收。
