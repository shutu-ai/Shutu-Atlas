# Shutu-Atlas 架构

```text
D:\dev-projects (只读)
        │  discovery + git metadata + safe file reader
        ▼
  project/file inventory ──► SQLite + FTS5 ──► CLI / MCP / Gallery API
        │                           │
        ├─ static symbols           ├─ capability evidence
        ├─ UI asset metadata        └─ hashes + index runs
        ▼
  Hub-owned Serena mirror (按需、受限、可丢弃；不写源仓库)
```

## 数据层

`projects` 保存路径、稳定 `project_id`、Git HEAD/branch/dirty；`files` 保存相对路径、语言、大小、修改时间和 SHA-256；`symbols` 保存受支持语言的静态定义；`capabilities` 与 `capability_evidence` 将关键词线索映射回真实文件行；`ui_assets` 与 `ui_source_links` 保存 UI 文件、特征和截图状态；`fts_content` 是 SQLite FTS5 召回表，源码正文受大小上限约束。

索引按项目处理并在一个数据库事务中提交；单项目异常会写入 `index_errors`，不破坏其他已提交项目。变化判断使用哈希、大小和修改时间；删除文件会清理其符号、证据、UI 映射和 FTS 记录。

## 查询层

代码查询将中文/英文别名归一化，先查 FTS5，再用 `rg --fixed-strings` 返回真实行号和片段；结果携带 `match_reason`。能力查询使用可解释规则并标记 `verified/inferred`，不把名字命中当作完整实现。源码读取只接受索引生成的 `project_id + file_id`，并重新验证当前哈希。

Serena 是可替换符号 Provider，不是全库数据库。若存在 Serena，镜像管理器只复制通过敏感过滤且在预算内的文件；当前环境没有 Serena，所以真实输出为静态 fallback 和 `DEGRADED/BLOCKED_ENV`。

## 接口层

- CLI：扫描、索引、搜索、状态、诊断。
- MCP：newline JSON-RPC stdio，工具清单只有只读查询；没有命令执行、Git 写入、索引刷新或源代码写入工具。
- Gallery：标准库 `ThreadingHTTPServer`，只监听指定地址（默认 `127.0.0.1`），UI 通过只读 API 查询，并对截图路径做 `.local/gallery` 边界校验。

