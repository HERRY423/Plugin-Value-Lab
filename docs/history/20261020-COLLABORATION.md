# 本地研究人员与 agent 协作闭环

本源码增加可选的持久协作入口，尚未发布到 rc5 安装包。它执行 PVL 对已提交记录的本地复算，并串联审阅、纠正、交接和恢复。实际模型调用、GPU/SSH 科研作业仍由宿主负责；这里不会把复算记成新观察。

## 最短使用路径

1. 创建专用本地目录，例如 `C:\lab\pvl-collaboration`。
2. agent 通过 Python API 或显式开启的 MCP 工具创建任务并执行评估。
3. 用 `status` 查看责任人、输入版本、结果摘要和下一步；`result` 返回完整报告。
4. 审阅必须引用具体执行和结果摘要，填写 `accept`、`request_changes` 或 `reject` 及理由。
5. 纠正引用最近一次审阅，另建输入版本；旧输入、结果、失败与审阅全部保留。新版本不会沿用旧审阅。
6. 发出交接后，接收方必须 `receive`，才能继续写入。原责任人可显式取消尚未接收的交接。
7. 导出恢复包并另存检查点。恢复只重建原事件和文件，不执行、不重评分。

每个写请求都提供稳定 `key` 和上一次返回的 `sequence`。同一执行请求重发不会再执行；不同内容复用同一 key 会被拒绝。过期 sequence 会被拒绝，要求先读取状态。执行中断后保持 `EXECUTION_UNRESOLVED`；确认原进程已停止且没有可收集结果后，显式 `resolve`，保留原结果 `UNKNOWN`，再决定是否重试。

## agent 入口

默认六个 MCP 分析工具保持原有行为。宿主设置以下环境变量并重启 **这个源码版本的** MCP 进程后，增加第七个工具 `collaborate_plugin_task`：

```text
PVL_COLLABORATION_ROOT=C:\lab\pvl-collaboration
PVL_COLLABORATION_ACTOR=research-agent
```

根目录必须事先存在。工具不能更改根目录、不能自报真人身份；actor 由宿主固定为 `agent`。所有写入、恢复和临时产物均留在该目录内。不要把共享不可信目录作为根目录。它是单机、单个权威工作副本的协作记录，并非用户认证、RBAC 或分布式锁。

首次调用示意：

```json
{
  "task_id": "study-a",
  "action": "open",
  "arguments": {
    "inputs": {
      "suite": "<完整 PVL suite 对象>",
      "records": [],
      "lock": null,
      "cost_ledger": null
    }
  },
  "key": "study-a-open",
  "expected_sequence": 0
}
```

把 `suite` 占位符换为真实对象。输入可包含 `artifact_files`，它把安全相对路径映射为 base64 文件字节；最多 256 个文件，整个输入不超过 8 MiB。缺失文件保持缺失，声明摘要错误不会被修复。文件仅供内置只读评分器读取，不能触发可执行评分器。大型数据与独立 verifier/corpus 依赖尚未接入此闭环，不能声称已经完成相关检查。

使用现有研究记录时，可在本地准备冻结输入：

```python
from value_lab.collaboration import capture_inputs, dispatch
from value_lab.core import load_json, load_records

inputs = capture_inputs(
    load_json("study/suite.json"),
    load_records("study/runs.jsonl"),
    load_json("study/protocol.lock.json"),
    artifact_root="study/artifacts",
)
opened = dispatch(
    r"C:\lab\pvl-collaboration", "study-a", "open", {"inputs": inputs},
    who={"id": "research-agent", "kind": "agent"}, key="study-a-open", expected_sequence=0,
)
```

这只读取 records 中明确引用的文件，不扫描或上传资料。records 的实际来源、失败、费用声明和原锁文件都会保留。

## 研究人员审阅与接收

`export` 的 `directory` 是根目录下的新目录名。包内包含：

| 文件 | 用途 |
| --- | --- |
| `HANDOFF.md` | 当前责任人、交接说明、下一步和证据边界 |
| `RESULT.json` | 最近一次完整结果 |
| `decision.json`、`events.json` | 全部输入版本、事件、审阅、失败和结果绑定 |
| `checkpoint.json` | 导出时检查点；另存一份用于防止回退 |
| `RECEIVE.request.json` | 待接收交接的请求模板 |
| `REVIEW.template.json` | 绑定具体结果的审阅模板，理由默认留空 |
| `*.blob` | 历史结果的原始字节 |

接收者首先把模板中的 `REPLACE_WITH_LOCAL_TASK_ID` 改成自己的任务 ID。然后在本地运行：

```powershell
python -m value_lab.collaboration --root C:\lab\pvl-collaboration --actor researcher --kind human --request C:\lab\pvl-collaboration\bundle\RECEIVE.request.json
```

检查 `RESULT.json`，填写 `REVIEW.template.json` 的 `verdict` 和 `notes`，再使用同一命令指定该文件。模板的 sequence 只适用于导出时状态和一次接收；若有新事件，先读取最新状态，重新绑定审阅。空理由不能提交。

CLI 的 `--kind human` 只是操作者声明，不提供身份认证。即使记录了真人声明的 accept，`human_acceptance_verified` 和 `human_identity_authenticated` 仍为 false。agent 的 accept 只进入 `AWAITING_HUMAN_REVIEW`，不能完成真人验收。审阅通过也不自动授权下一次科研执行或费用。

## 动作参数

| action | arguments |
| --- | --- |
| `open` | `inputs` |
| `status` / `result` | `{}` |
| `execute` | `attempt_id`, `reason` |
| `review` | `review_id`, `attempt_id`, `result_sha256`, `verdict`, `notes` |
| `correct` | `review_id`, `inputs`, `reason` |
| `handoff` | `handoff_id`, `recipient: {id, kind}`, `note` |
| `receive` | `handoff_id` |
| `cancel_handoff` | `handoff_id`, `reason` |
| `resolve` | `attempt_id`, `reason` |
| `export` | `directory` |
| `restore` | `directory`, `checkpoint` |

命令行 `--request` 接受与 MCP 相同的请求对象。`status`、`result`、`export`、`restore` 不需要 key/sequence；restore 必须提供单独保存的检查点。恢复后要停用原可写副本，保留一个权威工作副本；不同副本不会自动合并。接收者要继续重评分还需要相同软件依赖，导出包不是完整环境镜像。

## 实际验证与待真人验收

本地可运行：

```powershell
python -m unittest tests.test_collaboration tests.test_collaboration_mcp
python scripts/verify_collaboration.py --study PATH_TO_RETAINED_STUDY --output NEW_OUTPUT_DIRECTORY
```

第一条是明确标为 synthetic 的工程边界与真实 stdio 传输测试，不是研究人员或桌面宿主验收。第二条在独立 CLI 进程中读取实际保留的研究记录，故意省略产物输入，再通过 agent 审阅、纠正补入原始产物；保留原方案、全部观察和失败，核对与直接复算的完整报告一致，并生成待真人接收的恢复包。它不会启动新的模型调用。

仍须由真实参与者完成以下验收，当前均不自动标为完成：

- 非作者研究人员阅读结果、提出一条真实纠正意见并确认接收。
- 实际 Codex/Claude 等目标宿主加载新工具并完成一次闭环。
- 非作者在自己的环境恢复，能定位原始失败和 UNKNOWN。
- 与原流程比较实际人工时间、漏接纠正、错误接受和恢复失败；现有工程测试不证明协作收益。
