# 面向 Vision Zero 的纽约交通碰撞风险识别与高危交叉口治理管理系统

个人数据库课程设计。M0已完成；M1本轮指定的最小工程、环境迁移和Windows启动入口已完成，完整M1仍进行中。当前提供开发环境状态页与健康检查，业务表、认证、正式数据导入尚未实现。实施依据为[PROJECT_PLAN 1.3](PROJECT_PLAN.md)。

## Windows启动

需要Docker Desktop已启动、Python3.12.4（`py -3.12`）、Node24.14.1/npm11.11.0，以及[M0镜像锁](validation/m0/database-image.lock.json)对应的已导入官方PostGIS镜像。脚本不会自动拉取其他镜像；换电脑的离线镜像准备见[M0数据库记录](docs/milestones/M0-database.md)。默认Python3.9不用于本项目。

在项目根目录PowerShell执行：

```powershell
& .\scriptsootstrap.ps1
& .\scripts\dev.ps1 -Action DatabaseStart
& .\scripts\dev.ps1 -Action Migrate
& .\scripts\dev.ps1 -Action MigrationStatus
```

bootstrap安装隔离依赖并生成被忽略的`.env`随机凭据，存在时校验且不覆盖。不要直接复制`.env.example`使用。若终端策略阻止本地脚本，可用`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scriptsootstrap.ps1`；Bypass仅对该进程生效，不修改全局策略。dev入口同样可用`-File`运行。

分别打开两个PowerShell终端，在项目目录启动后端和前端：

```powershell
# 终端1
& .\scripts\dev.ps1 -Action Backend
# 终端2
& .\scripts\dev.ps1 -Action Frontend
```

打开[开发环境页](http://127.0.0.1:5173)。后端为`127.0.0.1:8000`，开发库为`127.0.0.1:55433/vision_zero_dev`；全部绑定本机。页面“已就绪”来自真实数据库、迁移版本和PostGIS检查。数据库不可用时ready返回503，live仍可返回200。

其他入口：

```powershell
& .\scripts\dev.ps1 -Action Worker       # 仅连接预检，然后退出
& .\scripts\dev.ps1 -Action Check        # 基础pytest、Vue类型检查、构建
& .\scripts\dev.ps1 -Action Status
& .\scripts\dev.ps1 -Action DatabaseStop # 保留容器、数据卷和数据
```

前后端在各自终端按Ctrl+C停止。端口已占用时脚本拒绝启动；自定义后端端口需同时设置前端`VISION_ZERO_API_TARGET`（本机HTTP）。与`.env`冲突的继承配置会被拒绝，应只在当前终端清除对应变量后重试。

## 工程与验证

| 路径 | 作用 |
|---|---|
| [backend](backend/pyproject.toml) | FastAPI、配置、Alembic、worker预检和测试 |
| [frontend](frontend/package.json) | Vue环境状态页，复用M0精确依赖锁 |
| [compose.yaml](compose.yaml) / [scripts](scripts/dev.ps1) | 专用开发数据库及Windows启动入口 |
| [M1执行记录](docs/milestones/M1.md) / [ADR 0002](docs/decisions/0002-minimal-foundation.md) | 实际命令、验证结果、失败修正和范围 |
| [任务清单](docs/milestones/tasks.md) | 完整M1剩余任务与M2—M8边界 |
| [环境说明](docs/environment.md) / [数据探测](docs/data_probe.md) | 锁定版本、真实数据样本与离线CSV方案 |
| [课程要求S1](docs/references/course_requirements.md) / [前期资料S2](docs/references/prior_work_summary.md) | 归并后的项目约束、保留设计和原文件索引 |
| [M0记录](docs/milestones/M0.md) / [数据库补验](docs/milestones/M0-database.md) | 保留的历史命令、镜像和平台SQL证据 |

本机已验证后端10项测试（含真实PG迁移生命周期）、Windows脚本11项模拟边界、前端类型/构建和桌面页面。普通Check跳过真实数据库集成测试；显式运行方式见M1记录。测试仅在新建随机验证库回退，不回退开发库；验证库保留。

## 当前边界

开发库管理账号暂用于环境迁移和只读预检。完整M1继续完成字段契约、23表、迁移/应用/worker数据库角色分离、认证权限、E-R及数据字典；当前页面没有业务功能。worker没有导入/风险队列，计划中的业务CLI尚不存在。

M0容器与卷独立保留，端口55432；启停仍使用`validation/m0/database.ps1`。本轮没有删除数据、修改其他项目、初始化Git或推送。目录仍无`.git`，当前用文件SHA-256核对改动。四份原课程资料此前按授权归并、校验备份并删除；不再视为缺失文件。

`.env`、`.venv`、`.m0-work`、`.m1-work`、node_modules、dist、原始大文件和备份保持本地。公开碰撞事实与课程模拟治理记录须分别标识；未来提交前检查证据内容和凭据。已知TestClient/httpx及glob弃用提示、原生Docker Registry EOF仍有记录。
