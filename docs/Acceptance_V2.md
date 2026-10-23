# V2 验收记录

本文档只记录已执行或明确未验证的证据。当前文档在实现过程中更新，不把计划当成结果。

| ID | 当前状态 | 证据/命令 |
| --- | --- | --- |
| A01 源项目零改写 | `PASS_WITH_SCOPE` | M0 与索引后两次只读快照的 12 个 Git 项目 HEAD/dirty 完全一致；未创建源仓库 `.serena`。15 个普通目录未做完整内容哈希，范围限制已记录。 |
| A02 多项目发现 | `PASS` | `atlas scan --root D:\dev-projects --dry-run` 实测发现 39 个外部候选（含嵌套源码项目），索引实际覆盖 5 个真实 Git 项目、1,580 个文件，技术栈含 Python/JavaScript/TypeScript/Go。 |
| A03 全文与能力查询 | `PASS` | FTS5 + ripgrep 实测查询 `mcp`、`任务重启恢复`、`趋势图`；返回真实项目、文件、行号、Git HEAD/dirty 和证据片段；`find-symbol main` 明确返回 static fallback。 |
| A04 增量更新 | `PASS` | `tests/test_index.py::test_incremental_change_and_remove` 通过；哈希/mtime、增删清理和 `--changed-only` 实测，真实索引 run 2 为 0 个错误。 |
| A05 Serena | `BLOCKED_ENV` | 本机 `serena` 不在 PATH；静态 fallback 和镜像边界已实现，真实 Serena integration test 未运行。 |
| A06 UI Gallery | `PASS_WITH_SCOPE` | Gallery API、桌面/移动 Playwright 截图、真实 Vue/ECharts UI 资产映射和明确“未采集截图”占位均通过；源项目未获截图启动授权，未声明真实截图采集通过。 |
| A07 MCP 只读 | `PASS_WITH_SCOPE` | stdio initialize/tools/list/atlas_health smoke test 通过，9 个工具均为查询；官方 Python SDK 安装受网络 WinError 10013 阻塞，SDK client test 为 skipped。 |
| A08 Skill | `UNVERIFIED` | Skill 源文件、Codex 安装 dry-run/备份脚本已提供；未执行用户级安装或真实新项目 Codex/OpenCode E2E。 |
| A09 安全边界 | `PASS` | fixture 测试验证 `.env`/credentials 排除、项目隔离、源码边界和未索引 file_id；Gallery 路径穿越请求被拒绝；源项目脚本未执行。 |
| A10 文档运维 | `PASS_WITH_SCOPE` | README、配置、架构、操作、MCP/Skill 文档、Windows 脚本、Git 本地提交已提供；CLI `doctor/status` 与 5 passed/1 skipped 回归通过。 |

实际测试：`python -m pytest -q` → `5 passed, 1 skipped`；`atlas doctor` → SQLite FTS5 PASS、ripgrep PASS、Serena BLOCKED_ENV、官方 MCP SDK BLOCKED_ENV；Gallery `/api/health` 与 `/api/ui?q=ECharts` → PASS；MCP stdio 协议 smoke test → PASS。

结论：当前交付为 `PARTIAL`，不能声明 `V2 READY`。阻断项是 Serena 真实 integration、官方 MCP SDK client、Codex Skill E2E 和 OpenCode Skill E2E；这些环境缺失/未授权，未用模拟结果冒充通过。

