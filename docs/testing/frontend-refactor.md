# 前端工作台重构与验收

日期：2026-10-03。范围为现有 Vue 前端的浅色视觉、导航和交互重构；后端接口、业务规则、数据库迁移和开发库数据保持原有契约。本轮不代表 M7/M8 验收，也没有提交、推送或发布。

## 页面与交互

- 新增独立登录页与工作台外壳：桌面侧栏可折叠，窄屏使用带焦点循环和 Escape 关闭的导航抽屉。只提供浅色主题。
- 页面按路由拆分为工作总览、事故查询、地图与交叉口、风险画像、治理任务、统计报表、数据导入与质量、账户管理及个人账户。使用 hash 路由，无需新增后端静态回退配置。
- 总览读取现有统计接口，展示实际事故、已知伤亡、坐标覆盖、月度趋势和行政区分布。多个响应的 revision 一致后才应用结果；未记录月份保留缺口。
- 事故查询采用桌面表格、窄屏卡片和详情抽屉。人员/车辆分别分页；筛选条件发生变化后，旧游标不可继续加载，必须重新查询。
- 地图采用筛选工具栏、图例和结果侧栏；窄屏切换地图/结果，支持方向键、Home、End。容器变化后重新校准地图尺寸。
- 风险画像保留规则、周期、历史批次、缺失/过期提示和评分分项。选择画像可进入治理页并预填草稿标题；治理页保留课程模拟标记和原工作流。
- 导入页以批次进度和质量信息组织内容；管理员保留上传、发布等原能力，管理者只读批次摘要。
- 账户管理与个人账户分开。按路由卸载旧组件，避免用户目录未加载或密码表单跨页面残留。
- 统计页保留原有版本一致性、缺失值、权限、实际 CSV 下载和打印保护。A4 打印固定可用宽度，图表随纸张重排，治理统计表打印时采用单列，避免计数列被裁切。

导航和直接访问均检查角色；未登录直达会保留目标路由。登录令牌仍只存在于页面内存，刷新需重新登录，未引入 localStorage 持久会话。

## 验收环境与边界

浏览器使用本机 Chrome 无头模式，前端 `127.0.0.1:5176`，后端 `127.0.0.1:8006`；两者连接随机命名的独立合成 PostgreSQL 库。详情分页样本包含 21 条人员和 21 条车辆记录。所有截图与下载样本均为合成数据。

验收凭据只存放在 Git 忽略目录 `.m6-work/frontend-refactor/browser-private.json`，不进入此文档或证据目录。开发库仅通过 `REPEATABLE READ READ ONLY` 读取聚合快照，前后对比完全相同：revision 98、事故 85,546、人员 292,070、车辆 170,015、画像 95、治理任务与历史记录均为 0。

本轮没有再次执行整个后端测试套件，也没有通过界面上传/发布真实数据、计算新画像或修改真实账户。开发工作区同时存在其他任务的后端和 `.gitignore` 改动，本轮保留这些改动，不计入前端交付。

## 已验证结果

| 项目 | 本轮结果 | 证据 |
| --- | --- | --- |
| Vue/TypeScript 类型检查 | `npm.cmd run check`，退出码 0 | [typecheck.log](../evidence/frontend-refactor/typecheck.log) |
| 生产资源构建 | `npm.cmd run build`，退出码 0 | [build.log](../evidence/frontend-refactor/build.log) |
| 路由生命周期回归 | 修复前 0/3，修复后 3/3 | [修复前](../evidence/frontend-refactor/lifecycle-before.json)、[修复后](../evidence/frontend-refactor/lifecycle-after.json) |
| 综合业务与角色验收 | 47/47 通过，API/pageerror/非预期控制台错误均为 0 | [browser-acceptance.json](../evidence/frontend-refactor/browser-acceptance.json) |
| 真实会话退出与失效 | 5/5 通过；第二会话退出后，第一会话实际收到 401，跳登录并保留目标 | [session-acceptance.json](../evidence/frontend-refactor/session-acceptance.json) |
| 桌面/390px 页面检查 | 17 个业务视口均无整页横向溢出，pageerror 0 | [responsive-render.json](../evidence/frontend-refactor/responsive-render.json) |
| 统计、打印、真实下载 | 20/20 通过；实际 PDF 5 页逐页查看 | [statistics-acceptance.json](../evidence/frontend-refactor/statistics-acceptance.json)、[PDF](../evidence/frontend-refactor/normal-print.pdf) |
| 开发库只读前后对比 | 所有被检查字段相同 | [development-comparison.json](../evidence/frontend-refactor/development-comparison.json) |

