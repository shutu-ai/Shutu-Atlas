# V2 验收记录

本文档只记录已执行或明确未验证的证据。当前文档在实现过程中更新，不把计划当成结果。

| ID | 当前状态 | 证据/命令 |
| --- | --- | --- |
| A01 源项目零改写 | `UNVERIFIED`（基线已采集） | M0 采集了 12 个 Git HEAD/dirty；最终索引后需再次采集并比较，普通目录需抽样哈希。 |
| A02 多项目发现 | `PASS`（发现器层） | `atlas scan --root D:\dev-projects --dry-run` 实测发现 27 个外部候选、12 Git、15 普通源码目录；包含 Python/JS/TS/Go。 |
| A03 全文与能力查询 | `IN_PROGRESS` | FTS5、ripgrep、能力证据和 `get_source` 已实现，需在首次索引结束后记录真实查询结果。 |
| A04 增量更新 | `IN_PROGRESS` | 哈希/mtime、增删清理和 `--changed-only` 已实现，需由 fixture 测试验证。 |
| A05 Serena | `BLOCKED_ENV` | 本机 `serena` 不在 PATH；静态 fallback 和镜像边界已实现，真实 Serena integration test 未运行。 |
| A06 UI Gallery | `IN_PROGRESS` | 静态 UI 识别、源码映射、无截图占位、只读 Gallery 已实现；真实截图采集未授权。 |
| A07 MCP 只读 | `IN_PROGRESS` | 兼容 stdio server 和工具白名单已实现；官方 Python SDK 不存在，正式 SDK client 未通过。 |
| A08 Skill | `UNVERIFIED` | Skill 源文件和备份安装脚本已提供；未执行用户级安装或真实新项目 Codex E2E。 |
| A09 安全边界 | `IN_PROGRESS` | 敏感文件过滤、路径约束、查询上限、源项目不执行已实现，需由测试覆盖。 |
| A10 文档运维 | `IN_PROGRESS` | README、配置、架构、操作、MCP/Skill 文档和 Windows 脚本已提供，待完整测试。 |

结论：在完成自动化测试、真实索引和前后源项目状态比较之前，不能声明 `V2 READY`。

