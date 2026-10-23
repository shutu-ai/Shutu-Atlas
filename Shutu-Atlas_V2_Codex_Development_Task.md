# Shutu-Atlas V2 — 跨项目代码与 UI 资产参考库：Codex 开发任务

> **执行角色**：你是本项目的技术负责人、实施工程师和验收责任人。请按本文件直接开始实施，而不仅输出方案。
>
> **项目名称**：**Shutu-Atlas**（术图·代码图鉴）  
> **仓库 / 项目目录**：`D:\dev-projects\Shutu-Atlas`  
> **扫描源目录**：`D:\dev-projects`（已有项目**只读**）  
> **目标版本**：`v0.2.0`（V2 能力完整可用）  
> **主要用户**：Codex、OpenCode、其他支持 MCP / Agent Skills 的 Agent，以及本地浏览器用户  
> **原则**：本地优先、真实证据、低 Token 开销、零源项目改写、增量更新、按需加载、不重复发明检索轮子。

---

## 0. 启动指令（Codex 必须先读）

请在 Windows 本机 `D:\dev-projects` 内创建独立项目 `Shutu-Atlas`，实施一个可实际运行的**跨项目代码资产与 UI 参考系统**。系统要让 Codex 和其他 Agent 在开发新项目时，通过一个只读 MCP 和跨 Agent Skill，发现旧项目里已经存在的功能、类/函数、代码调用位置、UI 页面/组件、图表和视觉样式，得到带证据的可复用方案。

**本次交付以 V2 为目标，不以“只完成 V1”结案**：必须包含跨项目索引、ripgrep + SQLite 检索、Serena 符号级集成、UI Gallery、本地只读 MCP、共享 Agent Skill、增量索引、真实项目验收。可以分里程碑提交，但最终需达到第 13 节验收条件。

**最高优先级限制**：

1. `D:\dev-projects` 下的原有项目一律作为**外部只读参考源**；不可修改、格式化、清理、切换分支、安装依赖到源项目、运行其迁移/构建/测试脚本、自动推送 Git。不可往源项目写入 `.serena/`、`.agent/`、配置、日志、索引、截图或缓存。
2. 只可在 `D:\dev-projects\Shutu-Atlas` 项目中创建和修改产品代码、测试夹具与受控索引数据。运行时缓存必须位于本项目忽略目录或明确配置的外置缓存目录。
3. **先真实盘点后实现**：扫描已存在的项目、框架、前端资源与工具，记录事实；不得假造源码路径、功能、截图、验收结果。
4. 对用户级 `~/.codex/config.toml`、OpenCode 设置、用户级 Skill 目录，仅生成安装脚本和合并建议；执行前备份并经过明确确认，不覆盖已有设置。尤其注意 MCP server 名称冲突。
5. 默认无外部模型 API、无上传、无遥测、无对外监听、无后台常驻要求；可选语义向量模型应支持本地运行，但不是系统基础查询的前置依赖。
6. 若 Serena 或可选 Playwright/Embedding 环境暂时不可用，必须实现清晰的降级路径及状态报告；**禁止用模拟结果冒充真实集成已通过**。
7. 不因安全过度工程化：不实现登录、RBAC、多租户、审批流、工作流引擎、多 Agent 调度或图数据库。但读取路径验证、排除敏感内容、源项目只读是必须兑现的边界。
8. 遇到一般工程实现分歧可做专业判断并记录 ADR，不要反复提问；只有涉及修改用户现有项目或全局配置时才需授权。

## 1. 产品目标与使用场景

用户已有多个独立代码项目，集中于 `D:\dev-projects`。需要一个跨项目的**参考库**，而不是把所有代码塞进 LLM 上下文，或将它们合并为单一仓库。

必须支持以下自然语言需求，并返回**真实定位和复用建议**：

- “以前哪个项目实现过异步任务取消、持久化与重启恢复？”
- “寻找 Streamable HTTP MCP、stdio MCP、任务进度/状态查询的实现。”
- “我要做一个面向高层的深蓝色 Dashboard，给我可参考的页面截图、组件、样式和对应源码。”
- “查找 Vue/ECharts 中 KPI 卡片、趋势图、筛选器、表格布局的成熟实现。”
- “对比两个候选实现，说明技术栈、依赖、API 入口、测试位置、适配成本和风险。”
- “在**新项目**中实现功能，但不要动老项目。”

