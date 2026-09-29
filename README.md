# 面向 Vision Zero 的纽约交通碰撞风险识别与高危交叉口治理管理系统

个人数据库课程设计。M0、M1已完成：23表、约束/索引/3个业务视图、数据库角色分离、认证和账户管理，以及模型文档。M2真实数据导入尚未开始。实施依据为[PROJECT_PLAN 1.4](PROJECT_PLAN.md)，验收见[M1模型记录](docs/milestones/M1-model.md)。

## Windows启动

需要已启动的Docker Desktop、Python3.12.4（`py -3.12`）、Node24.14.1/npm11.11.0，以及[M0镜像锁](validation/m0/database-image.lock.json)对应的已导入PostGIS镜像。脚本不自动换镜像；离线准备见[M0数据库记录](docs/milestones/M0-database.md)。

首次在仓库根目录PowerShell执行：

```powershell
& .\scripts\bootstrap.ps1
& .\scripts\dev.ps1 -Action DatabaseStart
& .\scripts\dev.ps1 -Action ProvisionRoles
& .\scripts\dev.ps1 -Action Migrate
& .\scripts\dev.ps1 -Action MigrationStatus
& .\scripts\dev.ps1 -Action InitAdmin
```

bootstrap生成本机维护凭据，ProvisionRoles生成独立迁移/app/worker账号和JWT密钥，Migrate创建23表。已有配置/角色均校验归属；不重置未知同名角色。InitAdmin交互读取密码且不回显；已有可用管理员时拒绝初始化。本机此次已初始化admin，随机初始密码在被Git忽略的`.m1-work/model/initial-admin.txt`，登录后请修改密码。不要直接复制`.env.example`。

已初始化后日常启动只需DatabaseStart，并在两个终端分别执行：

```powershell
# 终端1
& .\scripts\dev.ps1 -Action Backend
# 终端2
& .\scripts\dev.ps1 -Action Frontend
```

打开[系统页面](http://127.0.0.1:5173)。后端`127.0.0.1:8000`，开发库`127.0.0.1:55433/vision_zero_dev`，均仅本机监听。登录状态仅保留当前页面内存；刷新需重登。退出、改密、换角色或停用使该账户旧令牌失效，退出作用于全部现有会话。只有ADMIN可维护账户。

前后端在各自终端Ctrl+C停止；数据库用DatabaseStop停止并保留数据。端口占用会拒绝启动，自定义后端端口须对应设置前端VISION_ZERO_API_TARGET。冲突的继承环境变量会被拒绝。终端策略阻止脚本时可用`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action Backend`，仅影响该进程。

## 验证与设计入口

```powershell
& .\scripts\dev.ps1 -Action Check         # 普通测试、类型检查、构建
& .\scripts\dev.ps1 -Action Worker        # worker角色连接预检后退出
$env:VISION_ZERO_RUN_DB_TESTS='1'
& .\.venv\Scripts\python.exe -X utf8 -m pytest backend\tests -q
Remove-Item Env:VISION_ZERO_RUN_DB_TESTS
```

真实PG套件创建随机验证库与独立随机账号，仅这些验证库允许downgrade；开发库禁止业务降级。验证库保留供复核，不在测试中删库或删卷。普通Check会跳过实库用例，不能据此宣称数据库验收通过。

| 文件 | 内容 |
|---|---|
| [M1模型执行记录](docs/milestones/M1-model.md) | 本轮命令、失败修正、独立审计/测试与证据 |
| [数据字典](docs/data_dictionary.md) | 23表逐列类型、空值、主外键、CHECK/UNIQUE/索引 |
| [概念ER](docs/diagrams/conceptual.md) / [关系模型](docs/diagrams/relational.md) | 业务对象及物理联系 |
| [字段映射](docs/field_mapping.md) / [JSON契约](configs/field_mapping_v1.json) | 源键、街道语义、缺失及CSV边界 |
| [规范化](docs/normalization.md) / [数据库和认证权限](docs/security.md) | 函数依赖、受控冗余和角色最小权限 |
| [API契约](docs/api_contract.md) / [ADR 0003](docs/decisions/0003-m1-model-auth.md) | 登录和用户管理、业务契约定案 |
| [任务清单](docs/milestones/tasks.md) | 当前完成情况及M2—M8验收边界 |
| [历史M1基础入口](docs/milestones/M1.md) / [M0](docs/milestones/M0.md) | 保留前次范围和原始证据 |

## 当前边界

开发库有固定三角色、五行政区、初始评分规则、数据修订单例和首次管理员；事故事实、风险结果及工单为空。测试账户和业务夹具只存在独立验证库。worker尚无导入或计算作业，应用数据库账号不直接写事故/工单。完整状态动作及函数在M5落实。

本地Git由用户初始化，当前main保留原始快照；本轮修改未提交或推送。M0库/卷仍独立保留（55432）。`.env`、`.venv`、`.m0-work`、`.m1-work`、node_modules、dist和大文件留在本机；公开证据不含密码/JWT/DSN。M1为本机开发验收，远程部署、真实数据、性能及备份恢复在后续阶段验证。既有Starlette TestClient/httpx弃用提示保留。
