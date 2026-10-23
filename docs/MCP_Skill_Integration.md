# MCP 与 Skill 集成

## MCP stdio

本项目提供兼容 MCP JSON-RPC 的只读 stdio 服务：

```powershell
atlas mcp serve --transport stdio
```

服务 stdout 只输出协议消息；日志和非法输入错误写 stderr。工具清单见 README 和 `src/shutu_atlas/mcp_server/server.py`。当前环境没有官方 Python MCP SDK，因此 `atlas_health` 报告 `mcp_sdk.available=false`；这不是官方 SDK 集成 PASS。

Codex/OpenCode 的配置应由用户按实际版本合并，不能自动覆盖已有同名服务器。示例（概念格式，执行前检查客户端版本）：

```json
{
  "mcpServers": {
    "shutu-atlas": {
      "command": "D:/dev-projects/Shutu-Atlas/.venv/Scripts/python.exe",
      "args": ["-m", "shutu_atlas.cli", "mcp", "serve", "--transport", "stdio"],
      "cwd": "D:/dev-projects/Shutu-Atlas"
    }
  }
}
```

不要把这个示例直接写入用户配置；先备份、查重并明确确认。项目脚本只负责检查和安装，不负责自动合并。

## Skill

源文件为 `skills/local-project-reuse/SKILL.md`。安全预览：

```powershell
.\scripts\install-skill.ps1
```

安装前确认后：

```powershell
.\scripts\install-skill.ps1 -Install -DryRun:$false
```

本次环境没有执行用户级安装，也没有声称 OpenCode 已实测加载；OpenCode 结果应保持 `UNVERIFIED`。