输出不仅要“搜索命中”，还应为候选结果提供：`project_id`、仓库路径、`relative_path`、符号名/行范围、文件类型、说明、Git HEAD、工作树是否有未提交修改、证据片段、依赖、可复用类型、可信度标签、更新时间与可打开的本地 UI 资产链接（如有）。

“发现能力”与“复用能力”应分离。索引不能因为函数名包含 `recover` 就宣称实现了完整的 crash recovery；需显示 `verified / inferred / unverified` 及具体证据。

## 2. 范围界定

### V2 必须交付

1. **项目发现与资产目录**：自动发现多个独立 Git 或源码目录，解析语言、框架、构建/测试特征与 README；用户可将项目排除或标记；对嵌套仓库、Git worktree、Windows junction 做正确处理。
2. **精确搜索**：ripgrep 跨项目搜索、SQLite FTS5 全文索引、文件/项目/语言过滤、行号和代码片段、高亮、结果分页/上限、中文能力同义词查询。
3. **符号搜索**：Serena 按需分析选定项目，支持函数/类/符号定位、引用查询及源码证据；Serena 不可用时明确返回 `DEGRADED` 并退化到受支持语言的静态符号信息或精确文本搜索。
4. **功能资产索引**：识别候选能力、记录来源与证据；允许在 Hub 中人工确认/维护能力描述（不修改原始仓库）；支持功能与源码映射。
5. **UI Gallery**：发现现有 HTML/Vue/React 等 UI 页面、组件、CSS、颜色/字体/图表资产；支持真实截图导入，许可后 Playwright 对可启动页面截图；浏览器里预览、搜索、过滤并跳转对应源码。
6. **只读 MCP Server**：默认本地 stdio，工具仅提供搜索/读取/比较/推荐；不提供源代码修改、Git 写入、命令执行、触发构建、自动启动第三方项目、索引写入工具。
7. **跨 Agent Skill**：`local-project-reuse`，面向 Codex、OpenCode 和兼容 Agent Skills 的客户端，说明检索—核验—适配—实施流程；提供真实集成步骤与健康检查。
8. **增量更新**：Git HEAD/dirty 状态、文件哈希及版本记录，增删改感知；仅更新变更项目/文件的索引；手动更新和可选定期任务，默认不常驻轮询。
9. **本地 CLI、安装和测试**：Windows PowerShell 一键安装/诊断/升级入口、配置示例、测试夹具、运行报告、验收文档。

### 本版不做

- 全局扫描后将全部源码永久拼到提示词中。
- 强制依赖云端 LLM、远程 RAG、向量数据库或云上传。
- 自动提取旧项目代码并**直接改写/复制到新项目**的 MCP 工具；新项目实现仍由 Codex 在其明确可写的工作目录内执行。
- 完整知识图谱、Neo4j、多 Agent 自动协商/调度、账号体系、RBAC、审批后台。
- 默认运行所有旧项目的开发服务器，或对所有页面自动截图。
- 为了测评指标而构造虚假“已实现能力”或虚构项目。

## 3. 推荐技术路线（适度允许调整，但必须给理由）

| 层 | 默认选型 | 理由/约束 |
| --- | --- | --- |
| 主程序 | Python 3.11+，类型标注，`pyproject.toml` | Windows 友好，CLI/扫描/MCP 共用逻辑 |
| 元数据和搜索 | SQLite（FTS5）+ ripgrep（`rg`） | 无需独立 DB 服务；既有词法精确匹配又有索引召回 |
| Git 元数据 | Git CLI，只读命令 | 识别 HEAD/dirty；不 `checkout`、不 `reset` |
| 符号引擎 | **Serena 适配器**；静态符号/文本检索作为 fallback | 复用成熟语言服务器，不重新实现所有语言解析器 |
| MCP | 官方 Python MCP SDK，与所锁定版本一致 | stdio 默认；工具是只读接口 |
| Web API | Python 轻量服务（FastAPI 可选） | 只监听 `127.0.0.1`；只读浏览 UI 资产 |
| UI Gallery | Vue 3 + TypeScript + Vite（可复用现有风格） | 现代本地搜索/图集/详情体验；控制依赖规模 |
| 截图 | Playwright，仅“用户批准的目标”启用 | 不默认运行陌生项目；图片要有真实来源 |
| 语义增强 | 可插拔本地 Embedding（可选 Qwen3-Embedding-0.6B / Ollama / 本地模型） | 只做可选的重排或召回；离线不可用不影响 V2 主功能 |

