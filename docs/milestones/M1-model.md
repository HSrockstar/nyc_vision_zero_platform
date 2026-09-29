# M1执行记录：数据库模型与认证

日期：2026-09-29。**完整M1已完成。** 本轮按用户授权先落实数据库模型，再完成角色分离、认证、前端和验收。[历史基础入口](M1.md)保留当时范围，不覆盖旧证据。当前实施决定见[ADR 0003](../decisions/0003-m1-model-auth.md)。

## 交付

- 23张关系表：官方事故事实、观察地点/标准路口、原始批次/问题、风险规则/批次/画像、模拟工单/历史，以及账户/角色/审计/数据修订。
- `0002_business_model`读取冻结SQL，历史迁移不依赖未来ORM；34外键、70业务CHECK、唯一键/非空/时间及空间索引、3业务视图；完整性触发器保护关键不可变边界。
- 固定源键与街道映射；UNKNOWN仅调查草稿、在办执行人账户变更保护、四类幂等请求摘要字段已定案。实际导入/幂等重放、计算和完整工单动作仍在M2/M4/M5。
- 本机迁移/app/worker数据库账号分离；worker本阶段只预检，应用账号仅账户维护/审计可写，事故与工单不可直接写。
- Argon2id、15分钟JWT、固定三角色；登录/退出/me/改密及管理员用户创建/分页/版本更新。启停、角色变化、改密及全会话退出使旧令牌失效。
- 概念ER、物理关系图、23表逐列字典、字段映射、API/权限和规范化说明。data_issue批次字段为显式受控冗余，不声称所有支撑快照严格3NF。
- 登录、改密、退出及管理员账户页面，令牌仅页面内存；401清空会话与敏感输入。

模型入口：[models.py](../../backend/app/models.py)、[数据字典](../data_dictionary.md)、[关系模型](../diagrams/relational.md)、[概念ER](../diagrams/conceptual.md)、[规范化](../normalization.md)。

## 本机资源与数据

| 项目 | 实际状态 |
|---|---|
| PostgreSQL / PostGIS | 17.11 / 3.6.4，复用M0锁定镜像 |
| 开发容器/卷 | vision-zero-dev-db / vision-zero-dev-postgis-data，55433仅loopback |
| 开发迁移 | 0002_business_model (head)，alembic check无差异 |
| 固定种子 | 三角色、五行政区、COURSE_V1规则、revision=0 |
| 开发账户 | 首次admin已安全初始化，随机密码仅`.m1-work/model/initial-admin.txt` |
| 官方事实/运行/工单 | collision/person/vehicle/risk_run/governance_task均0行 |
| 验证库 | 新随机vision_zero_m1_test_<12hex>及独立角色，保留供复核 |

[开发库状态](../evidence/M1-model/dev-state.json)仅含数量/版本和初始化登录名，没有哈希或密码。[业务目录](../evidence/M1-model/business-catalog.json)区分扩展对象；[迁移生命周期](../evidence/M1-model/migration-lifecycle.json)记录随机验收库。

## 命令与验收

```powershell
& .\scripts\dev.ps1 -Action DatabaseStart
& .\scripts\dev.ps1 -Action ProvisionRoles
& .\scripts\dev.ps1 -Action Migrate
& .\scripts\dev.ps1 -Action MigrationStatus
# 此次采用本机随机文件方式初始化；日常InitAdmin默认交互
cd backend
& ..\.venv\Scripts\python.exe -X utf8 -m app.cli init-admin --generate
& ..\.venv\Scripts\python.exe -X utf8 -m app.worker
cd ..
$env:VISION_ZERO_RUN_DB_TESTS='1'
& .\.venv\Scripts\python.exe -X utf8 -m pytest backend\tests -q
& .\validation\m1\windows_guards.ps1
```

