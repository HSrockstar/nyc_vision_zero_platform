# 面向 Vision Zero 的纽约交通碰撞风险识别与高危交叉口治理管理系统

个人数据库课程设计。M0—M6本机实现与验收已完成；首批95个路口已核对道路身份，2025年度95条真实画像已生成，模拟治理任务支持多人执行与复核全过程；统计报表、CSV导出与打印已接入真实API。2025全年数据发布与网页重复导入验收通过；23表模型、角色分离、认证、三源CSV清洗/原子发布和事故查询已有实库证据。实施依据为[PROJECT_PLAN](PROJECT_PLAN.md)，后续非前端工作见[M7性能与恢复](docs/milestones/M7.md)和[M8报告与隔离演示准备](docs/milestones/M8-preparation.md)，M6历史见[M6记录](docs/milestones/M6.md)，中期演示入口见[M6演示脚本](docs/milestones/M6-demo.md)，治理依据见[M5记录](docs/milestones/M5.md)，风险依据见[M4记录](docs/milestones/M4.md)，道路身份及剩余候选边界见[M3记录](docs/milestones/M3.md)，历史见[M2记录](docs/milestones/M2.md)和[M1模型记录](docs/milestones/M1-model.md)。

本轮185项分段后端验证（116+69）有通过证据；B01—B04性能实验、新库恢复、非空治理历史二次恢复和独立模拟演示库已完成。前端重构后的验收由前端会话记录；最终报告和录像、干净机器交付仍待完成。维护命令与演示启动见上述M7/M8入口。

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

已初始化后先执行DatabaseStart和Migrate，再在三个终端分别执行：

```powershell
# 终端1
& .\scripts\dev.ps1 -Action Backend
# 终端2
& .\scripts\dev.ps1 -Action Frontend
# 终端3：持续领取导入和风险计算作业
& .\scripts\dev.ps1 -Action Worker
```