实现时先检查本机工具是否存在、版本及 SDK API。**不要把旧版 FastMCP 示例与已安装的新版 MCP Python SDK API 混用**；锁版本并按实际 API 编码。使用 Serena 官方项目/客户端文档核验具体命令和多项目限制，不假设它天然支持多项目并发共享同一上下文。

所有环境路径集中在 `atlas.toml` / `atlas.example.toml`；不得把开发者用户名或机器路径硬编码到产品逻辑。

## 4. 仓库目标结构

```text
D:\dev-projects\
├── Shutu-Atlas\                  # 本项目，可写
│   ├── README.md
│   ├── AGENTS.md
│   ├── pyproject.toml
│   ├── atlas.example.toml
│   ├── src/shutu_atlas/
│   │   ├── discovery/           # 项目发现/框架检测
│   │   ├── index/               # SQLite/FTS/增量索引
│   │   ├── search/              # 排序、检索、证据
│   │   ├── symbols/             # Serena 与 fallback 适配器
│   │   ├── ui_assets/           # UI 静态识别/截图管理
│   │   ├── mcp_server/          # 只读 MCP
│   │   ├── api/                 # Gallery 本地只读 API
│   │   ├── cli.py
│   │   └── config.py
│   ├── web/                      # Vue3 + TS UI Gallery
│   ├── skills/local-project-reuse/SKILL.md
│   ├── scripts/                  # PowerShell 安装、诊断、用户配置示例
│   ├── tests/                    # 测试夹具与 E2E
│   ├── docs/                     # ADR、架构、验收、操作手册
│   └── .local/                   # 全部索引/截图/Serena 镜像/运行日志；Git ignored
├── <existing-project-A>/        # 禁止修改
├── <existing-project-B>/        # 禁止修改
└── <existing-project-N>/        # 禁止修改
```

允许小幅修改命名与拆分，但必须做到：**源项目与参考库运行数据彻底分离**；DB/截图/缓存/克隆镜像不进入 Git；仓库中只提交可复现的源代码、文档、样例、测试与必要锁文件。

## 5. 项目发现、索引与搜索

### 5.1 发现规则

- 默认扫描配置指定的 `roots=["D:\\dev-projects"]` 下项目，跳过 Shutu-Atlas 自身 `.local`、依赖目录、构建产物和已排除目录。
- 支持 `include_projects` 与 `exclude_projects`，不以项目名模糊匹配作为唯一身份；用稳定的 `project_id`，原始路径是可变属性。
- 支持多语言项目和嵌套仓库；界定独立 Git 根。对于 junction/symlink，默认不跟随越界路径，防止重复索引与路径穿越。
- 读取 `.gitignore` 时不得因此漏掉用户明确允许的 UI 截图；用户自定义排除规则优先；敏感文件排除优先级最高。
- 保存 repo 的 commit、branch（只读取）、dirty 状态及 `indexed_at`，对未提交的本地文件明确标示 `working_tree`，不能把内容错误归属到 HEAD。

### 5.2 敏感信息与资源控制

- 默认排除：`.git/`、`.env*`、密钥/证书、token/credentials 文件、`node_modules/`、`.venv/`、`dist/`、`build/`、覆盖率、缓存、临时文件、大型二进制与常见日志；文件大小上限、总索引预算可配置。
- 读取原文件前验证规范化绝对路径确在允许的源项目根内；禁止 `..`、符号链接/重解析点逃逸；MCP `get_source` 只能通过已索引且获准的 `project_id + file_id` 访问，不直接接受任意绝对路径。
- 返回给 Agent 的内容按默认配置限制 `max_results`、`max_snippet_lines`、`max_chars` 和超时；输出中不包含已排除秘密文件内容。
- 不运行源项目脚本来“推断能力”；静态扫描不会执行目标仓库代码。

### 5.3 检索优先级

采用**低成本、可解释的多阶段检索**：

