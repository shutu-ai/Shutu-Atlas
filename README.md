# Shutu-Atlas v0.2.0

Shutu-Atlas 是一个本地优先、只读参考边界的跨项目代码与 UI 资产库。它扫描 `D:\dev-projects` 中的真实项目，把文件、静态符号、能力证据和 UI 源码映射写入本项目的 `.local/atlas.sqlite3`，然后通过 CLI、只读 MCP 和本地 Gallery 按需返回证据。

## 快速开始（Windows PowerShell）

```powershell
cd D:\dev-projects\Shutu-Atlas
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item atlas.example.toml atlas.toml
atlas doctor
atlas scan --root D:\dev-projects --dry-run
atlas index --root D:\dev-projects
atlas list-projects
atlas search-code "task recovery" --limit 10
atlas find-capability "任务重启恢复"
atlas find-symbol submit_sm --project <project-id>
atlas find-ui "dark KPI dashboard" --limit 12
atlas gallery serve --host 127.0.0.1 --port 8765
atlas mcp serve --transport stdio
atlas status
```

没有安装 editable package 时可用 `python -m shutu_atlas.cli ...`。`atlas scan --dry-run` 不创建数据库，也不在源项目写入文件；`atlas index` 只写 `.local`。

## 设计边界

- 发现和索引为静态读取，不执行源项目脚本，不自动启动服务，不自动安装依赖。
- 默认排除 `.git`、环境文件、密钥/证书、依赖目录、构建产物、缓存和过大的二进制文件。
- `atlas get_source` 只能通过已索引的 `project_id + file_id` 读取受限行范围，并返回当前哈希是否过期。
- Serena 采用 Hub 内镜像边界；本机没有 Serena 时，符号查询明确返回 `DEGRADED/BLOCKED_ENV` 并使用静态符号 fallback。
- 本机没有官方 Python MCP SDK 时，内置的是兼容 MCP JSON-RPC stdio 协议的只读服务；`atlas_health` 会明确报告 SDK 状态，不冒充 SDK 集成通过。
- Gallery 是标准库只读 HTTP 服务。没有真实截图时显示“未采集截图”，不会生成合成图片；可用 `gallery import-screenshot` 导入用户主动指定的真实截图。

## MCP

stdio 工具：`atlas_list_projects`、`atlas_find_capability`、`atlas_search_code`、`atlas_find_symbol`、`atlas_get_source`、`atlas_find_ui`、`atlas_get_ui_detail`、`atlas_suggest_reuse`、`atlas_health`。没有写文件、Git、命令执行或索引刷新工具。

Codex/OpenCode 配置示例见 [`docs/MCP_Skill_Integration.md`](docs/MCP_Skill_Integration.md)。脚本只生成备份/合并建议，不自动改用户配置。

## 文档

- [`docs/00_Discovery_and_Constraints.md`](docs/00_Discovery_and_Constraints.md)：M0 真实盘点与边界
- [`docs/Architecture.md`](docs/Architecture.md)：架构与数据流
- [`docs/Acceptance_V2.md`](docs/Acceptance_V2.md)：逐项验收证据
- [`docs/Operations_Windows.md`](docs/Operations_Windows.md)：安装、升级、备份与故障排查
- [`docs/MCP_Skill_Integration.md`](docs/MCP_Skill_Integration.md)：MCP/Skill 集成说明
- [`skills/local-project-reuse/SKILL.md`](skills/local-project-reuse/SKILL.md)：跨 Agent 复用 Skill

