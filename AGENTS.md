# Shutu-Atlas 开发约束

- 仅修改 `D:\dev-projects\Shutu-Atlas`；`D:\dev-projects` 下其他项目是只读参考源。
- 不在源项目中运行构建、测试、迁移、安装、截图或写入 Serena 配置。
- 索引、截图、Serena 镜像和运行日志只能写入 `.local/`，该目录不提交 Git。
- 查询必须返回真实路径、行号、版本来源和 `verified/inferred/unverified` 状态；不能把关键词命中宣称成完整能力。
- MCP 只暴露只读查询；刷新索引必须由 CLI 主动执行。
- 默认只监听 `127.0.0.1`；任何用户级配置或 Skill 安装都必须先备份并明确确认。
- 运行测试：`python -m pytest -q`。