1. `project / language / ui_type / framework` 过滤候选集；
2. 能力别名与关键词归一化（中文/英文，如“断点续传/resume”、“异步任务/async job”）；
3. ripgrep 直接精确搜索 + FTS5 BM25 返回候选文件/符号；
4. Serena 对 Top N 相关项目做符号定位/引用分析与交叉验证；
5. （可选）本地 Embedding 召回/重排；模型未安装时显式跳过；
6. 只返回经过定位的 Top K 来源，每项带解释和证据；禁止无依据编造 API/依赖。

明确标记候选的匹配原因：`exact_symbol`、`fts`、`regex`、`capability_tag`、`semantic`、`serena_reference`。不要把字面搜索等同“功能已验证”。

建议建立表：`projects`、`files`、`symbols`、`capabilities`、`capability_evidence`、`ui_assets`、`ui_source_links`、`index_runs`、`index_errors`。通过 FTS5 索引必要的可检索文本，避免无界重复存储源码全文；有清晰 schema migration 和 DB 自恢复/重建策略。

### 5.4 CLI 接口（需真实实现）

```powershell
atlas doctor
atlas scan --root "D:\dev-projects" --dry-run
atlas index --root "D:\dev-projects"
atlas index --changed-only
atlas list-projects
atlas search-code "task recovery" --limit 10
atlas find-capability "任务重启恢复"
atlas find-symbol "submit_sm" --project <project-id>
atlas find-ui "dark KPI dashboard" --limit 12
atlas gallery serve --host 127.0.0.1 --port 8765
atlas mcp serve --transport stdio
atlas status
```

上面是**预期用户接口**，Codex 可以按 Python CLI 框架调整选项命名，但 README 必须提供准确且实测通过的命令。`scan --dry-run` 不得创建文件到源项目；`index` 只可写入本项目 `.local`。

## 6. Serena 集成（V2 硬性要求）

Serena 是**符号检索适配器**，不是整个项目的单一索引数据库，更不是直接对所有旧项目运行的全局、可写 Agent。

### 6.1 必须解决的实际约束

1. Serena 以**一个激活项目**为工作上下文；不能假设共享同一 Serena 实例就能安全并发处理不同仓库。
2. Serena 初始配置/索引可能在项目附近生成 `.serena/` 或缓存；直接在源仓库激活不符合源项目零改写目标。
3. Serena 可提供读写工具，单靠对 Agent 说“只读”不是系统约束。不能把可写 Serena 原样暴露给使用参考库的 Agent。

### 6.2 推荐实现

- **适配器接口**：`SymbolProvider`（如 `find_symbol`、`get_references`、`health`）；`SerenaProvider` 和 `FallbackProvider` 可替换。
- **隔离工作镜像**：对**选中的候选项目按需**建立受控、只读来源的轻量工作镜像于 `Shutu-Atlas/.local/serena-workspaces/<project-id>/<fingerprint>/`，并保存镜像相对路径 → 源文件相对路径映射。镜像必须遵守敏感文件排除、大小预算和更新指纹；不要全量无差别复制大仓库。
- Serena 的配置、语言服务器生成物与索引只允许落在镜像/Hub 缓存，不得落到原项目；可按官方配置设置 `read_only` 并关闭不必要的写入/命令执行能力。必要时以文件系统权限加固镜像读取行为；**安全边界主要依赖源文件不在工作目录且不暴露 Serena 写工具**。
- 推荐一个项目一个短期工作进程/连接或串行生命周期；并发时彼此隔离，不串项目上下文。不把动态激活的单例作为多个 Agent 的全局共享服务。
- 仅对指定文件/项目启动语言服务，保留超时、取消、进程回收、内存/磁盘缓存上限；不允许 indexer 长时间阻塞基础搜索。
- Serena 缺失、语言不支持、镜像预算超限、符号服务异常时，返回确定的错误类型与 fallback 结果，不能返回空列表却标记成功。
- 对镜像中的符号结果映射回原始项目路径和行范围，并验证源文件当前指纹；若索引过期则显示 `stale` 或要求刷新。

### 6.3 验收测试

至少用真实可控的 Python 项目 + 一种 JS/TS 或 Go 夹具，验证：类/函数查找、引用查找、路径映射、两个仓库切换、两个请求并发、进程错误恢复、源项目没有新增 `.serena` 文件或其他变化。必须含真实 Serena 调用的**integration test**；如果开发环境没有 Serena，不能声称该项 PASS。

## 7. UI Gallery（V2 硬性要求）