打开[系统页面](http://127.0.0.1:5173)。后端`127.0.0.1:8000`，开发库`127.0.0.1:15433/vision_zero_dev`，均仅本机监听。登录状态仅保留当前页面内存；刷新需重登。退出、改密、换角色或停用使该账户旧令牌失效，退出作用于全部现有会话。只有ADMIN可维护账户。

前后端和worker在各自终端Ctrl+C停止；数据库用DatabaseStop停止并保留数据。端口占用会拒绝启动，自定义后端端口须对应设置前端VISION_ZERO_API_TARGET。冲突的继承环境变量会被拒绝。终端策略阻止脚本时可用`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Action Backend`，仅影响该进程。

ADMIN登录后可上传事故、人员、车辆三个CSV，填写左闭右开的日期范围；worker完成校验后批次显示“可发布”，管理员确认后才正式入库。完全重复输入不增加事实或修订号。MANAGER可查看批次摘要，VIEWER只查询事故事实；缺失明细和坐标均保留缺失状态。

官方CSV下载与受控CLI操作见[M2执行与恢复](docs/milestones/M2.md)。上传总CSV上限256MiB，不接收服务器路径或远程URL；当前仅支持单后端/worker开发方式。

M3在页面下方增加地图、附近事故查询、交叉口档案与分页复核。ADMIN/MANAGER可按行政区每批最多100个地点生成候选，并按版本填写依据确认/拒绝，或对地点人工改派。VIEWER可查看地图和归属状态，不能提交复核。2025年度库已核对MANHATTAN首批100个候选，**95个已确认、1个已拒绝、4个待定**，覆盖349起事故。复杂路口道路身份、历史路网版本及剩余待定边界见M3记录。需要批量推进时，可在`backend`目录使用受控命令：

```powershell
..\.venv\Scripts\python.exe -X utf8 -m app.cli generate-intersection-candidates --borough-id 3 --username admin --max-batches 1 --radius-m 50
```

候选生成有审计但不将候选计为正式事故归属；实际确认、拒绝或改派会增加分析数据revision。地图底图依赖网络，业务点查询可独立使用。
上面的命令从该行政区开头复查一批；要继续后续批次，使用上次输出的`last_location_id`作为`--after-location-id`，并保持同一半径。每批结果可重复运行，人工结果不会被覆盖。

## M4风险画像

登录后进入“风险画像与历史批次”，选择周期、规则和成功批次；ADMIN/MANAGER可排队计算，VIEWER只读。页面展示覆盖、分数、等级、分项、分页及过期提醒。2025全年run 1已完成：95条画像，高14、中44、低37；仅349/85,546起事故纳入，覆盖0.41%，不能解释为全市排名。缺失评分伤亡字段时显示UNKNOWN和已知值合计，无画像不等于低风险。

从`backend`目录可用受控CLI计算其他周期：

```powershell
..\.venv\Scripts\python.exe -X utf8 -m app.cli request-risk-run --username admin --start 2025-01-01 --end 2026-01-01
..\.venv\Scripts\python.exe -X utf8 -m app.worker --kind risks --once
```

没有指定request-id时每次建立新的计算批次；重试同一请求需保留UUID。默认worker同时处理导入/风险。结果与映射/评分输入快照绑定，文件保存在被忽略的`.m4-work/snapshots`，数据库和文件应一起备份；成功批次只读。规则/公式与计算方法见[ADR 0006](docs/decisions/0006-m4-risks.md)。

## M5模拟治理任务

ADMIN/MANAGER在风险画像行选择“建立治理草稿”，填写措施、说明、评价半径和必要理由。发布时指定当前启用的管理人员，由执行人开始、追加记录和提交，再由创建者或其他有权管理员退回或通过；执行人不能复核自己的任务。支持待执行重分配、非终态取消、草稿软删除、我的执行待办和只追加历史。

LOW/MEDIUM建立必须填写理由；UNKNOWN只能调查草稿、不能发布。画像与评价范围建立后冻结，所有记录明确标为课程模拟。VIEWER不显示或访问治理业务。写失败或版本冲突后主动重新加载详情，系统不会自动覆盖其他人的修改。工单和历史的写入由数据库受控函数同事务完成；完整状态、权限与幂等契约见[ADR 0007](docs/decisions/0007-m5-governance.md)。

本机开发库固定使用15433；由Windows保留区间导致的原端口修复、原卷保留及配置备份见[端口记录](docs/milestones/M5-port.md)。历史验收记录中的旧端口保持其当时事实。

## M6统计、导出与打印

登录后进入“统计报表”。页面通过真实API查询PostgreSQL，提供日期（结束日含当天，默认2025-01-01至2025-12-31，提交时自动转为次日排他上界）、行政区（1=布朗克斯、2=布鲁克林、3=曼哈顿、4=皇后区、5=斯塔滕岛）、街道、车型、原因筛选，并展示当前范围总览、行政区分布、月度趋势（含伤亡缺失列）、小时分布、原因Top10、车辆类型、人员类别（ADMIN/MANAGER）与模拟工单统计（ADMIN/MANAGER）。车型/原因筛选只负责选出涉及的事故，车辆与人员明细统计这些事故内的全部记录；伤亡为Crashes汇总口径，全部未知显示“无已知值”而不是0。月度空月份不补零，表格标注覆盖状态；原因/车型组别之间存在重叠，不做互斥占比图。

“下载事故CSV”导出当前筛选的事故列表（上限5,000行数据，超限明确拒绝并提示缩小范围）；“下载统计报表CSV”（ADMIN/MANAGER）在同一数据库快照内一次生成总览/行政区/月度/小时/原因/车型/人员各节（聚合结果，无5000行上限）；两份CSV均带说明行（生成时间、revision、排他区间、口径与缺失/重叠说明），NULL导出为空字段。页面区分“正在编辑的表单”与“已应用筛选”：下载与打印始终绑定后者；数据版本不一致时输出停用并提示重新查询。“打印报表”使用浏览器打印样式：只保留统计面板，页首含可打印标题与已应用条件摘要及课程模拟标记。VIEWER可读基础统计与事故CSV，人员细分、治理统计及统计报表CSV由后端403。统计口径、导出与权限细节见[ADR 0008](docs/decisions/0008-m6-statistics-export.md)。

## 验证与设计入口

```powershell
& .\scripts\dev.ps1 -Action Check         # 普通测试、类型检查、构建
Push-Location backend
& ..\.venv\Scripts\python.exe -X utf8 -m app.worker --preflight  # 只预检连接
Pop-Location
$env:VISION_ZERO_RUN_DB_TESTS='1'
& .\.venv\Scripts\python.exe -X utf8 -m pytest backend\tests -q
Remove-Item Env:VISION_ZERO_RUN_DB_TESTS
```

真实PG套件创建随机验证库与独立随机账号，仅这些验证库允许downgrade；开发库禁止业务降级。验证库保留供复核，不在测试中删库或删卷。普通Check会跳过实库用例，不能据此宣称数据库验收通过。

| 文件 | 内容 |
|---|---|
| [M2导入与查询记录](docs/milestones/M2.md) / [ADR 0004](docs/decisions/0004-m2-import-query.md) | 官方输入、批次发布、质量统计和独立验收 |
| [M3空间归属记录](docs/milestones/M3.md) / [ADR 0005](docs/decisions/0005-m3-spatial.md) | 地图、米制查询、候选、人工确认与归属 |
| [M4风险记录](docs/milestones/M4.md) / [ADR 0006](docs/decisions/0006-m4-risks.md) | 风险作业、统一视图、覆盖与历史快照 |
| [M5治理记录](docs/milestones/M5.md) / [ADR 0007](docs/decisions/0007-m5-governance.md) | 模拟治理、对象身份、原子历史及独立验收 |
| [M6统计记录](docs/milestones/M6.md) / [ADR 0008](docs/decisions/0008-m6-statistics-export.md) | 统计口径、CSV导出、打印与中期演示 |
| [M1模型执行记录](docs/milestones/M1-model.md) | 本轮命令、失败修正、独立审计/测试与证据 |
| [数据字典](docs/data_dictionary.md) | 23表逐列类型、空值、主外键、CHECK/UNIQUE/索引 |
| [概念ER](docs/diagrams/conceptual.md) / [关系模型](docs/diagrams/relational.md) | 业务对象及物理联系 |
| [字段映射](docs/field_mapping.md) / [JSON契约](configs/field_mapping_v1.json) | 源键、街道语义、缺失及CSV边界 |
| [规范化](docs/normalization.md) / [数据库和认证权限](docs/security.md) | 函数依赖、受控冗余和角色最小权限 |
| [API契约](docs/api_contract.md) / [ADR 0003](docs/decisions/0003-m1-model-auth.md) | 登录和用户管理、业务契约定案 |
| [任务清单](docs/milestones/tasks.md) | 当前完成情况及M2—M8验收边界 |
| [历史M1基础入口](docs/milestones/M1.md) / [M0](docs/milestones/M0.md) | 保留前次范围和原始证据 |

## 当前边界

开发库已发布2025全年85,546起官方事故、292,070条人员和170,015条车辆。完整年度三源CSV共547,631行；M2重复发布与网页重复导入均无事实增量。M3道路复核后revision=98、95个已确认、1个已拒绝、4个待定，95条正式归属覆盖349起事故。M4前向升级0006并生成run 1的95条画像，计算不改变事实或revision。M5已前向升级0007并完成独立随机库验收；M6为纯查询统计，迁移仍为0007，实施前后事实/revision/画像/工单逐项不变（工单/历史仍为0）。测试账户和合成夹具只存在独立验证库。worker执行导入/风险作业，app账号不直接写事故事实或风险画像。

本地Git由用户管理；本会话的M7/M8非前端修改未提交或推送，历史记录中的旧HEAD保留其当时含义。M0库/卷仍独立保留（55432）。`.env`、`.venv`、`.m0-work`至`.m8-work`、data/raw、node_modules和dist留在本机且被忽略；公开证据不含密码/JWT/DSN或真实人员行，历史浏览器验收与截图使用独立合成验证库。本项目已完成本轮SQL性能对照、权限检查和隔离备份恢复验证；远程部署、全系统吞吐测试和干净机器交付尚未验收。既有Starlette TestClient/httpx弃用提示保留，前端构建情况由前端会话记录。
