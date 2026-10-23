# M0 真实盘点与约束

盘点时间：2026-10-23。盘点使用 PowerShell、只读 `git rev-parse`/`git status`、文件名和小型配置读取；没有运行源项目构建、测试、迁移、安装或开发服务器。

## 目录与项目

- `D:\dev-projects` 一级目录总数：48。
- 排除隐藏工具目录和本项目后，外部一级目录：41。
- 当前发现器能识别的外部候选项目：27，其中 Git 根 12 个、普通源码目录 15 个。
- Git 项目的状态基线：3 个 clean、9 个 dirty；`git status` 只读采集，dirty 是源项目原有状态，不由 Shutu-Atlas 修改。
- Git 根中 `High-End_Feature_Phones` 能检测到 `.git`，但当前没有可读 HEAD；这被保留为真实的 Git 元数据缺失，而不是伪造提交。

代表性真实项目和技术栈：

| 项目 | Git HEAD（只读） | 识别技术栈/线索 |
| --- | --- | --- |
| `carbon-lens` | `d2c2cfe` | Python、MCP、pytest |
| `dsh-bash-terminal` | `3bf1aa8` | JavaScript、React |
| `English-Practice` | `f80ceee` | Go、TypeScript、Vue、Vite |
| `new-api` | `206e0fa` | Go、MCP |
| `network-insight-dashboard` | `916df55` | JavaScript、Vue、Vite、ECharts、Next.js |
| `unlimited-package-user-care` | `e506a05` | TypeScript、Vue、Vite、ECharts |
| `znexus-dashboard-demo-v3` | `ed507a3` | Go、JavaScript |

发现器在默认扫描时跳过隐藏目录（如 `.codex`、`.opencode`、`.playwright`）、`.git`、`.local`、依赖、构建产物、缓存和符号链接目录；秘密文件和证书后缀在文件层再次排除。源文件读取前要求规范化路径仍在项目根内。

## 工具状态

| 工具 | 实测状态 |
| --- | --- |
| Windows | 可用（PowerShell） |
| Python | `3.14.7` |
| Git | `2.55.0.windows.3` |
| ripgrep | `15.2.0` |
| Node/npm | `v24.19.0` / `12.0.2` |
| Playwright CLI | `1.62.1`，仅记录存在，不自动启动源项目 |
| uv | 未找到 |
| Serena | 未找到；符号层使用真实 `DEGRADED/BLOCKED_ENV` fallback |
| FastAPI/uvicorn | 未安装；Gallery 使用标准库只读 HTTP 服务 |
| Python MCP SDK | 未安装；当前提供兼容 MCP JSON-RPC stdio 服务，官方 SDK 集成标为 `BLOCKED_ENV` |
| pytest | `9.1.1` |
| Codex CLI | `0.163.0` |
| OpenCode CLI | 命令存在，但版本检查因其用户日志文件权限返回 `EPERM`，未将其当作可用集成 |

## 边界与风险

1. 源项目原始 dirty 状态较多，验收必须保存索引前后 Git 状态快照，不能简单把 dirty 视为本次修改。
2. 普通非 Git 目录没有 HEAD；系统会返回 `git_head=null`，并在报告中标注来源边界。
3. Serena、官方 Python MCP SDK 和 FastAPI 当前不可用。主查询链路可运行，但 Serena 真实联通和官方 SDK 客户端验收不能冒充 PASS。
4. 真实 UI 页面只做静态发现；没有用户明确授权，不启动陌生项目，不自动截图。无截图资产显示 `screenshot_status=unavailable`。
5. 源目录内容规模可能变化。索引记录每个文件哈希、大小和修改时间；`atlas index --changed-only` 是重新核对后的增量入口。