UI Gallery 的首要价值是建立“**真实页面效果 ↔ 真实代码实现**”的映射，而非仅从文件名猜测 UI 风格。

### 7.1 索引对象

- 页面：HTML、Vue SFC、React/TSX、静态 Dashboard 等；
- 组件：KPI 卡片、图表容器、筛选面板、表格、导航、状态条、地图/流程图等；
- 风格：主题色、背景、字体、CSS variables/design tokens、grid 布局、深浅色、响应式线索；
- 图表：ECharts / Chart.js / Recharts / ApexCharts 等库的明确引用或组件调用；
- 截图：用户主动导入的原始截图，或 Playwright 在**获授权可访问页面**上生成的真实截图。

### 7.2 截图采集边界

- 默认**只做静态发现**，不自动 `npm install`、不 `npm run dev`、不执行源项目脚本。
- 可以导入已有截图，并人工指定项目/页面/源码链接；导入后拷贝到 Hub 内的专有 gallery assets 路径（不要修改源截图）。
- Playwright 采集须使用白名单 URL（优先 `http://127.0.0.1:<port>`）及用户指定的已有服务；如需启动旧项目，必须另行得到明确许可，并确保所有运行写入及缓存不在源项目。
- 不加载未知的外部网页、不执行任意 shell 参数、不假设截图页面可直接运行；采集失败需保留错误和 `screenshot_status=unavailable`。
- 元数据必须指向真实源文件；若匹配是推断，标记 `inferred`。

### 7.3 浏览器界面

本地 `127.0.0.1` Gallery 最少实现：

- 项目选择、框架/语言/组件类型筛选、关键词搜索；
- 卡片式视觉缩略图（有真实截图才展示；无图使用**明确的无截图占位**）；
- 详情页：页面名称、截图、功能/组件、颜色与布局摘要、源码路径/行范围、Git 来源、可信度；
- 一键复制“引用该 UI 资产的 Agent 提示词”（包括资产 ID、源码定位、设计要求，但不直接大量复制源码）；
- 空状态/错误状态、深浅主题、桌面浏览器适配；
- UI API 严格只读；本地静态缩略图服务不可通过路径穿越读取任意磁盘文件。

UI Gallery 应具备清爽、专业的可视化效果。**不要用虚构业务数据或合成截图伪装源项目的真实 UI。** 如使用演示素材，必须标记 `DEMO` 且不进入真实资产搜索结果。

## 8. MCP Server：明确的只读接口

默认采用 stdio MCP。工具名建议固定为：

| MCP Tool | 输入 | 输出 |
| --- | --- | --- |
| `atlas_list_projects` | filter, limit | 已扫描的真实项目、栈、状态 |
| `atlas_find_capability` | query, project_filter, limit | 能力候选、证据、置信状态 |
| `atlas_search_code` | query, mode, filters, limit | 文件、行范围、片段、匹配原因 |
| `atlas_find_symbol` | name, project_id, kind | 符号定义、引用、Serena/fallback 状态 |
| `atlas_get_source` | project_id, file_id, start_line, end_line | 边界受限的源码片段和版本证据 |
| `atlas_find_ui` | query, filters, limit | UI 资产、图片/组件关联、截图状态 |
| `atlas_get_ui_detail` | asset_id | 截图索引、源码链接、风格摘要 |
| `atlas_suggest_reuse` | requirement, target_stack?, limit | **有出处**的候选对比、依赖与移植提示 |
| `atlas_health` | - | DB、rg、Serena、图库、最后索引的真实健康状态 |

规则：

- 所有工具的业务操作为只读；**不得**暴露写文件、Git 操作、命令执行、脚本执行、索引重建、启动项目、复制代码到目标项目的 MCP 能力。
- MCP 的只读业务查询可以在 Hub 内写入非业务性临时日志/语言服务缓存，但不能修改索引内容或源项目；索引刷新交给用户主动运行的 CLI。
- 必须遵守限制参数上限、防止绝对路径访问、任意 SQL、命令注入与越界文件读取。
- 结果结构化（JSON schema），带 `status`、`source`、`evidence`、`stale`、`warnings`；错误不伪装为“找到 0 个”。
- 支持两个 MCP 客户端同时查询 SQLite：使用 DB 读连接、事务/锁处理，避免一个索引写任务导致 Agent 永久卡住。
- stdout 只输出 MCP 协议，日志写 stderr 或 Hub 日志文件。
- 为 Codex 和 OpenCode 分别提供**经实际版本核验**的配置样例；先检测已有同名 MCP 服务，避免和现有 ssh-manager 等配置冲突。
- 本版无需公网服务；如果以后引入 Streamable HTTP，必须另行增加监听/认证要求，不能默认开放 `0.0.0.0`。

