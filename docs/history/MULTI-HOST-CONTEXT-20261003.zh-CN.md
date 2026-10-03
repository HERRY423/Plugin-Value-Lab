# 多宿主原生上下文采集：2026-10-03

本次由负责人明确要求“扩大宿主覆盖……Claude Code 和其他宿主如 DSH 和 Antigravity 补齐”。这是限定的宿主适配范围变更：增加只读采集模块、独立脚本及验收，不更改主 CLI、MCP、评分器、版本或既有 Codex 采集器。旧证据保持原身份。

## 实际覆盖

| 宿主与原生输入 | 本机真实记录 | 已支持 | 尚未建立 |
| --- | --- | --- | --- |
| Claude Code 2.1.288，持久化 projects JSONL | 26 个原生会话；25 个包含 39 个已结算响应，1 个失败会话没有已结算响应 | session / message / model 绑定，最终用量，缓存归一化，响应后采样，多 block 去重 | 原生 turn ID、响应绑定的容量、持续实时占用、其他版本 |
| DSH session format v4，连接的 Zstandard 帧 | 6 个会话；5 个有 282 个最终响应，1 个空会话 | 原生 session / turn / step / seq、缓存分桶、settlement 替换与 retry 分开、响应后采样 | 生产程序版本（日志没有该字段）、原子绑定容量、实时预测占用 |
| Antigravity Desktop，本地 SQLite gen_metadata | 1 个真实数据库，49 条响应元数据 | 原生 cascade / response / model，6 个原始计数字段及缺失状态，数据库和行摘要 | 输入与缓存归一化口径、上下文占用、容量、数据库生产版本 |
| Antigravity Desktop 与 Antigravity IDE 的文本转录 | 各 1 份真实转录 | 识别为不支持 token 采集，保留负面证据 | 文本转录没有原生用量和会话绑定；目录名不能补齐 |

因此本次新增 **321 个已有真实响应的读取样本**（Claude 39 + DSH 282），另有 **49 条 Antigravity 原始用量元数据**。DSH 另有 17 条尝试缺少用量，单独保留为未知。重读、前缀重放、制造测试都不增加独立模型运行数；本次没有调用模型或付费工具。采集不等于科学有效性、宿主插件加载验收或插件收益。

## 使用

从用户明确选择的输入读取，不自动遍历账户目录，不输出消息、提示词、工具参数或私有路径。输出新文件，拒绝覆盖已有证据。

```powershell
python scripts/collect_host_context.py --host claude-code --source <persisted-session.jsonl> --session-id <native-session-id> --output <new-capture.json>
python scripts/collect_host_context.py --host dsh --source <session.v4.jsonl.zstd> --session-id <native-header-id> --output <new-capture.json>
python scripts/collect_host_context.py --host antigravity-db --source <offline-conversation.db> --session-id <native-cascade-id> --schema-binary <language_server.exe> --output <new-capture.json>
python scripts/collect_host_context.py --host antigravity-transcript --source <transcript.jsonl> --session-id <selected-id> --output <new-capture.json>
```

DSH 压缩文件读取使用可选 Python `zstandard`；也可传入用户本地解压后的 JSONL。解压前后均限制 64 MiB，压缩源与解压后完整事件前缀分别绑定摘要。多个 Zstandard 帧全部读取，不能只读首帧便宣布会话为空。`--prefix-bytes` 指解压后的精确字节边界，不是增量游标。新宿主尚未实现 Codex 的持久化增量恢复。

输出内的 `capabilities` 沿用 `pvl-host-capabilities-1`。消费者按语义字段检查；不把宿主健康布尔值代替逐字段状态。单次 usage 与 context sample 分开：压缩或不完整尾事件使当前采样未知，但已保留历史响应不会变为零。模型调用、费用、插件身份、工具加载、两臂匹配与累计账本不由本适配器推定。

## 口径与发现

Claude 的 SDK stream-json 在本次真实记录中存在同一 message ID 的多个 block，且常显示 `stop_reason=null, output_tokens=0`。最终持久化 projects 日志才有已结算用量。适配器只接收精确 2.1.288、明确 stop reason、原生 UUID 和不同 apiBlockIndex；同一响应的相同最终计数合并，冲突或重放拒绝。session-wide result 不反推单个响应。输入归一化为 uncached + cache read + cache creation；输入加输出是响应时采样，不能解释为当前实时 prompt。

DSH 上游明确将 inputTokens 定义为 uncached bucket，usage settlement 在相同 turn/step 内替换；retry-started 才开始另一次尝试。上下文压力的 numerator 与 denominator 是独立 last-wins 字段，projectedTokens 还包含 surface 估计。适配器保留原生结算用量，只接受同一 turn/step 的绑定，拒绝重复 seq，不把 request/context.contextWindow 拼为一个原子百分比。[上游 usage projection](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/token-meter/src/usage-projection.ts)

Antigravity Desktop 的文本转录不足，但其 conversations SQLite 的 gen_metadata 含 protobuf 原生用量。字段号来自本机安装的 **2.19.1** language_server 内嵌的三个描述符；整个二进制与各描述符摘要均固定。二进制变化需要重新资格核验，不能继续猜字段号。此版本只描述已检查的 reader，不冒充历史数据库的生产版本。

在真实 Antigravity 数据库中，cache_read_tokens 可以大于 input_tokens，说明不能照搬 CLI JSON 的示例口径。当前只输出 raw_native_usage，request_usage/context_sample 保持 UNKNOWN。proto3 缺省标量保持 null，不将缺失当作实测零。数据库读取限定无非空 WAL/journal 的稳定离线快照，前后摘要必须相同；不启动语言服务器，不修改账户配置。[官方 CLI headless 格式](https://www.antigravity.google/docs/cli/headless/)不能替代桌面数据库资格核验。

本机 agentapi 元数据命令返回 `ANTIGRAVITY_LS_ADDRESS is not set`；该入口没有通过验收。IDE 文本转录的负面结果不能套用桌面数据库读取资格。要完成 Antigravity 的规范化上下文验收，仍需对同一响应取得官方 runtime 的原子用量／上下文输出并与数据库逐项核对，固定生产版本与缓存口径；当前不声称这一步已完成。

## 证据与复验

脱敏摘要见 [本次验收记录](../evidence/multi-host-context-20261003.json)。原始账户文件不进入仓库；本地 capture 文件只含计数、标识和摘要，实际路径映射单独保留在私有源选择记录。收据给出采集文件摘要及原始源摘要，不能代替源文件认证。

新增测试覆盖缓存去重、最终块与未结算流、重试替换、foreign session、版本改变、compaction、缺字段／布尔／负数／溢出、尾行截断、protobuf 截断、未知二进制、WAL 拒绝及不覆盖旧证据。制造测试单列，不充作本机原生运行。Windows 测试使用项目内可写临时目录；默认沙箱临时目录的权限失败不算产品通过。

本轮最终全量回归 **1398 项通过、0 跳过**（Windows Python 3.13.9，沙箱外，工作区内 TEMP/TMP）；新增采集专项 20 项及既有 Codex/能力契约 46 项通过。沙箱内运行停在已有 MCP stdio 测试；相同单项在沙箱外 2.506 秒通过，故不将沙箱内的中断记为通过。35 份真实采集输出通过共享能力 schema；冻结接口与 marketplace 镜像检查通过。源码交付未替换账户内已安装缓存，也未发布。