| 检查 | 结果与证据 |
|---|---|
| 冻结版独立实库套件 | **82 passed，0 failed/0 skipped，48.28秒，exit0**，[日志](../evidence/M1-model/tests-frozen.log) |
| 空库与模型差异 | 空库升级、重复升级、base回退再升级及外部schema保持；alembic check无差异，[日志](../evidence/M1-model/dev-alembic-check.log) |
| 约束/不变性 | PK/FK/NOT NULL/唯一/非负/周期/SRID，事故伤亡延迟一致、原始行/成功画像/规则冻结、UNKNOWN调查草稿拒绝发布 |
| 权限/API | VIEWER/MANAGER拒绝账户写；停用/换角色/改密/退出旧令牌失效；篡改角色claim无效；限流/秘密错误与审计检查 |
| 并发 | 两连接最后管理员保护、在办执行人角色/停用与分配竞争、陈旧版本409 |
| 数据库运行权限 | app/worker拒绝DDL/扩展/规则/工单/历史写；worker拒绝账户/人员/原始行读；PUBLIC函数ACL与默认ACL |
| 维护文件/资源 | 预置pending硬链接/目录junction不外写；读取.env前拒绝reparse；卷标签正确/错误/缺失分别验证 |
| Windows模拟边界 | 11 passed，Docker调用模拟；[日志](../evidence/M1-model/windows-guards.log) |
| 前端类型/构建 | check/build exit0，15模块；[类型](../evidence/M1-model/frontend-check.log)/[构建](../evidence/M1-model/frontend-build.log) |
| 浏览器 | Chrome/Playwright桌面1366×900和窄屏390×844；错误登录/正确管理员/刷新/模拟401/退出均通过；页面无横向溢出，非预期console/page/HTTP错误为0。[脱敏报告](../evidence/M1-model/report.json) |
| 独立审计 | 已报边界问题修复，无确认P0/P1阻断；[复核记录](../evidence/M1-model/review.md) |

测试汇总公共schema含71个CHECK/5个视图，其中1个CHECK/2个视图属于PostGIS扩展；新增业务是70个CHECK/3个视图。唯一后端警告为Starlette TestClient/httpx弃用，保留原始输出，未用SQLite替代。

## 失败与修正

- Docker Desktop此前被两个不可访问运行套接字阻断。主Agent对精确文件的清理被自动审批审查拒绝，未成功删除；用户自行恢复后，实际引擎与专用容器重新核对通过。未恢复出厂设置、未删镜像/卷。
- 初始生命周期断言尝试读取外部schema权限而失败；改用pg_catalog核对对象存在，不扩大迁移权限。
- 第一轮完整套件69通过/1失败：测试所谓短密码恰为12字符，触发重复用户名409；改正非法密码夹具后77通过。随后维护ACL/路径/卷边界新增测试，最终82全部通过。
- 独立浏览器初验遇到异步表格等待及预期401断言顺序问题；按用户可见条件等待，不改产品来迎合测试。缺失favicon资源告警由内联图标修正，前端构建重验。

## 保留与后续

Git初始状态为用户建立的main/7b02dec（Initial local snapshot），本轮开始工作树干净；本轮未提交/推送、未改历史或依赖锁。M0资源及历史资料保留；后端/前端验收进程由本轮启动并在收尾停止，专用开发库保持运行便于下一阶段。

本轮复用Python3.12.4和固定依赖完成可重复M1验收，不声称旧运行时补丁安全更新完成。HTTPS/CORS/多实例限流、真实三源导入、路口归属、风险计算、完整工单函数/对象权限、性能与备份新库恢复均需在对应阶段验收。

下一步建议M2先完成一个真实小批次：2025年约500起事故及对应人员/车辆，文件manifest→暂存→问题隔离→原子发布→事故查询页面；验证重复导入不增加事实行、缺父记录隔离和一事故一汇总，再扩展全年。不能把本次夹具当作正式数据。

## 页面证据

[桌面管理员页面](../evidence/M1-model/03-desktop-admin.png) / [窄屏管理员页面](../evidence/M1-model/04-narrow-admin.png)。截图前密码输入均为空；测试只登录/退出，没有新增或修改业务账户。报告的两次401分别为错误登录和拦截模拟失效，模拟检查不能代替真实后端失效测试，后者由82项实库套件覆盖。

可复跑：`node docs/evidence/M1-model/m1_ui_acceptance.cjs`。依赖仓库既有Playwright、本机Chrome和本地初始密码文件；用户改密后应采用自己的登录验收，不复用过期初始密码。归档脚本将输出写到Git忽略的`.m1-work/model/browser`，只清理其内已检查范围的自建Chrome临时目录。