## 9. `local-project-reuse` 跨 Agent Skill

放置源文件 `skills/local-project-reuse/SKILL.md`，按 Agent Skills 通用格式提供 `name`、`description` 与内容。Codex 用户级安装目标优先为：

```text
%USERPROFILE%\.agents\skills\local-project-reuse\SKILL.md
```

本项目只提供带 `--dry-run`、备份和安装检查的脚本，不自动修改用户级文件。

Skill 应规定以下工作流：

1. 收到新项目实现/复用功能/UI 参考请求时，先 `atlas_health` 与 `atlas_find_capability` / `atlas_find_ui`，按需执行代码或符号搜索；不要把所有旧仓库加入上下文。
2. 提供最多 3 个最相关候选，列项目、文件/行号、实际能力、依赖和成熟度；必要时进一步 `atlas_get_source` 核查。
3. 区分 `reuse_direct`（可以独立引入）、`adapt`（要改造）、`visual_reference`（仅借鉴外观）、`not_recommended`（不适合）和 `unknown`。
4. 优先用目标项目现有技术栈适配；不得未经确认引入大量依赖、复制含许可证限制/敏感配置的源码。
5. **修改和验证只在用户选定的新项目中进行**；参考源项目不允许写入，MCP 不负责修改目标代码。
6. 结束时报告“参考了哪些资产 → 实际复用了什么 → 对新项目改动了什么 → 测试结果”。
7. MCP 不可用时说明降级方式；不凭旧记忆臆造项目内容。

请验证：在一个全新 Git 项目中通过 Codex 显式调用 Skill（如 `$local-project-reuse`），再验证描述足够清晰时可被正常发现；OpenCode 需要按其实际版本的 Skill 加载方式验证，不能只复制目录便宣称兼容。

## 10. 索引刷新、运行稳定性和性能

- 初始扫描：输出明确的发现/排除项目清单及统计，不执行源项目代码。
- 增量刷新：依据 repo/文件状态与哈希判断；新增、删除、重命名、修改、被排除文件变化均能更新；清理旧索引的孤儿记录。
- 索引原子性：用事务/临时表/按项目提交，单个项目失败不破坏其他项目索引；支持中断重试。
- 可观察性：`atlas status` 展示索引规模、最后扫描时间、成功/失败/降级计数、Serena 版本与真实可用性。
- 轻量默认：不在 Agent 每次调用时启动完整扫描；不在每次检索时重算全库 Embedding；不要求 GPU。
- 当可选本地 Embedding 存在时，只针对结构化能力描述、符号摘要和 UI 元数据做向量检索；模型版本、索引指纹和回退行为记录清楚。
- 给出实际测量的索引耗时、查询 P50/P95、DB/截图/镜像磁盘占用及系统资源；只报告实测值，不设拍脑袋的 SLA 门禁。

## 11. 分里程碑实施（每个阶段提交可追溯成果）

### M0 — 环境与真实仓库审计

- 只读检查 `D:\dev-projects` 的实际目录、项目与技术栈。
- 记录 Windows、Python、Git、ripgrep、uv、Node、Playwright、Serena、Codex/OpenCode 的存在与版本。
- 确认目录中的项目不能被改写；`git status` 基线只读采集，并记录无法通过 Git 检测的普通目录/未跟踪文件边界。
- 生成 `docs/00_Discovery_and_Constraints.md`，包括例外、工具缺失与风险。

**门禁**：无对原项目写入；输出真实发现记录。

### M1 — 跨项目资产目录与检索

- 建立 Python 包、配置系统、CLI、扫描、SQLite schema、FTS5、ripgrep、敏感文件过滤。
- 实现功能索引（证据分级）、查询解释、增量刷新、路径/行号定位。
- 对多个真实项目建立初始索引。

**门禁**：`scan/index/search/find-capability` 可用；真实查询给出可打开的证据。

### M2 — Serena 符号层

- 实现镜像映射、隔离的 Serena adapter、符号/引用查询、fallback、资源预算。
- 完成至少两个语言/项目夹具与并发隔离测试。

