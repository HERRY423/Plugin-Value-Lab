# 安装 Plugin Value Lab

版本：0.5.0。以下以用户在 Codex 桌面端成功安装的 GitHub 市场配置为主。2026-09-23 已核对 Git 来源、`main` 引用、插件启用状态，并在该任务中实调全部 6 个默认 MCP 工具。[实测记录](INSTALLED-ACCEPTANCE-20260923.zh-CN.md)。

## 按截图添加

在 Codex 桌面端进入“插件 → 添加 → 添加插件市场”，填写：

| 字段 | 填写内容 |
| --- | --- |
| 来源 | `HERRY423/Plugin-Value-Lab` |
| Git 引用 | `main` |
| 稀疏路径 | **留空**；灰色的 `plugins/codex` 是提示，不是要填写的值 |

完整 Git URL `https://github.com/HERRY423/Plugin-Value-Lab.git` 也可作为来源；已安装配置将来源保存为这个 URL。`main` 是本次成功安装采用的分支；希望固定已发布版本时，可改用 `v0.5.0`，但这不是本次用户安装所用的引用。

1. 点击“添加市场”。市场名为 `plugin-value-lab-marketplace`。
2. 回到插件列表搜索 **Plugin Value Lab**，打开后点击**安装并启用**。插件标识为 `plugin-value-lab@plugin-value-lab-marketplace`。
3. 新建一个任务，通过 `@` 选择 **Plugin Value Lab**。若当前任务尚未加载插件，关闭后重新打开 Codex，再新建任务。
4. 发送：“调用 example_value_suite，再用 validate_value_suite 校验返回的方案；不要启动模型评测。”应返回 `real_observations: 0` 和 `valid: true`。文字判据的校准警告仍会保留。

**添加市场、安装插件、启用插件、工具可调用是不同步骤。** 只添加市场后，插件不会自动出现在“已安装”里。`main` 后续可以变化，核对安装缓存中的实际版本，不要仅凭分支名推断版本。

## 已添加市场但没有显示

先确认没有只筛选“已安装”，再搜索插件名称并安装。如果仍未列出，可在已配置该市场的同一 Codex 环境中执行：

```powershell
codex plugin marketplace upgrade plugin-value-lab-marketplace
codex plugin add plugin-value-lab@plugin-value-lab-marketplace
```

第一条刷新已配置的 Git 市场，第二条安装其中的插件。随后重新打开 Codex 并新建任务。这是按本机 CLI 帮助核对的排查方式；不代表用户成功安装时一定执行过这些命令。若本机 `codex plugin --help` 不提供这些命令，请使用桌面端的市场刷新和安装入口。

## 本地文件夹安装（备用）

也可选择包含 `.agents/plugins/marketplace.json` 的市场根目录绝对路径作为来源，Git 引用与稀疏路径均留空，然后安装并启用插件。

给其他用户时，发送 `plugin-value-lab-marketplace-0.5.0.zip`，请对方先解压，在“来源”填写解压得到的 **plugin-value-lab-marketplace 文件夹的绝对路径**。应选择含 `.agents/plugins/marketplace.json` 的市场根目录；不要选 ZIP 文件、JSON 文件或里面的 `plugins/plugin-value-lab` 子目录。这个压缩包可以在任意目录解压，不依赖开发电脑的路径。

## 运行条件

技能可以由宿主加载；本地评估引擎需要 Python 3.11+，MCP 工具还需要 Python MCP SDK。本插件不需要 API 密钥或独立服务账户，不会自动安装 Python、联网下载依赖或启动模型评测。

宿主需要能够通过 `python` 找到 Python 3.11+。在宿主所用的同一个 Python 中，一次性准备已验证的 SDK：

```powershell
python -m pip install "mcp==1.28.1"
```

已有兼容 SDK 时无需重复安装。这个依赖安装会从所配置的软件包源下载代码；核心本地 CLI 不需要它。macOS/Linux 上也应确保宿主 PATH 中的 `python` 指向 Python 3.11+；只存在 `python3` 时，先在该宿主的运行环境中配置对应的 `python` 命令。改动 PATH 后重启宿主。

从市场包中的插件目录检查：

```powershell
python scripts/value_lab.py doctor
```

