# Gallery UI QA

## Flow

`http://127.0.0.1:8765/` → Gallery 首屏 → 输入/选择项目 → 搜索 UI 或代码 → 打开资产详情。

## Evidence

- 设计概念（frontend-app-builder/imagegen preview）：`C:\Users\swx1536744\.codex\generated_images\01a16837-2a74-7f72-9037-50fc1afdb418\exec-7536da8e-9be4-4c20-8a8c-77533d721fa2.png`，已用 `view_image` 检查。
- 实现截图：`.local/qa/gallery-desktop.png`（1440×900）与 `.local/qa/gallery-mobile.png`（390×844），由 `npx playwright screenshot` 在本地 Gallery 上生成。
- Browser/IAB 在本环境不可用；Playwright Chromium 在沙箱内首次 `EPERM`，获批后对本地地址截图成功。
- `/api/health` 返回 `ok`、3 个已索引项目；`/api/ui?q=ECharts` 返回 2 个真实资产；路径穿越请求返回 `unavailable`/拒绝，不读取任意文件。
- `node --check web/app.js` 通过。Playwright Test runner 不在本机可用的 CLI 包中，因此 DOM 点击交互未宣称 PASS；API 查询和静态渲染截图已验证。

## Mismatch ledger

| 比较点 | 概念参考 | 实现证据 | 处理 |
| --- | --- | --- | --- |
| 深色背景与蓝色强调 | 深蓝、蓝色主操作 | 桌面/移动截图 | 保持；CSS tokens 对齐 |
| 资产卡片密度 | 多卡片图集 | 桌面截图显示 3 列卡片 | 保持；无截图使用明确占位 |
| 源码定位 | 详情面板显示源路径/行范围 | API detail 与卡片路径 | 保持；由只读 API 提供 |
| 筛选/搜索 | 搜索框与项目下拉 | 首屏 DOM/截图 + API 查询 | 搜索按钮接入 `/api/ui`/`/api/search` |
| 响应式 | 桌面图集 | 390×844 移动截图 | 卡片单列、控件换行；未发现溢出 |
| 真实截图状态 | 有图/无图区分 | 所有当前真实资产 `unavailable` | 不合成图片；导入命令留作授权路径 |