统计验收涵盖未形成有效报表、混合 revision、加载中、查询失败、空/倒序日期、恢复前必须成功重查、正常打印、图表恢复、A4 图表与表格宽度，以及两类 CSV 的 `download` 事件、文件名、失败状态、`saveAs`、BOM、日期/revision 和内容解析。1 月合成样本预期为事故 3、已知受伤 4、已知死亡 1。

综合验收覆盖 ADMIN/MANAGER/VIEWER 路由矩阵与直接访问拒绝、刷新重登、游标与筛选绑定、人员/车辆明细真实第二页、VIEWER 隐藏年龄/性别、管理者导入只读、地图缩放后的实际范围请求、窄屏地图键盘切换、移动导航焦点循环与 Escape 恢复、账户密码状态清除及治理预填。合成库只实际新建 1 个草稿，返回 201；最终综合复测复用该证据，没有重复创建，见 [governance-create-evidence.json](../evidence/frontend-refactor/governance-create-evidence.json)。

初轮失败没有抹除：统计第 1 轮的尺寸断言在侧栏动画中途执行，改为等待打印前尺寸后通过；随后 PDF 视觉检查发现并修复 A4 图表裁切和双列表格计数列被裁切。早期截图使用固定等待导致懒加载尚未就绪，最终改为等待目标路由与具体内容；准备合成数据时曾触发成功风险快照不可变约束，随后保留原快照，不再补写成功批次。各轮原始结果保留在本机忽略目录 `.m6-work/frontend-refactor/`。

综合第 1/2 轮的失败来自脚本的 URL 编码、控件名称、错误事故选择、响应式表格可见性和异步等待假设；均保留在 [initial-runs](../evidence/frontend-refactor/initial-runs)。恢复任务后第 3 轮遇到已停止的本机服务，未发出业务请求。重新启动数据库并等待 PostgreSQL 崩溃恢复完成后，第 4 轮 47/47 通过。

当前构建仍提示统计页约 524 KB 的未压缩资源块（gzip 约 175 KB）；图表已按需注册，页面按路由懒加载。此提示不阻止构建。地图底图依赖 OpenStreetMap 网络；浏览器业务验收可阻断瓦片并独立验证业务接口，视觉截图未模拟底图；早期截图实际加载成功，恢复环境后的部分瓦片未加载，业务点和覆盖查询正常。带底图的实测预览见[地图截图](../evidence/frontend-refactor/screenshots/map-basemap-loaded.png)。

## 复现

正常使用继续沿用仓库已有入口，分别运行 `scripts/dev.ps1 -Action Backend`、`Frontend`、`Worker`，访问 `http://127.0.0.1:5173`。

本轮合成验收从仓库根目录执行；已有本轮私有配置时复用，准备脚本拒绝覆盖：

```powershell
.\.venv\Scripts\python.exe -X utf8 frontend/tests/prepare_acceptance.py
.\.venv\Scripts\python.exe -X utf8 frontend/tests/start_acceptance.py
node frontend/tests/route_lifecycle.cjs .m6-work/frontend-refactor/browser-private.json .m6-work/frontend-refactor/lifecycle-new
node frontend/tests/refactor.acceptance.cjs .m6-work/frontend-refactor/browser-private.json .m6-work/frontend-refactor/browser-new
node frontend/tests/session_transitions.cjs .m6-work/frontend-refactor/browser-private.json .m6-work/frontend-refactor/session-new
node frontend/tests/statistics.acceptance.cjs .m6-work/frontend-refactor/browser-private.json .m6-work/frontend-refactor/statistics-new
node frontend/tests/render_preview.cjs .m6-work/frontend-refactor/browser-private.json .m6-work/frontend-refactor/preview-new
```

同一验收库的浏览器脚本顺序执行，不并发运行。服务进程 PID 写在本机忽略目录的 `processes.json`，停止前应核对命令行及端口归属。

## 预览

[桌面总览](../evidence/frontend-refactor/screenshots/overview-desktop.png) · [390px 总览](../evidence/frontend-refactor/screenshots/overview-mobile.png) · [登录](../evidence/frontend-refactor/screenshots/login-desktop.png) · [地图](../evidence/frontend-refactor/screenshots/map-desktop.png) · [治理](../evidence/frontend-refactor/screenshots/governance-desktop.png) · [统计](../evidence/frontend-refactor/screenshots/statistics-desktop.png)
