# 发布阻断修复：冻结签名与 Windows JSON 管道

产品版本保持 0.6.0，功能冻结状态及截止日期不变。此次只修复已有接口的兼容性，不增加 CLI、MCP、技能、评分器或运行时模块。

## 根因与修复前复现

- Windows / Python 3.12.13：原检查报 `Frozen surface changed: mcp_signatures`，虽然 MCP 参数没有改变。旧冻结文件使用 Python 3.13 省略空字段的 `ast.dump` 表示。
- Windows / Python 3.13.9：令子进程使用 `PYTHONIOENCODING=cp1252:strict`，原 README 五步迁移测试在 `compare-studies` 的 `_emit` 中触发 `UnicodeEncodeError`。这些设置仅用于制造回归条件，产品修复不依赖设置环境变量。

## 冻结表示的迁移

`pvl-feature-freeze-2` 使用项目定义的 JSON 结构。参数顺序、名称、五种传参方式、默认值存在性、带类型的默认值、注解、返回注解及同步／异步方式均参与比较。表达式只遍历明确列出的字段；不使用 `ast.dump`、`ast.unparse`、`eval` 或导入待检查模块的注解来生成签名。位置和 AST 显示元数据不参与比较。未知表达式或泛型函数声明拒绝通过，需明确扩展格式后才能接受。

quoted forward annotation 与对应未引用注解规范为同一结构；注解中的 `Literal` 字符串仍是字符串。该表示只规范语法，不宣称解析类型别名或证明任意 Python 表达式语义等价。`None` 默认值与缺失默认值、`True`、`1` 和 `1.0` 保持可区分。

迁移从旧快照的七条签名解析参数，仅允许已知 AST 构造器，不执行快照内容。每条转换结果都与源码签名核对；所有其他冻结清单保持原值。旧格式未固定返回值和同步方式，此次检查七个既有工具均为同步 `-> dict` 后一并固定。

- 旧冻结文件 SHA-256：`d017558178ddafc47fdd1c087d21dfe9c946fdb8a6e418b7563b5a32ec374c06`
- 新冻结文件 SHA-256：`e7e8fe2a1239f05b427b4caefd673bceedcf5495cf3971bae6ff777a86819cf5`
- 本地迁移脚本、原文件及收据保留于 `work/release-blocker-repair/`，不进入分发包。

## JSON 输出契约

CLI 的成功 JSON 和错误 JSON 共用 `_emit`，使用 `ensure_ascii=True`、`allow_nan=False`。非 ASCII 字符在管道中转义，标准 JSON 解析后逐字符恢复原值，不丢弃或替换字符。文件写入保留原有显式 UTF-8。冻结检查的 JSON 诊断也使用 ASCII 转义。

## 回归覆盖

- 固定期望结构在 CI 的每个 Python / OS 组合运行，覆盖无参函数、位置参数、仅位置参数、仅关键字参数、可变位置参数和可变关键字参数。
- 实际修改 MCP 源码的负向用例覆盖参数删除、新增、改名、改类型、默认值变化／删除、顺序变化、位置／关键字方式、返回类型和同步／异步方式；可选研究工具也在检查范围内。
- 模拟 AST 元数据、行号、空白及引号变化不误报；不支持的表达式拒绝通过；默认表达式不执行。
- README 五步在包含中文和空格的迁移目录中执行，分别使用系统默认、严格 cp1252、严格 ASCII 和 UTF-8 输出，并解析每一步 stdout。比较结果的中文 blockers 与 UTF-8 文件内容逐项一致。
- 成功和错误 JSON 覆盖中文路径、非 BMP 字符、管道和文件重定向，校验原有退出码及 JSON 可解析性；UTF-8 中文产物保真。

## 验收状态

为隔离同一工作区同时进行的原生修复模块改动，最终完整验收使用基线提交 `41704e7b2a47b8d3238a60b7cc423e9f73e01226` 加本次修复的独立副本 `C:/Test/pvl-release-blockers-acceptance-20260926`。并行改动保留在原工作区，不属于此次修复的验收范围。

| 环境 | 实际验证 | 结果 |
| --- | --- | --- |
| Windows / Python 3.11.15 | 冻结与 CLI 专项 17 项；完整冻结结构摘要 | 通过 |
| Windows / Python 3.12.13 | 冻结专项 9 项；完整冻结结构摘要 | 通过 |
| Windows / Python 3.13.9 | 独立副本完整发布套件 556 项，120.680 秒 | 556 通过，0 失败、0 错误、0 跳过 |
| Linux (WSL Ubuntu) / Python 3.12.14 | 冻结与 CLI 专项 17 项；完整冻结结构摘要 | 通过 |
| Linux (WSL Ubuntu) / Python 3.14.4 | 冻结与 CLI 专项 17 项；完整冻结结构摘要 | 通过 |

五个环境对完整冻结接口和包含全部参数方式的样例生成同一规范 JSON SHA-256：`63b65fa4a48a869ab9edf91cbacb3cc171f599bfe78d0cfa4404779a8a7f7dc0`。这不是分别为每个 Python 版本更新快照。

分发验证：冻结检查、八份主线文档约束、marketplace 字节镜像、离线 Agent Plugins schema 均通过；两种 ZIP 与 wheel 构建成功。便携 ZIP 解压到中文目录后，严格 cp1252 环境下的 9 项冻结回归通过。wheel 安装到独立临时目录后，从非源码目录执行五步均成功，检查确认导入来自安装产物；中文 JSON 恢复完整，合成卡仍无绿色条目。

本地日志和机器收据：`work/release-blocker-repair/windows-3.13-release-tests.log`、`cross-version-signatures.json`、`acceptance-snapshot.json`、`portable-archive-regressions.log`、`package-smoke.json`。根目录 `VERIFICATION.json` 追加本次记录，历史测试与哈希记录保留。

远端 CI 未触发；没有提交、推送或发布。现有 Ubuntu / Windows × Python 3.11 / 3.13 CI 矩阵会运行这些固定期望与负向回归。上述证据为本地工程验证，不代表四个远端任务已经转绿、外部采用或科学有效性。Linux 3.11 / 3.13 未在本机执行完整矩阵。
