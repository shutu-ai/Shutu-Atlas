# Windows 操作手册

## 安装

```powershell
cd D:\dev-projects\Shutu-Atlas
.\scripts\install.ps1
Copy-Item atlas.example.toml atlas.toml
notepad atlas.toml
atlas doctor
```

如需执行官方 SDK/Serena 集成测试，并已获准联网安装，可使用：

```powershell
.\scripts\install.ps1 -WithIntegrations
```

该开关只写项目内 `.venv`；直接依赖版本锁定在 `requirements-integrations.txt`。当前验收环境的 PyPI 连接返回 WinError 10013，因此未将阻塞伪装成通过。

脚本只在项目内创建 `.venv` 和 `atlas.toml`；不会修改用户 Codex/OpenCode 配置。运行 `scripts\install-skill.ps1` 默认只是 dry-run；用户明确确认后才使用 `-Install -DryRun:$false`，已有 Skill 会先备份。

## 更新与增量

```powershell
atlas scan --root D:\dev-projects --dry-run
atlas index --root D:\dev-projects
atlas index --changed-only
atlas confirm-capability --project <project-id> --name task_recovery --status verified --note "人工核对源码与测试证据"
atlas status
```

索引和截图位于 `.local`，可以整体备份；源项目不保存索引缓存。若数据库损坏，删除本项目 `.local\atlas.sqlite3*` 后重新运行 `atlas index`；这个删除动作只针对本项目受控缓存。

## 故障排查

- `Serena BLOCKED_ENV`：检查 `serena` 是否在 PATH；在此之前使用静态 fallback，不要在源项目直接激活 Serena。
- `mcp_sdk BLOCKED_ENV`：兼容 stdio 服务仍可用于协议测试；需要官方 SDK 证据时，在隔离环境安装并运行显式 integration test。
- 没有 UI 图片：这是安全默认值；用用户主动提供的真实截图执行 `atlas gallery import-screenshot --asset-id ... --path ...`。
- DB locked：等待正在运行的索引完成；查询连接是只读并带忙等待，不要删除正在写入的数据库。

