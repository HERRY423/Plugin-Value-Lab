# L0/L1 一条命令与实验室模型配置

这是本地工程实现；尚未证明实验室复用率、真实插件收益或生产宿主适配。L0/L1 指 PVL 取证阶段，与 Parrhesia 审查档位无关。清单作为一个插件组合比较，不从多个候选中事后挑选赢家。

当前已停止新增功能，v1.0 等待 1 个外部实验室完成 L1。按[数据治理说明](../DATA-GOVERNANCE.md)，机构内受限数据试用必须使用机构内模型与批准的工具出口；下文支持外部 API 的技术能力及预算冻结不构成受限数据外发许可，实验室自有云 API 账户也不例外。

## 一条命令

```console
pvl screen --plugins plugins.json --tasks tasks.json --settings lab-screen.json --output screen-01
```

输出仅有三种业务判定：**停止 / 证据不足 / 进入先导**，同时写 `use-card.md`、`result.json`、`frozen-plan.json`、`schedule.json` 和完整运行记录。非法 JSON／无效命令属于输入错误，不伪装成业务判定。不覆盖已有目录。源码 checkout 可使用 `python -m value_lab.easy_cli` 替代 `pvl`。

最小输入示例见 `examples/screening/`。省略 settings 时采用单次 $0.10、任务 $1、600 秒；没有适配器或已收集的配对记录，就返回证据不足，列明下一步，不虚构测试通过。

L0 检查声明、权限、出口、许可、版本身份。每项 `pass/fail/UNKNOWN` 必须附 `evidence_ref`；这是实验室提供的检查记录，PVL 不把字符串或哈希当成真实性验证。已核实不适配→停止；缺字段→证据不足。

L1 要求 3–5 个任务，覆盖 positive、failure、boundary，各有输入、baseline 和 rubric。每任务有/无插件各两次，合计 12–20 次；执行顺序、阈值与适配器文件在调用前冻结。保留失败、未知与额外/重复记录，不填补缺失分数。已核实关键失败立即停止；未核实风险停止执行并判证据不足。完整配对才按每任务等权均值、逐任务退化上限和人工修正时间判定。达到阈值只允许进入独立先导，不提供采用结论或总体显著性。

## 实验室自己的执行适配器

`lab-screen.json` 可包含以下 `runner`（其余为可选阈值/预算）：

```json
{
  "per_request_micros": 500000,
  "total_micros": 10000000,
  "max_seconds": 600,
  "runner": {
    "argv": ["python", "lab_adapter.py"],
    "files": ["lab_adapter.py"],
    "timeout_seconds": 30,
    "upper_micros": 500000,
    "bound_ref": "lab-approved-transport-bound-v1",
    "ledger": "C:/lab/budget.sqlite",
    "task_id": "plugin-screening-study"
  }
}
```

账本必须已存在，额度必须匹配。适配器经 stdin 接收 `pvl-screen-run-1`：冻结 `plan`、`task_id`、`repeat`（0/1）、`arm`（with/without）。stdout 只返回一个 JSON 对象：

```json
{
  "status": "completed",
  "score": 0.8,
  "critical_failure": false,
  "evidence_ref": "output-and-runtime-record",
  "scoring_ref": "rubric-assessment-record",
  "cost_micros": 0,
  "cost_ref": "explicit-offline-zero-api-cost",
  "correction_seconds": 12
}
```

关键失败要停为“已核实伤害”时还须给 `critical_verified_ref`。失败可按冻结 rubric 返回 `status=failed` 及有依据的分数；无可恢复评分应保留 null。`cost_micros=0` 只表示显式记录的零 API 费用，不包含硬件、电力或人时。未知费用使用 null。

适配器是**实验室信任的执行器，不是隔离沙箱**，负责真实启用/禁用插件、相同模型/输入/评分、上下文隔离、子进程清理和实际传输费用上限。PVL 每次启动前在共享账本预留 `upper_micros`；该值必须是传输上界，不能来自 token 猜测。记录中的费用是实验室声明，不是认证账单；不会据此自动释放预留。适配器自行绕过网关的调用不受网关保护。