**门禁**：真实 Serena 联通与符号搜索通过；源仓库保持不变。

### M3 — UI Gallery

- UI 页面/组件/样式/图表静态识别；截图导入及带许可的 Playwright 采集；Vue Gallery 与只读 API。
- 实现“截图 ↔ UI 组件 ↔ 源码”对应关系和自然语言 UI 搜索。

**门禁**：至少一个**真实现有 UI 页面**与源码完成关联；浏览器能检索并查看；无图不得伪造图片。

### M4 — MCP、Skill 与完整验收

- 实现只读 MCP 全套工具、官方 SDK 客户端连接及工具调用测试、Codex/OpenCode 配置说明。
- 编写并安装验证 Agent Skill（安装前备份/确认）。
- 通过真实新项目的端到端复用场景验证。
- 补全 README、中文操作手册、架构图、ADR、验收报告与发布日志。

**门禁**：第 13 节所有必需能力闭环，才能声明 `V2 READY`。

## 12. 自动化与真实演示测试

建立仓库内 fixture，不使用或更改旧项目测试数据：

- `fixture-python`：定义/引用函数、包含可验证的异步任务能力片段与测试；
- `fixture-ts-vue`：KPI 卡片、图表、深色主题、前端页面、真实文件路径；
- `fixture-go` 或 `fixture-mcp`：选用一种跨栈能力；
- `fixture-secrets`：`.env`、软链接/路径遍历、安全排除测试；
- `fixture-multi-repo`：两个项目定义同名 symbol，验证隔离；
- 增删改和文件重命名、Git dirty、并发读/索引刷新、Serena 不可用 fallback。

**真实演示测试**（以扫描到的项目事实为准）：

1. 查找一个已有后端功能（如“异步导出/任务状态/重启恢复”），返回真实代码片段与文件定位；
2. 查找一个 MCP / Agent 功能，返回项目间候选对比；
3. 查找 Dashboard KPI/图表/主题 UI，并在 Gallery 打开真实页面截图或明确的“未采集截图”卡片；
4. 新建一个**临时测试新项目**，Agent 通过只读 MCP 和 Skill 查询候选，再在新项目中实现一个最小可运行的复用示例；
5. 验证所有既有 Git 源项目在前后未新增、删除、修改或改变 Git 状态；对非 Git 目录按抽样哈希/变动时间校验，并诚实说明检测范围；
6. 两个独立 Agent/MCP 客户端并发查询，不串仓库、不越权访问、不写源项目。

测试报告区分 `PASS`、`FAIL`、`SKIPPED`、`BLOCKED_ENV`、`UNVERIFIED`，禁止把模拟器通过写成“真实 Codex/Serena/Playwright 全链路通过”。

## 13. 最终验收标准（必须逐条提供证据）

| ID | 必需门禁 | 判断要求 |
| --- | --- | --- |
| A01 | 旧项目源代码零改写 | 扫描/索引/Serena/UI/MCP 前后比较有证据，无 `.serena` 写入源仓库 |
| A02 | 多项目发现 | 至少覆盖 3 个真实项目（若本机不足，明确实际数量）及 2 种以上技术栈 |
| A03 | 真实全文与能力查询 | 可定位精确路径、行范围、Git 来源；能力推断有证据且有分级 |
| A04 | 增量更新 | 修改测试夹具文件只更新对应索引；删改重命名正确，失败可恢复 |
| A05 | Serena 真实集成 | 符号定义、引用、路径映射、项目隔离、fallback；不能仅 Mock |
| A06 | UI Gallery | 可检索、预览真实截图/占位、打开源码映射、复制参考提示词 |
| A07 | MCP 只读 | 正式 MCP client 完整连接与查询；无写工具，限制路径有效 |
| A08 | Skill 复用 | Codex 至少一次真实调用通过；OpenCode 实测或明确 `UNVERIFIED` |
| A09 | 安全/数据边界 | 密钥排除、路径穿越、符号链接越界、查询上限、源项目不执行脚本测试通过 |
| A10 | 文档与可运维性 | 完整 README、Windows 安装、配置样例、`doctor/status`、测试报告 |

