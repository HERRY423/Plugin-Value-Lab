# 在线原生会话：断网宿主与受限模型网关

本轮依据用户明确要求，改进在线与离线隔离断层、原生 Windows 支持。版本保持 0.7.0。冻结接口只增加 `prepare-native-session --sandbox` 和 `online_sandbox.py` 模块；不增加 MCP 工具或评分器。原 `ONLINE_NAMED_ROOT_MASKING` 启动实现已移除，旧计划不能再次执行；`finish-native-session` 仍可离线恢复旧结果。

## 边界变更

```text
父进程：计划、评分参考、真实 API 密钥、HTTPS 提供方连接
       │ 有限的 JSON/pipe RPC（不是通用网络代理）
       ▼
断网沙箱：只读运行时与公开插件快照 + 新建 native/、retained/
       └─ 客体内 127.0.0.1 HTTP → 原生 Claude SDK
```

子进程没有宿主根挂载、账户 HOME、CLI 登录目录、Docker socket 或继承的代理/密钥环境。公开插件只复制冻结计划列出的 plugin_files 和 case_files；未列举文件不进入挂载。父进程只暴露两处结果目录，计划、评分参考和网关回执留在外部。

模型调用由父进程执行。只支持冻结的一个 HTTPS origin（443）、明确模型列表、`POST /v1/messages` 与 `/v1/messages/count_tokens`，可带固定 `beta=true` 查询。请求不能选择 URL、Host、Authorization 或 CONNECT；不读取系统 HTTP_PROXY，不跟随重定向。解析出的所有地址必须是公网地址，连接使用已检查的 IP，TLS 仍校验提供方域名。API key 只在父进程请求头中加入，子进程拿到不可用的占位值。

每次请求先计入冻结的请求限额，验证输出令牌上限；请求体最多 2 MiB，响应最多 8 MiB，协议/日志累计最多 64 MiB。记录编号、摘要、大小和状态，不记录真实密钥或请求原文。超时、HTTP 错误、重定向、非法帧或未知结果终止本次运行，不重试购买，也不回退到宿主网络。DNS/传输在受监督线程中执行；会话截止后阻止迟到连接，已发请求仍保留费用未知。

SSE 响应目前先在父进程内有界缓存，再原样交给 SDK；这不是逐 token 低延迟转发。SDK 兼容性、长推理请求与真实费用必须通过另行授权的小试确认。请求数/输出令牌上限与原生 `--max-cost-usd` 估计均不构成美元结算硬上限。

## 两个平台

| 后端 | 实际执行边界 | 必备环境 |
| --- | --- | --- |
| bubblewrap | 独立 network/PID/user 等 namespace，空根加明确挂载，禁止嵌套 user namespace，清空 capabilities/环境 | Linux 或 WSL2，已有 bwrap、可信系统 Python 与独立 Claude 运行时目录 |
| windows-hyperv | 原生 Windows 客体内核，`--isolation=hyperv --network=none`，ContainerUser，2 GiB 内存与 2 CPU，显式四处挂载 | 本地原生 Windows 容器引擎、可用 Hyper-V、兼容的已存在 Windows 镜像 |

Windows 后端不会调用 WSL；拒绝 Linux Docker 引擎、process isolation、可变镜像标签、自动拉取、隐式 volumes 与远程 Docker endpoint。镜像必须按本地 `sha256:...` ID 冻结，内含 `C:\runtime\python.exe`、标准库及选定原生 Claude 可执行文件。信任这个镜像及其系统依赖，不能在镜像里嵌入账户密钥。控制器关闭 Docker 客户端后还要删除本次随机命名的容器；不能确认清理时保留 UNKNOWN，不做离线收集完成声明。

这两个后端有不同内核边界，不声称字节级或威胁模型完全相同。Linux namespace 共享宿主内核；Windows Hyper-V 使用独立客体内核。都需要可信内核/后端/运行时，不能替代专门恶意代码防护产品、聚合磁盘配额或独立安全审计。原离线 `offline_eval.py` 仍是 Linux/WSL 的独立回放入口。

## 准备与运行

由 Agent/操作者按实际运行环境创建配置；以下为明确的部署示例，不是已运行的环境：

```json
{
  "format": "pvl-online-sandbox-1",
  "backend": "bubblewrap",
  "runtime": "/opt/pvl-selected-claude-runtime",
  "executable": "claude",
  "gateway": {
    "endpoint": "https://api.anthropic.com",
    "models": ["YOUR_CONFIRMED_MODEL_ID"],
    "api_key_env": "PVL_MODEL_API_KEY",
    "max_requests": 12,
    "max_output_tokens": 4096,
    "request_timeout_seconds": 90
  }
}
```

Windows 将 backend 改为 `windows-hyperv`，runtime 填实际已有镜像的完整 ID，executable 填相对于 `C:\runtime` 的原生程序（例如 `claude.exe`）。只支持 API key 类型的 Anthropic Messages 兼容接口；不会复用宿主 OAuth 登录目录，也不支持 Bedrock/Vertex/cloud SDK 凭据链、代理任意网站或任意外部 MCP。其他配置会阻断，不偷偷降级。

```text
python scripts/value_lab.py prepare-native-session PLAN --plan-sha256 PIN --plugin CANDIDATE --invocation invocation.json --sandbox sandbox.json --output NEW_SESSION
```

该预检不读取真实模型密钥、不调用 LLM：核对来源、快照/运行时、实际客体版本、参考读阻断、无直接网络、客体回环可用。Linux 还比较真实 network namespace inode，并检查只有 lo。当前 native 绑定仍限已有 2.1.278 剖面，其他版本不会被猜测为兼容。

确认既有任务授权覆盖材料发送、提供方和费用后，使用原来的 `run-native-session --session-sha256 ... --execute`。真实密钥仅在执行时从明确的 PVL_ 变量读取；不把密钥写入配置、命令行、计划或仓库。开始标记具有排他性；未知中断不自动重启。SDK 可能需要不同供应商特性；不为兼容而扩大目标/网络白名单。

## 证据上限

`scripts/check_online_boundary.py` 是真实 Linux/WSL 内核验收：主机可读诱饵与可连接回环服务作正控制，子进程通过 open/os.open/libc/子进程/符号链接尝试读取，验证私有引用、凭据诱饵、未挂载副本、父进程路径、只读公开材料、宿主回环、网络 namespace 与模型 RPC。原生版本程序及提供方响应是制造 fixture；因此它证明内核边界与通道工作，不证明真实 Claude/LLM 已试跑。

本机当前有 Docker 客户端，但查询本地 docker_engine 管道失败；Windows Hyper-V 尚无真实内核验收。Windows 命令/策略单测与错误引擎拒绝测试不能代替这一步。不能把新增后端接口报告为已经获得与 Linux 同等级实测保障。

本次封闭的是在线采集器的宿主文件、账户与一般网络访问。原生 eval orchestrator 仍要读取公开候选中的用例定义；其内部 Agent 是否能看到同一份 rubric、原生临时目录是否达到完整盲法，并未由外层沙箱独立证明。评分参考仍应在独立 references 目录中。原生诊断/离线捕获、Codex 独立采集器等其他入口不因本次改动自动获得这一剖面。

依据：[Microsoft Hyper-V isolation](https://learn.microsoft.com/en-us/virtualization/windowscontainers/manage-containers/hyperv-container)、[Windows 容器网络边界](https://learn.microsoft.com/en-us/virtualization/windowscontainers/container-networking/network-isolation-security)。这些资料解释平台机制；项目是否正确调用仍以实际测试为准。