确认 `offline_engine_ready` 与 `optional_mcp_available` 均为 `true`，并核对 `python_executable`。这只是运行环境检查；安装后还应确认 MCP 工具可调用。建议先调用 `example_value_suite`，它返回教学方案、空观测和 `real_observations: 0`，不运行模型。

新版服务直接运行插件自身的脚本，不再依赖开发目录或提前安装 `value_lab` 包。复制到宿主缓存目录后仍从该副本加载代码。不要在安装缓存里编辑源码，更新应从市场的新版本重新安装。

## 市场目录结构

公开仓库已经包含完整市场，无需自行创建仓库或先下载 ZIP。维护自己的镜像时，保留隐藏目录和插件子目录：

```text
repository/
  .agents/plugins/marketplace.json
  .claude-plugin/marketplace.json
  plugins/plugin-value-lab/
    plugin.json
    mcp.json
    skills/
    scripts/
    value_lab/
    ...
```

来源填写真实的 `所有者/仓库名` 或 Git URL。Git 引用填写仓库实际存在的分支、标签或提交；需要可复现时使用实际发布标签/提交。默认让稀疏路径留空，避免只取插件目录却漏掉市场清单。不要直接把 `plugins/plugin-value-lab` 填成整个市场来源。

仓库访问权限由宿主管理，私有仓库需要用户已有的 Git 访问能力。添加 Git 市场不等于提交到官方公开目录。当前本地 stdio MCP 也不能据此宣称支持没有本地 Python 运行环境的网页或云端宿主。

## 标准包与兼容包

`plugin-value-lab-agent-plugins-0.5.0.zip` 是 Agent Plugins 1.0.0 的便携包，根目录有 `plugin.json`、`mcp.json` 和两个默认技能。研究技能保留在 `extensions/`，退出默认发现；研究与团队入口需在子命令前显式添加 `--enable-extensions`。它不包含旧宿主入口；按目标客户端的 Agent Plugins 加载流程使用。[范围与启用说明](STRUCTURAL-RISKS.zh-CN.md)。

安装后的评估工作台仍是本地进程。可让助手按 `assess-value` 技能定位插件根目录并启动 `python scripts/value_lab.py workbench --data <可写证据目录>`，随后打开打印的本地地址。不要把研究数据写入只读插件缓存。真实 Agent 执行另需本机 Claude Code、认证和模型权限；安装 Value Lab 不会自动提供 Claude 账户。见 [工作台指南](WORKBENCH.zh-CN.md)。

市场包中的插件另外保留 Codex 与 Claude 兼容入口。便携 `mcp.json` 使用标准 `${PLUGIN_ROOT}`；旧 Codex 清单内嵌同一启动配置；Claude 的 `.mcp.json` 使用 `${CLAUDE_PLUGIN_ROOT}`。两种变量不能混用。宿主应按其格式选择配置，不要把三份 MCP 配置手动叠加导入。

Claude 使用自己的市场清单，其 source 是相对路径字符串；Codex 市场 source 是对象。两份文件都指向同一插件副本。可通过 Claude 的市场添加流程选择同一个市场根目录，再安装 `plugin-value-lab@plugin-value-lab-marketplace`。

## 排查与维护

- 找不到市场：检查来源目录下 `.agents/plugins/marketplace.json` 是否存在，解压或提交时是否遗漏隐藏目录。
- 找不到插件：市场根目录与清单中 `./plugins/plugin-value-lab` 应对应；添加市场后再安装插件。
- 技能出现但 MCP 失败：核对宿主的 Python 版本和 SDK；不要用另一个终端环境的成功代替宿主环境。
- 更新没有生效：从正确市场更新/重新安装，然后使用新对话；不要修改个人账户配置来掩盖旧缓存。

开发者在源项目根目录执行 `python scripts/build_marketplace.py --generate --package` 生成分发副本与两个包，`--check` 检查副本是否与源码一致。只编辑根目录源码，`plugins/plugin-value-lab/` 是生成副本。构建过程不修改用户市场配置，也不发布内容。这些构建命令仅适用于完整源项目；用户解压市场包后可直接添加，无需重新构建。

格式依据：[Agent Plugins 1.0.0](https://agent-plugins.org/specification)、[OpenAI 插件打包](https://developers.openai.com/plugins/build/plugins)、本机 Codex CLI 的市场管理契约。实际本地验收结果见插件目录中的 `VERIFICATION.json`；格式一致性、CLI 安装、MCP 握手和真实用户收益分别记录。