不要对同一调用在筛查账本和模型网关账本重复预留。采用适配器整次包络时，该适配器须有独立且不超过包络的传输限制；采用逐模型网关记账的真实宿主时，可在宿主完成后导入记录。两个入口共享实验室冻结预算的语义，但不会假装为任意宿主提供自动插件执行或转换。

已有宿主记录可用同一命令导入：

```console
pvl screen --plugins plugins.json --tasks tasks.json --frozen screen-01/frozen-plan.json --results paired.json --output screen-02
```

`paired.json` 为 `{ "plan_sha256": "…", "runs": […] }`，每行包含上述 receipt 字段，另有 `plan_sha256/task_id/repeat/arm`。冻结后不改阈值或输入；`--frozen` 只导入，不重跑。相同冻结方案的启动键持久保存，换输出目录不能重新派发未知请求。哈希不证明预注册；导入者负责保留真实采集时间和原始证据。

## 自有 API、本地与内网模型

```console
pvl freeze-models --policy lab-models.json --ledger budget.sqlite --task-id study-01 --history history.json --history-ref lab-cost-inventory --output model-freeze
```

该命令不访问网络、不读取 API key、不调用模型。新账本要求显式历史清单；`[]` 是实验室对确实无历史费用的声明，不能用于重新开始已有任务。已有账本省略 history 参数，只重新打开，不能改写额度或抹去费用。未知历史阻止发送。冻结结果 `gateway.json` 可交给实验室执行器的 `ModelGateway`；原生 sandbox 配置使用其内容作为 `gateway` 字段。

模型政策字段：`endpoint`、`protocol`、`network_scope`、`allowed_addresses`、`tariffs`，可选 `per_request_micros/total_micros`（默认 100000/1000000）。每个白名单模型都必须单独冻结 id、model、context_tokens、max_output_tokens、input_micros_per_token、output_micros_per_token、source、含时区的 expires_at。费率以 USD micros/token 表示，可为小数，最后向上取整到 micros。一个政策内的所有模型共享任务账本；使用多个端点可冻结多个政策并引用同一账本和相同额度。

| 配置 | 支持范围 |
| --- | --- |
| `anthropic_messages` | 标准 `/v1/messages` 文本与客户端工具；现有 Claude 原生桥继续使用此协议 |
| `openai_chat` | 标准 `/v1/chat/completions` 文本；用于实验室兼容接口适配器，不把 Claude 原生桥转换成其他宿主 |
| `public` | HTTPS 443；每次 DNS 检查，禁止私网地址 |
| `local` | 显式 IP 白名单，仅 loopback，可 HTTP；适合本机服务 |
| `intranet` | HTTPS，可自定端口，精确 IP 白名单仅 RFC1918/ULA；不接受 metadata/link-local 地址 |

API key 只由父进程从指定 `PVL_…` 环境变量读取。默认 `api_key`：Messages 用 `x-api-key`、Chat 用 Bearer。显式 `--no-auth` 仅允许 local/intranet。内网 TLS 仍验证证书，使用实验室受信 CA；不提供关闭验证开关。

费用预留采用完整输入窗口加最大输出的保守包络；这可能阻断便宜的短请求。实验室可冻结更高额度，不能以估算输入长度冒充硬上界。未知费率、过期任一白名单费率、名单/端点/额度漂移、图片、缓存、服务端工具、推理扩展等未定价功能均拒绝。没有自动重试、自动换模型或重定向。零费率必须显式声明，仍计次数并保留幂等性。提供方实际账单超出冻结上界时应保留超额并阻断后续，不声称 PVL 控制了提供方账户。

政策样例是模板，不是当前公开费率。历史内置单模型费率及到期日不被自动延长。L2/L3 序贯统计设计仍未实现；本次没有付费调用、真实宿主验收或实验室用户效果试验。
