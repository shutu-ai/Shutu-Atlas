---
name: local-project-reuse
description: 在新项目中复用本地旧项目的真实代码能力或 UI 参考。先通过 Shutu-Atlas 的只读 MCP 查询健康状态、能力、符号、源码和 UI 证据，再核验依赖与许可证，最后只在用户明确选定的新项目中实施和验证。
---

# Local Project Reuse

这个 Skill 适用于“找以前做过的功能”“找成熟 UI 参考”“比较两个候选实现”以及“在新项目里实现但不要动旧项目”的请求。

## 工作流

1. 先调用 `atlas_health`，确认索引时间、项目数量、ripgrep、Serena 和 Gallery 的真实状态。
2. 按需调用 `atlas_find_capability` 或 `atlas_find_ui`，不要把所有旧仓库加载进上下文；最多保留 3 个候选。
3. 用 `atlas_search_code` 或 `atlas_find_symbol` 精确定位文件、符号和行号。Serena 如果不可用，必须保留 `DEGRADED/BLOCKED_ENV` 状态，不把静态关键词命中当作 Serena 验证。
4. 对最相关候选调用 `atlas_get_source`；核验依赖、API 入口、测试位置、Git HEAD、工作树状态和敏感内容排除状态。
5. 将候选分为：
   - `reuse_direct`：边界清晰、依赖可接受，可独立引入；
   - `adapt`：能力真实但需要改造或迁移；
   - `visual_reference`：只借鉴布局/颜色/交互，不复制实现；
   - `not_recommended`：证据不足、依赖/许可证/风险不合适；
   - `unknown`：证据不足以判断。
6. 只在用户选定的新项目工作目录修改代码。参考仓库、Shutu-Atlas 的索引和 MCP 均不负责写入目标代码。
7. 结束时报告：参考了哪些资产 → 实际复用了什么 → 新项目改动了什么 → 测试结果；对 OpenCode 或 Serena 未实际运行的步骤标为 `UNVERIFIED` 或 `BLOCKED_ENV`。

## 典型查询

```text
atlas_health
atlas_find_capability(query="任务重启恢复", limit=3)
atlas_find_ui(query="深蓝 KPI dashboard", limit=3)
atlas_find_symbol(name="submit_sm", project_id="...")
atlas_get_source(project_id="...", file_id=123, start_line=40, end_line=80)
```

不要依据函数名推断完整功能；例如 `recover` 只代表字面线索，除非证据片段和测试共同支持，否则标记 `inferred`。

