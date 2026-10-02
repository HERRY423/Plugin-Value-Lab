# 真实宿主上下文采集 P0：Codex 桌面 0.159.2

授权日期：2026-10-02。用户要求“真实宿主采集层完成验收”。范围限定为当前实际可读的 Codex 桌面宿主，rollout 的 originator 为 codex_work_desktop、cli_version 为 0.159.2。这不是对所有 Codex 版本、Claude 或其他宿主的通用验收。

## 采集与绑定

`value_lab/codex_context.py` 只读一个显式指定的本地会话日志；不搜索其他聊天，不更改宿主配置，不启动模型或后台轮询，不发送对话到第三方。独立脚本 `scripts/collect_codex_context.py` 导出结构化采集快照，输出文件已存在时拒绝覆盖。

每个请求保留 session/thread、turn、从 turn_context 实际观察的模型、response_id、宿主与引擎版本，并引用原事件的时间戳、行号、字节区间和 SHA-256。采样阶段明确为 response_usage_recorded / post_response_token_count。只有逐请求 usage 与对应 token_count.last_token_usage 一致，且会话、轮次、模型和时间均可绑定时，才给出测量值。重复 response_id 或错误会话会被拒绝；重复 token_count 不增加请求数。

原始日志留在宿主；导出的快照不包含消息正文、系统提示、工具输入输出、工作目录或原日志路径。字节摘要用于核对本地来源，不能证明供应商签名或独立审计身份。

## 三项 P0 的口径

| 要求 | 实现 |
| --- | --- |
| 当前采样占用与累计消耗分开 | `latest_context_sample.context_tokens` 来自响应匹配的 last_token_usage.total_tokens；`thread_cumulative_usage`、`turn_cumulative_usage` 和 `context_stream_cumulative_usage` 分列保留原生账本，不参与占用比例计算。 |
| 未知不补零 | 缺字段、缺窗口、未匹配的事件、半行写入、模型/轮次缺失、压缩后仅有估计、未知宿主版本均保持对应的 null / 未知状态。完整匹配的真实零值才保留为零。 |
| 宿主、模型、会话、采样点绑定 | session_meta → turn_context → token_usage_record.response_id → 同值 token_count，保留每段原生事件引用。模型不从启动请求或文件名猜测。 |

请求输入 `usage.input_tokens` 已包含缓存输入，不能再次加 cached_input_tokens。完成响应时的上下文占用使用 `input + output`；原负担视图的指标仍是“主代理请求输入峰值”，使用单独的 request_input_fraction，不能偷换为响应后总量。

比例为采样计数除以宿主报告的窗口容量，不声称复刻宿主界面对保留空间、基线或舍入的显示算法。

两个原生累计账本可能采用不同范围，分别保留，不相互补值或择大合并。token 数也不构成已结算费用；settled_cost_usd 保持 null。

## 压缩、时效与完整性

compacted 事件会使当前采样失效；压缩调用单独标记 COMPACTION_RESPONSE，不计作主代理正常请求。实际日志存在“input_tokens 为 0、total_tokens 非零”的压缩后记录；它只保留为宿主估计，measured_context_tokens 仍为 null。下一次完整匹配的真实响应才能恢复测量状态。

最新采样仅代表标明时间点的观测，不能冒称工具结果追加后、下一次请求前或此刻实时占用。采集时若最新请求尚未写完对应上下文事件，latest_context_sample 为 null；last_measured_context_sample 单独保留历史测量，不将它改称当前值。

这份真实会话包含历史观察和仍在进行的工作。完整性只针对保留的日志字节前缀与明确采样阶段，不证明宿主未记录的请求不存在，也不自动产生完整实验或合格候选。该适配器不把当前聊天制造成 WITH/WITHOUT 或插件组合研究。

## 使用与复现

```text
python scripts/collect_codex_context.py --rollout LOCAL_ROLLOUT.jsonl --session-id EXPECTED_SESSION --output NEW_CAPTURE.json
python scripts/collect_codex_context.py --rollout LOCAL_ROLLOUT.jsonl --session-id EXPECTED_SESSION --prefix-bytes RETAINED_READ_BYTES --output REPLAY.json
python -m unittest tests.test_codex_context -q
```

prefix-bytes 用于重放已保留的同一字节前缀，即使宿主之后追加了新事件，也不改变该快照的结果。若前缀已不存在或完整 JSON 行损坏则拒绝。活动日志末尾未写完的行不解析为零，也不认定完整。

真实验收与制造的异常测试分开：真实记录验证宿主事件绑定、缓存与计数关系、实际压缩、后续追加和前缀重放；单元测试覆盖缺失、错配、重复、未知版本和损坏。验收汇总单独写入 `docs/evidence/native-context-p0-20261002.json`，完整本地采集放在项目外的本次验收目录，原会话日志不打包发布。

本次保留的第二份真实快照共有 131 个响应记录：129 个已匹配测量点、1 个单独排除的压缩响应、1 个等待对应上下文事件的进行中请求。相较第一份快照新增 4 个响应；旧字节前缀重放一致。实际压缩后的 24,889 token 宿主估计没有成为零值测量，后续真实请求恢复为 42,969 输入 token。完整回归通过 1132 项测试，零跳过；这些数量只对应本次保留前缀，不代表此后持续更新的会话总量。

计数语义参考 [OpenAI Codex 的 token_usage 实现](https://github.com/openai/codex/blob/main/codex-rs/tui/src/token_usage.rs)：单次上下文和累计会话用量是不同用途，缓存输入属于输入计数的一部分。在线 main 仅作解释材料；本次具体支持范围由本地版本和保留的真实事件确定。