`V2 READY` 仅在 A01–A07、A09–A10 通过，且 A08 的 Codex 真机测试通过后宣告；OpenCode 如果没有可用环境，可以保留 `UNVERIFIED` 并不能声称它已实测。若真实项目暂不包含可截图运行的 UI，Gallery 功能可用但真实截图采集列为未验证，必须明确记录，不能虚报完成。

## 14. 代码规范、提交与交付物

- 代码：清晰模块边界、类型提示、测试覆盖关键路径；避免与外部工具的非必要深度耦合。
- 测试：Python `pytest`，前端必要的单元/E2E；通过启动参数控制外部真实集成测试。
- 文档：**中文优先**、示例命令可复制；所有架构断言可从源码或实测推导。
- Git：仅在 `Shutu-Atlas` 本项目中建立和提交代码；分里程碑合理提交。除非用户明确要求，不创建 GitHub 远端/不推送。
- 要产出：
  - `README.md`（快速开始、使用场景、MCP/Skill/Gallery）
  - `AGENTS.md`（本仓库开发约束）
  - `atlas.example.toml`（Windows 默认配置及排除规则）
  - `docs/Architecture.md` 与关键 ADR
  - `docs/00_Discovery_and_Constraints.md`（真实项目盘点）
  - `docs/Acceptance_V2.md`（逐条证据、测试命令、结果）
  - `docs/Operations_Windows.md`（安装、更新、故障排查、备份迁移）
  - `docs/MCP_Skill_Integration.md`（Codex/OpenCode 配置与实测记录）
  - `skills/local-project-reuse/SKILL.md`
  - `scripts/install.ps1`、`scripts/doctor.ps1`、`scripts/install-skill.ps1` 或等价脚本
  - `.gitignore`、依赖锁文件、可复现测试和版本说明。

## 15. 最终回复格式（Codex 执行完成后）

只报告**已经完成**的工作和真实运行结果，至少包括：

```text
PROJECT=Shutu-Atlas
PROJECT_PATH=D:\dev-projects\Shutu-Atlas
SOURCE_ROOT=D:\dev-projects
VERSION=v0.2.0
SOURCE_PROJECTS_READ_ONLY=PASS/FAIL/UNVERIFIED
PROJECTS_DISCOVERED=<number>
FILES_INDEXED=<number>
CAPABILITIES_INDEXED=<number>
UI_ASSETS_INDEXED=<number>
SERENA_INTEGRATION=PASS/FAIL/BLOCKED_ENV
UI_GALLERY=PASS/FAIL/BLOCKED_ENV
MCP_STDIO=PASS/FAIL/BLOCKED_ENV
CODEX_SKILL_E2E=PASS/FAIL/BLOCKED_ENV
OPENCODE_SKILL_E2E=PASS/FAIL/UNVERIFIED
TESTS=<真实测试统计>
ACCEPTANCE=V2_READY / PARTIAL / BLOCKED
GIT_HEAD=<本项目真实提交>
```

随后给出：

1. 实际扫描到了哪些项目、找到哪几个**真实可复用**的能力/UI 资产；
2. 如何启动 Gallery、如何运行 CLI 搜索、如何安装 MCP 和 Skill（准确命令）；
3. 未解决风险与不影响主流程的降级项；
4. 本项目新增/修改文件清单（不要把源项目文件列为交付变更）。

**执行要求**：先完成 M0，并立即继续 M1–M4；在当前可用环境内尽可能实施、测试和形成可交付工程。没有授权就不修改用户全局环境，不能把“准备好了开发计划”当作完成开发任务。

---

## 参考资料（实现时确认当前版本与兼容性）

- OpenAI Codex Skills 与 MCP：<https://learn.chatgpt.com/docs/customization/overview>
- Codex MCP 连接说明：<https://learn.chatgpt.com/docs/extend/mcp>
- Serena 官方运行文档：<https://oraios.github.io/serena/02-usage/020_running.html>
- Serena Project Workflow：<https://oraios.github.io/serena/02-usage/040_workflow.html>
- Serena 安全说明：<https://oraios.github.io/serena/02-usage/070_security.html>
- 官方 MCP Python SDK：<https://py.sdk.modelcontextprotocol.io/>

> 设计提醒：Serena 的 `read_only` 设置会限制它的编辑操作，但它不等价于操作系统级只读沙箱。源项目隔离镜像和 MCP 工具白名单才是关键边界；相关细节以所安装 Serena/SDK 版本实测为准。
