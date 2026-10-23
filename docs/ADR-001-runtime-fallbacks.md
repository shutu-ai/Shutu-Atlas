# ADR-001：缺失可选工具时的真实降级

状态：Accepted（2026-10-23）

## 决策

核心索引只依赖 Python 标准库、SQLite FTS5 和本机 `rg`。Serena、FastAPI、官方 MCP Python SDK 和 Playwright 不是基础查询的前置依赖。缺失时保留功能边界并返回结构化状态：静态符号为 `DEGRADED`，Serena 健康为 `BLOCKED_ENV`，官方 SDK 为 `BLOCKED_ENV`，截图未采集为 `unavailable`。

## 原因

M0 发现这些工具在本机不可用；伪造“已集成”会违反真实证据要求。标准库实现让扫描、索引、只读 Gallery 和 MCP wire protocol 仍能测试，同时将需要额外环境的验收项显式留痕。

## 后果

当前可完成 M0/M1、静态符号 fallback、M3 静态 Gallery 和 MCP 协议边界；Serena 真实联通、官方 SDK 客户端和 Playwright 真实截图只能在用户提供/批准环境后升级为 PASS。

