# 面向 Vision Zero 的纽约交通碰撞风险识别与高危交叉口治理管理系统

## 项目设计与 Codex 实施计划

- 文档版本：1.6
- 编制日期：2026-09-28
- 更新日期：2026-09-30（已确认95个路口，M4风险批次与画像实施）
- 用途：本学期数据库课程设计的开发依据、任务拆分依据和验收清单。
- 当前状态：M0—M4本机实现与验收已完成，首批95个路口道路身份已确认，2025年度95条画像已生成；121项独立实库回归、迁移往返、前端检查/构建及桌面/窄屏验收通过。下一阶段为M5治理业务。完成范围见§0.4及[M4记录](docs/milestones/M4.md)。
- 实现形式：个人完成的 B/S 数据库应用系统。开发辅助工具的使用方式以教师要求为准，最终代码、设计和答辩内容应由项目作者理解和审核。
- 阅读入口：本计划、[课程要求摘要S1](docs/references/course_requirements.md)、[前期资料保留摘要S2](docs/references/prior_work_summary.md)。四份原资料已按用户要求归并为Markdown，删除前均有校验压缩备份，后续不再把原文件缺席视为资料缺失。

## 0. 阅读约定与依据

### 0.1 依据及优先级

本计划以以下材料为基础。

| 编号 | 材料 | 在本计划中的作用 |
|---|---|---|
| S1 | [课程要求与项目参考摘要](docs/references/course_requirements.md) | 完整核对正确的18页秋季指南后保留项目约束和参考内容；原页码及备份见摘要§6 |
| S2 | [前期资料保留摘要](docs/references/prior_work_summary.md) | 汇总上学期报告、选题说明和早期大纲的有效内容；标明来源及过时内容 |
| U1 | 本次确认的题目及扩展意向 | 增加用户与角色、治理任务、治理记录与状态历史、导入批次四类业务对象 |

课程要求以 S1 为准；继承设计以 S2 中保存的原报告最终结论为准，本期修正以本计划和 ADR 为准。`CollisionFactor` 沿用 `(collision_id, factor_order)` 主键，不采用早期大纲的三字段主键。S2 §6 保留原文件名和位置索引，旧 S3/S4 编号停用。[S2，§2、§5]

文中使用三类表述。

- **课程要求**，指 S1 明确提出的要求。
- **继承设计**，指 S2 已有的实体、功能或方案。
- **本期实施决定**，指为了完成可运行系统而提出的设计选择。具体框架、工单状态、接口、测试数量和性能目标均属于这一类，不代表老师逐项要求。

外部技术资料只用于核对数据字段和实现方法，编号为 W1 至 W8，其中 W6 分为三项，见文末。尚未实际探测的 API 可用性、实际数据量、依赖兼容性和性能结果必须由开发阶段验证，禁止写成已确认事实。

### 0.2 项目定位

保留上学期的事故查询、行政区统计、事故原因分析、车辆类型分析、人员伤亡分析和风险画像功能。扩展高危交叉口档案、治理任务、处理记录、角色权限和可追溯的数据导入。[S2，§1、§4；U1]

系统的主要演示过程是，导入公开碰撞数据，查询事故，识别需要关注的交叉口，由管理人员建立治理任务，分配执行人，提交处理记录，完成复核，再查看同一统计口径下的描述性数据对比。

公开碰撞记录来自官方数据。用户、角色、治理任务、处理记录和演示中的治理实施日期由本系统创建，默认属于课程模拟业务数据。不得把模拟工单标为纽约政府实际开展的治理项目。

### 0.3 原方案保留与调整清单

| 原方案内容 | 本期处理 | 理由及来源 |
|---|---|---|
| 九个核心实体、十个主要关系模式 | 保留其业务含义，数据库命名统一为 `snake_case` | S2 §2；本期扩展为23表 |
| `Collision` 为核心，人员和车辆按事故关联 | 保留 | S2 §2 |
| `CollisionFactor(collision_id, factor_order, factor_id)` | 保留，主键为前两列，槽位范围 1—5 | S2 最终稿已确定 |
| 原文人员和车辆编号映射较简略 | 明确区分官方 `unique_id` 与原始 `person_id`、`vehicle_id` | 本期字段核对，依据 W1、W2 |
| `Location` 同时承担事故地点和交叉口 | 保留事故地点，再新增 `Intersection` 和地点归属表 | 本期设计，避免把任意事故坐标当成真实交叉口 |
| `RiskProfile` 保存地点及周期指标 | 改为按标准交叉口及计算批次保存指标，周期和规则放入 `RiskRun` | 本期设计，支持复算与版本追溯 |
| 风险分数、等级直接存在画像表 | 默认由统一 SQL 视图计算，物化结果仅作可选读取优化 | 本期设计，区分基础关系与派生结果 |
| 一般查询索引 | 增加复合索引和匹配查询表达式的空间索引，实际收益通过测试判断 | S2 §3 |
| 原始暂存表与批次追溯 | 实现为导入批次、原始记录和数据问题记录 | S2 §3 |
| 三类用户仅有角色说明 | 实现认证和后端权限校验 | S2 §1，落实 S1 安全性要求 |
| 高危交叉口以查询分析为主 | 新增治理任务和不可任意修改的历史记录 | 本次确认的新增业务 |

原报告中的表结构可以作为起点。上表明确列出的调整需要同步更新 E-R 图、数据字典、迁移文件和设计报告，不能只改代码。

### 0.4 当前进度与下一阶段入口

| 项目 | 实际状态 / 证据 |
|---|---|
| 资料与课程核对 | 前期资料归并为S2，秋季指南归并为S1；指定原文件已删除并保留校验备份。处理与来源索引分别见S1/S2 §6 |
| 数据探测 | M0探测保留；M2已下载并发布首批500起及2025年度三源CSV（总547,631行），正式事故85,546起；重复发布、网页重复导入、年度质量与容量核验通过。[M2记录](docs/milestones/M2.md) |
| 数据库 | Docker 内 PG17.11/PostGIS3.6.4，官方镜像摘要已锁；Windows/Linux各11项真实SQL及持久卷复启通过。[补验记录](docs/milestones/M0-database.md) |
| 依赖 | Python3.12.4、Node24.14.1/npm11.11.0；Windows40包/Linux38包分别锁定，前端严格安装、类型检查和构建通过。[环境说明](docs/environment.md) |
| 工程与Git | backend/frontend、23表、认证、M2导入/查询、M3空间归属及M4风险计算/快照已实现；开发库迁移0006_risk_worker。main HEAD为已提交M3的44bf96d；M4修改未提交或推送。[M4记录](docs/milestones/M4.md) |
| 当前风险输入与结果 | 95个已确认、1个已拒绝、4个待定；revision98，2025全年349/85,546起事故纳入，95条画像（高14/中44/低37）。快照重聚合及3个手算核对通过。[聚合证据](docs/evidence/M4/local-acceptance.json) |
| 当前开发方式 | 数据库Docker，后端/前端/导入worker在Windows分别前台启动。开发库127.0.0.1:55433独立于M0库55432。[启动入口](README.md) |

历史基础入口保留于[ADR 0002](docs/decisions/0002-minimal-foundation.md)。完整M1按用户授权落实数据库模型优先顺序：街道映射、UNKNOWN调查草稿、在办执行人账户变更和request_hash契约见[ADR 0003](docs/decisions/0003-m1-model-auth.md)；23表迁移、数据库权限与认证有独立实库复验。字段完整口径见[数据字典](docs/data_dictionary.md)，规范化及受控冗余见[3NF说明](docs/normalization.md)，当前范围见[任务清单](docs/milestones/tasks.md)。M2导入/查询见[ADR 0004](docs/decisions/0004-m2-import-query.md)和[M2记录](docs/milestones/M2.md)；M3空间工作流见[ADR 0005](docs/decisions/0005-m3-spatial.md)和[M3记录](docs/milestones/M3.md)；M4风险计算/快照见[ADR 0006](docs/decisions/0006-m4-risks.md)和[M4记录](docs/milestones/M4.md)，工单动作留M5。

## 1. 课程要求与项目交付映射

### 1.1 必须覆盖的课程内容

| 要求编号 | 课程要求 | 本项目落实方式 | 依据 |
|---|---|---|---|
| C01 | 可沿用上学期选题，10 月 8 日前在 Canvas 录入最新题目 | 使用本计划标题，完成题目登记 | S1，§1 |
| C02 | 问题定义、可行性分析 | 说明数据、业务、技术和个人工作量边界 | S1，§2 |
| C03 | 需求分析包含数据字典、数据流图 | 提供数据字典和第 0、1 层数据流图 | S1，§2 |
| C04 | 概念、逻辑和物理设计，一般达到 3NF | 完整 E-R 图、函数依赖说明、DDL、约束、索引 | S1，§2 |
| C05 | 数据库建立、应用实现、调试和综合测试 | 前后端真实访问 PostgreSQL，提供测试证据 | S1，§2 |
| C06 | 三类完整性约束 | 主键、外键、唯一约束、检查约束和必要的触发器 | S1，§2 |
| C07 | 用户管理及不同级别权限 | 管理员、交通管理人员、普通查询用户 | S1，§2 |
| C08 | 按业务需要实现基本操作及附加分析功能 | 工单增删改查、数据查询、统计、导出打印、备份恢复 | S1，§2 |
| C09 | 必要索引、SQL 优化、数据库性能测试 | 至少四组可复现的查询实验和执行计划分析 | S1，§2；实验数量为本计划目标 |
| C10 | 独立完成、界面友好、运行正常 | 单独仓库、可复现启动、功能演示、作者能够解释代码 | S1，§2—3 |
| C11 | 提交报告、代码和完整功能录像 | 报告 1.0 万至 1.5 万字，源码、迁移、运行说明和录像 | S1，§2—3 |
| C12 | 第 10 周中期检查，第 16 周期末答辩 | 中期完成真实数据与主要业务，后期完成测试和交付 | S1，§3 |

指南列举了常见应用功能，并未要求所有项目对每张表实现全部增删改操作。公开事故事实以导入、更新和查询为主，治理任务承担主要业务写入。[S1，§2；S2，§3]

本学期报告要求1.0万—1.5万字，前期资料中的20页篇幅安排不作为本期约束。[S1，§3；S2，§5]

### 1.2 小组调研任务单独管理

S1 另有 3—5 人小组前沿调研，要求提交 20—30 页 PPT，可深化上学期调研并用 1 页说明区别。本计划只负责个人应用系统。不要为了小组调研主题，未经确认就在个人项目中加入向量数据库、RAG 或分布式数据库。[S1，§5]

课程完整提交包括个人系统与小组调研；小组须列明成员和各自工作，申优正式答辩展示两部分成果及分工。系统研发/报告合计50%，进度与答辩20%，小组调研20%，平时考勤10%；具体比例、讲座与周次要求见S1 §3、§5，不据此增加个人系统功能。

## 2. 实现范围与优先级

### 2.1 P0 必做范围

P0 表示本项目最终提交版本必须具备的内容，不表示第一轮开发就全部完成。

| 模块 | P0 功能 | 验收要点 |
|---|---|---|
| 数据接入 | 官方三类数据的小规模与完整范围导入、离线 CSV 导入、批次及异常追踪 | 有真实数据，有重复导入测试，来源可核对 |
| 用户权限 | 登录、退出、用户启停、三类角色、后端鉴权 | 越权请求被后端拒绝 |
| 事故管理 | 多条件查询、分页、事故详情、人员车辆明细、导出 | 使用数据库查询，无前端假数据 |
| 地点与交叉口 | 事故点展示、候选交叉口、人工确认、归属修正 | 明确区分候选与确认结果 |
| 风险识别 | 原方案规则、按周期批量生成、分项指标、等级筛选、来源版本 | 数值可手算核验，旧结果可追溯 |
| 治理管理 | 草稿、发布、分配、执行、提交、复核、取消、历史 | 状态、权限及并发修改测试通过 |
| 统计展示 | 行政区、时间、原因、车辆类型、伤亡、工单状态 | 不因多表连接重复计数 |
| 系统维护 | 数据问题处理、必要字典维护、日志、CLI 备份及恢复演练 | 能在新数据库恢复并校验 |
| 性能与交付 | 索引实验、SQL 优化、自动化测试、完整演示、报告材料 | 保留真实执行计划和测试结果 |

### 2.2 P1 完成 P0 后补充

治理前后描述性对比、物化视图实验、更多真实数据、增强的断点续传、风险规则管理页面、批量交叉口复核、地图交互优化。

规则版本表和计算批次表从一开始建立。P1 的“规则管理页面”仅指配置界面，不影响 P0 使用初始化规则。

### 2.3 P2 可选，默认不做

机器学习预测、交通流量融合、自动道路拓扑建模、实时流处理、大模型问答、移动端 App、短信通知、外部政府工单对接、预算审批、多租户、微服务和 Kubernetes。

不得通过扩大 P2 功能挤占数据库设计、性能测试和报告时间。课程指南并未要求训练模型。[S1，§2—4]

## 3. 技术方案与仓库结构

### 3.1 本期技术选择

以下是本计划的实施选择。S1 允许 PostgreSQL 和 Python，但未指定这些框架。[S1，§4]

| 层次 | 选择 | 实施要求 |
|---|---|---|
| 数据库 | PostgreSQL 17.11 / PostGIS 3.6.4，Docker linux/amd64 | M0已实测并锁官方摘要，见validation/m0/database-image.lock.json；不使用浮动latest |
| 后端 | Python 3.12、FastAPI | Windows项目venv开发，单体分模块；3.12.4组合已验证，补丁升级另验 |
| 数据访问 | SQLAlchemy 2.x、psycopg 3、Alembic、GeoAlchemy2 | 同步数据库访问方案，空间类型由明确迁移创建 |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia | Windows Node/npm开发，复用M0 package-lock；类型化接口、按业务划分页面 |
| UI 与图表 | Element Plus、Apache ECharts | 以表格、表单和统计图为主 |
| 地图 | Leaflet | 数据坐标使用 WGS84，地图服务可配置 |
| 后台作业 | 同一后端代码库的独立 worker 进程 | 从 PostgreSQL 领取导入和风险计算任务，不依赖 Redis/Celery |
| 测试 | pytest、Vitest、Playwright | 集成测试使用真实 PostgreSQL/PostGIS |
| 开发与交付 | 开发时Docker数据库 + Windows后端/worker/前端；Compose保留交付入口 | M1先提供数据库Compose和PowerShell启动说明，全服务Compose在交付阶段按需补齐；数据库不暴露到公网 |

M0精确版本、镜像锁和平台哈希锁已经记录在 `validation/m0/` 与 [环境说明](docs/environment.md)。已验证包安装、基础调用和真实数据库连接；业务迁移、权限、浏览器功能及性能仍待相应阶段验收。

普通同步数据库接口使用合适的同步处理函数。不要在 `async def` 中直接执行耗时同步查询并阻塞事件循环。数据导入和风险批处理交给 worker，不占用用户请求连接。[实现选择，框架接口以实际锁定版本文档为准]

### 3.2 部署组成

开发环境包含 `db`、`backend`、`worker`、`frontend` 四个进程或服务：db在Docker中，后端与worker共用Windows项目venv、分别启动，前端用Windows npm启动Vite。后端连接本机数据库端口，前端只访问后端API。M0验证库为127.0.0.1:55432；M1配置明确区分开发、测试及演示数据库和凭据，不能混用测试与演示数据。

交付时可由Web服务提供前端静态文件并反向代理 `/api`，Compose统一部署属于交付配置，不要求日常开发把前后端也容器化。数据库镜像/卷保留；实际启停入口见README。

后台作业状态保存在数据库。worker 重启后应识别未完成作业。不要只用进程内变量表示导入进度，也不要把不可丢失的长任务仅放入 HTTP 请求的后台回调。

### 3.3 建议目录

```text
vision-zero-db/
  PROJECT_PLAN.md
  README.md
  .env.example
  .gitignore
  compose.yaml
  backend/
    pyproject.toml
    dependency-lock-file
    alembic.ini
    migrations/
    app/
      main.py
      config.py
      db/
      models/
      schemas/
      api/
      services/
        auth/
        imports/
        collisions/
        intersections/
        risks/
        governance/
        statistics/
      repositories/
      sql/
      worker.py
      cli.py
    tests/
      unit/
      integration/
      fixtures/
  frontend/
    package.json
    package-lock.json
    src/
      api/
      components/
      views/
      stores/
      router/
      types/
    tests/
  configs/
    datasets.yaml
    risk_rule_v1.yaml
    import_rules.yaml
  scripts/
    bootstrap.ps1
    bootstrap.sh
    backup.ps1
    backup.sh
    restore_verify.ps1
    restore_verify.sh
  data/
    samples/
    raw/
    manifests/
    exports/
  benchmarks/
    queries/
    run_benchmarks.py
    results/
  docs/
    requirements.md
    feasibility.md
    environment.md
    data_dictionary.md
    field_mapping.md
    normalization.md
    api_contract.md
    security.md
    data_quality.md
    decisions/
    diagrams/
    testing/
    milestones/
    report/
    references/
      prior_work_summary.md
```

`dependency-lock-file` 表示所选工具的真实锁文件，M0 决定使用一种锁定方案并替换，不要创建这个占位名称的文件。大规模数据、备份、密码、访问令牌、个人参考材料和生成的临时文件不提交公共仓库。

## 4. 用户、权限与数据写入边界

### 4.1 角色

保留上学期的三类用户。[S2，§1]

| 能力 | ADMIN 系统管理员 | MANAGER 交通管理人员 | VIEWER 普通查询用户 |
|---|---|---|---|
| 基础事故查询、地图、汇总图表 | 允许 | 允许 | 允许 |
| 人员与车辆详细分析 | 允许 | 允许 | 仅允许必要的基础信息，不提供人员年龄性别明细 |
| 导入、批次发布、问题处理 | 允许 | 只读导入摘要 | 不允许 |
| 交叉口候选生成 | 允许 | 允许 | 不允许 |
| 交叉口与地点归属确认 | 允许 | 允许 | 不允许 |
| 生成风险结果 | 允许 | 允许 | 只读已完成结果 |
| 创建和处理治理任务 | 允许，仍遵守状态规则 | 按任务内身份授权 | 不允许 |
| 用户启停及角色管理 | 允许 | 不允许 | 不允许 |
| 业务审计查询 | 允许 | 仅本人或可访问任务的记录 | 不允许 |
| 备份恢复 | 由维护人员使用受控 CLI | 不允许 | 不允许 |

P0 不提供公开注册。由管理员创建账户。角色枚举固定，不开发可任意配置的权限平台。

### 4.2 治理任务中的身份

在角色之外区分任务创建者、执行人和复核人。MANAGER 可以查看未删除任务，但只能修改自己有权负责的部分。发布、分配和取消由创建者或管理员执行。开始执行、增加执行记录和提交验收由当前执行人执行。复核由创建者或管理员执行，同时不得与当前执行人为同一人。

演示初始化至少配置两名不同的 MANAGER，用于展示分配和独立复核。前端按钮隐藏只能改善交互，后端必须重新鉴权。

### 4.3 公开事实与应用业务分开维护

`collision`、`person`、`vehicle` 和官方伤亡统计不开放普通手工 CRUD 接口。更新必须经过受控导入。错误原始值保存在暂存层，清洗规则产生规范化结果，并记录清洗版本。

可人工新增、修改、取消和删除草稿的对象主要是治理任务。用户支持停用，已被使用的字典支持停用或修改显示名，已确认交叉口支持受控维护。事故缺少经纬度时仍保留，不强行补成零坐标。

## 5. 数据来源、字段契约与开发数据范围

### 5.1 数据源

| 数据源 | Dataset ID | 数据粒度 | 在系统中的用途 |
|---|---|---|---|
| Motor Vehicle Collisions - Crashes | `h9gi-nx95` | 事故事件 | 时间、地点、事故原因槽位、伤亡汇总 |
| Motor Vehicle Collisions - Person | `f55k-p6yu` | 涉事人员记录 | 人员类型、伤亡状态和必要明细 |
| Motor Vehicle Collisions - Vehicles | `bm4k-52h4` | 涉事车辆记录 | 车辆类型、年份、碰撞状态等 |

数据集及关联设计继承原报告。[S2，§2、§6]

### 5.2 关键字段映射

官方 Person 和 Vehicles 字段说明将 `unique_id` 标为记录主键，同时分别提供文本型 `person_id` 和 `vehicle_id`。这几个名字不能互换。[W1、W2]

| 来源 | 原始字段 | 目标字段 | 约定 |
|---|---|---|---|
| Crashes | `collision_id` | `collision.collision_id` | 事故主键 |
| Person | `unique_id` | `person.person_id` | 系统人员记录主键，使用 BIGINT |
| Person | `person_id` | `person.source_person_id` | 原始业务代码，TEXT，不作为已验证的唯一身份 |
| Vehicles | `unique_id` | `vehicle.vehicle_id` | 系统车辆记录主键，使用 BIGINT |
| Vehicles | `vehicle_id` | `vehicle.source_vehicle_id` | 原始车辆代码，TEXT |
| Person / Vehicles | `collision_id` | 各表 `collision_id` | 引用事故主表 |
| Person | `vehicle_id` | `person.source_vehicle_id` | 原样保留，P0 不据此直接建立人员车辆外键 |
| Crashes | `contributing_factor_vehicle_1` 至 `_5` | `collision_factor` | 保存原槽位编号，不声称已匹配 Vehicles 记录主键 |

Person 与 Vehicle 的直接关联属于可选扩展。必须先验证连接字段、事故一致性、重复和缺失情况，再决定使用何种键。P0 通过事故页面分别显示人员和车辆，避免错误配对。[本期实施决定]

M0元数据及样本发现Crashes API字段名与显示语义存在冲突：`off_street_name`显示为横街，`cross_street_name`显示为街道外地址。M1已完成的字段字典显式映射前者到逻辑横街、后者到逻辑地址，保留原字段及映射版本；CSV按实际表头独立核验。不得直接按API变量名字进行交叉口配对。[docs/data_probe.md，§5；ADR 0003]

官方字段说明中的 `person_type` 并不等于可以直接细分驾驶员和乘客。P0 先按原字段支持的类别统计。只有核实其他角色字段后才增加更细分类，不能从年龄或车辆类型猜测人员角色。[W1]

### 5.3 已完成的数据探测及适用边界

M0已在 [docs/data_probe.md](docs/data_probe.md) 记录访问方式、探测时间、字段、2025年度键检查、日期边界、地点缺失及小样本关联。限定样本为10起父事故、40条人员、20条车辆；年度无重复的查询结果不能外推到全历史。

保存取得的字段元数据和样本响应。网页显示的更新时间不能替代最大事故日期，也不能证明三张表同日更新。官方数据说明提示数据可能修订，因此不能把已导入记录永远视为不再变化。[W1、W2、W3]

M0只下载限定样本和查询响应，没有完整年度原文件、正式导入或全历史质量统计。完整CSV、父子覆盖、评分字段缺失和存储容量在M2按实际文件与manifest核验；超时和网络失败记录保留，不用预计值补齐。

### 5.4 时间范围

以固定范围保证复现，避免每次运行都自动改成“最近一年”。

- M2首批导入固定为2025年1月按 `(crash_date, collision_id)` 稳定排序的前500起事故及其完整人员、车辆明细；M0仅有10起父样本，不能称500起已取得。实际数量记录在manifest。
- 业务开发数据先使用 `[2025-01-01, 2026-01-01)` 的完整选定范围。
- 性能和前后对比需要时扩展到 `[2024-01-01, 2026-01-01)`。数据实际可获得性由探测决定。

上述范围已由M0确认作为开发目标；后续改动须同时写入配置、探测报告和数据清单。不要把截断的前N行数据称为某年的完整数据。

所有统计日期使用左闭右开区间。前端选择的结束日可包含当天，但后端统一转换为次日零点的排他上界，并在接口文档中说明。

### 5.5 时间语义

事故日期及时间按纽约当地报告时间保存为 `DATE` 和 `TIME`。源时间没有可靠时区偏移时，不凭空生成精确 UTC 时刻。缺少事故时间时使用 NULL，不补为 00:00。

系统创建、修改、登录、导入和审计时间使用 `TIMESTAMPTZ`，后台以 UTC 处理。界面明确区分事故当地时间与系统操作时间。纽约当地时间存在夏令时歧义时，保留源值，不用日期时间推断唯一 UTC 时间。[本期数据契约]

### 5.6 下载与离线导入

先验证官方当前文档和实际响应，再确定下载适配器。允许 API 下载或官方 CSV 导出，不绑定某个永远不变的接口版本。访问令牌从环境变量读取，不写入前端或仓库。

API 下载必须有超时、有限重试、分页顺序、下载范围和断点文件。优先按日期区间及稳定主键分段。获取全量父记录后，子表按同范围获取并以父事故 ID 集合校验，必要时补取指定事故的明细。

403 时记录错误并检查接口、令牌及网络，不无限重试，不绕过访问控制。429 按服务器提示退避，5xx 有限重试。网络无法下载时，切换到官方网页导出的 CSV。离线 CSV 是 P0 必须可用的入口。

三个数据源未必具有完全同步的更新时间。父记录存在而子表缺少明细时标记明细覆盖情况，不伪造人员或车辆，也不自动判定没有伤亡。事故层面伤亡统计以 Crashes 对应字段为主。

## 6. 数据模型总览

### 6.1 四类新增业务对象如何落表

用户确认的“四类业务实体”按业务对象理解，可以分别对应多张关系表。

| 业务类别 | 对应表 | 作用 |
|---|---|---|
| 用户与角色 | `app_user`、`role` | 身份、角色、启停和登录失效控制 |
| 治理任务 | `governance_task` | 治理目标、任务内容、执行人、当前状态 |
| 治理记录与状态历史 | `task_history` | 合并保存状态变更、执行说明和复核意见 |
| 导入批次与追踪 | `import_batch`、`raw_record`、`data_issue` | 批次、原始输入、异常及处理结果 |

此外新增标准交叉口、地点归属、风险规则、计算批次、审计日志和数据版本。这六张支撑表用于解决交叉口身份、版本和追溯问题，不额外引入新的业务子系统。

默认方案共 23 张关系表。原有十张业务关系保留，新增十三张业务或支撑关系。原始记录、审计和派生结果与基础业务关系分开说明，不为凑数量再拆更多表。

### 6.2 主要联系

| 联系 | 基数及说明 |
|---|---|
| Borough 与 Location | 一个行政区可对应多个原始地点，地点行政区可缺失 |
| Location 与 Collision | 一个精确地点记录可对应多起事故，未知地点不得全部合并 |
| Collision 与 Person / Vehicle | 一对多，允许源数据缺少相应明细 |
| Collision 与 CasualtyStat | 正式发布后的事故应有一条统计记录，数值允许缺失 |
| Collision 与 ContributingFactor | 通过 CollisionFactor 表示多对多，同时保留 1—5 槽位 |
| Location 与 LocationAssignment | 一对零或一，保存当前归属判断 |
| Intersection 与 LocationAssignment | 一对多，同一交叉口可对应多个观察地点 |
| RiskRule 与 RiskRun | 一对多，一个不可变规则版本可被多次计算使用 |
| RiskRun 与 RiskProfile | 一对多，同一批次的每个交叉口最多一条画像 |
| RiskProfile 与 GovernanceTask | 一对多，工单引用建立时所依据的不可变画像 |
| GovernanceTask 与 TaskHistory | 一对多，历史记录按任务内序号排列 |
| Role 与 AppUser | 一对多，P0 一个用户对应一个固定角色 |
| ImportBatch 与 RawRecord / DataIssue | 一对多 |

概念 E-R 图绘制时区分实体、联系和基数。关系模型图可以展示关联表和字段。两种图的说明不能混用。[S1，§2；S2，§2]

## 7. 关系表与关键字段设计

### 7.1 通用约定

以下是目标字段契约，Codex 应据此编写完整 DDL、ORM 和数据字典。字段类型需要迁移验证，不能仅生成 ORM 后跳过数据库约束。

内部主键默认使用 `BIGINT GENERATED BY DEFAULT AS IDENTITY`。官方事故、人员记录、车辆记录主键使用来源 BIGINT，不自增生成。API 将所有 BIGINT 标识符序列化为字符串，避免前端数字精度问题。计数正常返回数字。

没有特别说明的业务关联使用 `ON DELETE RESTRICT`。用户、正式事故、画像、已发布工单和历史默认不物理删除。金额类功能不在 P0 范围，避免引入预算和审批字段。

`created_at`、`updated_at` 为 `TIMESTAMPTZ`。需并发控制的可编辑表包含 `version INTEGER NOT NULL DEFAULT 1`。可选字段必须在数据字典中明确写 `NULL`，不能通过空字符串代替所有缺失值。所有固定状态、角色和类型代码在数据库中配置 CHECK 或相应字典外键，不能只依赖前端枚举。

### 7.2 行政区 `borough`

```text
borough_id        SMALLINT PRIMARY KEY
borough_name      VARCHAR(40) NOT NULL UNIQUE
display_name      VARCHAR(80) NULL
is_active         BOOLEAN NOT NULL DEFAULT TRUE
```

初始化五个行政区字典。行政区缺失用引用字段 NULL 表示，不虚构第六个真实行政区。显示名可修改，已经使用的标准名称及编号不得随意改动。

### 7.3 原始事故地点 `location`

```text
location_id       BIGINT PRIMARY KEY
location_key      TEXT NOT NULL UNIQUE
key_input         JSONB NOT NULL DEFAULT '{}' -- 稳定键输入及版本
borough_id        SMALLINT NULL REFERENCES borough
zip_code          VARCHAR(20) NULL
on_street_name    TEXT NULL
cross_street_name TEXT NULL
off_street_name   TEXT NULL
geom              geometry(Point, 4326) NULL
created_at        TIMESTAMPTZ NOT NULL
```

`location_key` 由标准化后的原始地点属性生成稳定摘要，同时保留摘要输入供校验。日期不属于地点键。全部地点信息缺失时，键中加入事故编号，防止把所有未知地点合并。

此表保存可追溯的观察地点。已有事故引用的地点字段原则上不就地覆盖。源地点修订时生成或匹配新记录，再修改事故引用。与交叉口的匹配结果放入下一张归属表。

正式表只保存一个空间对象作为坐标真值，查询视图通过 `ST_X`、`ST_Y` 提供经纬度。原始经纬度保存在 `raw_record`。不让经纬度和空间对象成为三份可以独立修改的数据。

### 7.4 标准交叉口 `intersection`

```text
intersection_id   BIGINT PRIMARY KEY
intersection_code VARCHAR(40) NOT NULL UNIQUE
borough_id        SMALLINT NULL REFERENCES borough
street_a          TEXT NOT NULL
street_b          TEXT NOT NULL
center_geom       geometry(Point, 4326) NOT NULL
status            VARCHAR(20) NOT NULL  -- CANDIDATE / CONFIRMED / REJECTED
source_method     VARCHAR(30) NOT NULL  -- DERIVED / MANUAL / EXTERNAL
is_active         BOOLEAN NOT NULL DEFAULT TRUE
supersedes_id     BIGINT NULL REFERENCES intersection
confirmation_note TEXT NULL
confirmed_by      BIGINT NULL REFERENCES app_user
confirmed_at      TIMESTAMPTZ NULL
created_at        TIMESTAMPTZ NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
version           INTEGER NOT NULL DEFAULT 1
```

候选交叉口是系统根据数据提出的对象，不等同于官方道路节点。确认时保存依据和确认人。`EXTERNAL` 仅用于以后确实接入外部交叉口资料的情况，P0 不伪造外部编号。

已经用于成功风险计算的交叉口，其身份、街道和中心坐标冻结。重大位置修正新建记录并用 `supersedes_id` 说明替代关系，停用旧记录。旧画像和工单仍保留原目标，不能悄悄迁移。

### 7.5 地点归属 `location_assignment`

```text
location_id       BIGINT PRIMARY KEY REFERENCES location
intersection_id   BIGINT NULL REFERENCES intersection
match_status      VARCHAR(30) NOT NULL
match_method      VARCHAR(40) NOT NULL
algorithm_version VARCHAR(40) NOT NULL
distance_m        NUMERIC(10,2) NULL
evidence          JSONB NOT NULL DEFAULT '{}'
reviewed_by       BIGINT NULL REFERENCES app_user
reviewed_at       TIMESTAMPTZ NULL
updated_at        TIMESTAMPTZ NOT NULL
version           INTEGER NOT NULL DEFAULT 1
```

`match_status` 取 `UNMATCHED`、`CANDIDATE`、`AUTO_MATCHED`、`MANUAL_CONFIRMED`、`REJECTED`。已匹配状态必须有交叉口引用。只有 `AUTO_MATCHED` 或 `MANUAL_CONFIRMED` 且交叉口为 `CONFIRMED` 的记录参与正式交叉口风险统计。

每个原始地点当前最多有一个归属。多个候选的详细证据可以放在 `evidence`，正式归属不保存成多个有效行。自动重跑不得覆盖人工确认结果。改派应写审计并增加分析数据版本。

### 7.6 事故 `collision`

```text
collision_id      BIGINT PRIMARY KEY
location_id       BIGINT NOT NULL REFERENCES location
crash_date        DATE NOT NULL
crash_time        TIME NULL
source_record_id  BIGINT NOT NULL UNIQUE REFERENCES raw_record
imported_at       TIMESTAMPTZ NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
```

仅写入完整发布的正式数据。来源记录修订时更新当前引用；旧来源仍在原始记录中。P0 不支持用户任意修改或删除公开事故事实。

### 7.7 涉事人员 `person`

```text
person_id         BIGINT PRIMARY KEY       -- 来源 unique_id
collision_id      BIGINT NOT NULL REFERENCES collision
source_person_id  TEXT NULL                -- 来源 person_id
source_vehicle_id TEXT NULL                -- 来源 vehicle_id，P0 无外键
person_type       TEXT NULL
person_injury     TEXT NULL
person_age        SMALLINT NULL
person_sex        TEXT NULL
source_record_id  BIGINT NOT NULL UNIQUE REFERENCES raw_record
updated_at        TIMESTAMPTZ NOT NULL
```

年龄异常由清洗规则记录并转换为 NULL，原始值保留。年龄的可接受范围由配置明确说明为质量检查规则，不将其包装为官方有效值范围。人员类别和伤亡状态先保留官方语义及未知值，显示层再做有来源的类别映射。

### 7.8 车辆类型 `vehicle_type`

```text
vehicle_type_id   BIGINT PRIMARY KEY
canonical_name    TEXT NOT NULL UNIQUE
display_name      TEXT NULL
is_active         BOOLEAN NOT NULL DEFAULT TRUE
```

大小写和空白标准化由配置控制。确有语义差异的车型不凭相似字符串合并。原始名称保留在原始记录中。字典显示名与来源归一化规则分开管理。

### 7.9 涉事车辆 `vehicle`

```text
vehicle_id        BIGINT PRIMARY KEY       -- 来源 unique_id
collision_id      BIGINT NOT NULL REFERENCES collision
source_vehicle_id TEXT NULL                -- 来源 vehicle_id
vehicle_type_id   BIGINT NULL REFERENCES vehicle_type
vehicle_year      SMALLINT NULL
travel_direction  TEXT NULL
pre_crash         TEXT NULL
point_of_impact   TEXT NULL
vehicle_damage    TEXT NULL
source_record_id  BIGINT NOT NULL UNIQUE REFERENCES raw_record
updated_at        TIMESTAMPTZ NOT NULL
```

P0 保留原报告的一项主要损坏字段。其他损坏字段可在 `raw_record` 查看，未来确需多值检索时再拆子表。不要把多个损坏值拼成逗号字符串后再用于关系查询。

### 7.10 事故原因 `contributing_factor`

```text
factor_id         BIGINT PRIMARY KEY
canonical_name    TEXT NOT NULL UNIQUE
display_name      TEXT NULL
is_active         BOOLEAN NOT NULL DEFAULT TRUE
```

空值表示来源未提供。`Unknown`、`Unspecified` 先保留各自来源含义，分析时可提供一个统一的未知原因分组，但不得丢掉原值。该处理比原报告的统一未知类别更保守，属于本期明确的清洗调整。[S2，§3、§5；本期实施决定]

### 7.11 事故原因槽位 `collision_factor`

```text
collision_id      BIGINT NOT NULL REFERENCES collision
factor_order      SMALLINT NOT NULL CHECK (factor_order BETWEEN 1 AND 5)
factor_id         BIGINT NOT NULL REFERENCES contributing_factor
PRIMARY KEY (collision_id, factor_order)
```

保留原报告最终主键。相同原因出现在多个车辆槽位时允许存在多行。按原因统计事故数量前，必须对 `(collision_id, factor_id)` 去重。

`factor_order` 代表 Crashes 原字段后缀的位置，不代表 Vehicles 的主键或稳定车辆序号。

### 7.12 事故伤亡汇总 `casualty_stat`

```text
collision_id        BIGINT PRIMARY KEY REFERENCES collision
persons_injured     INTEGER NULL
persons_killed      INTEGER NULL
pedestrians_injured INTEGER NULL
pedestrians_killed  INTEGER NULL
cyclists_injured    INTEGER NULL
cyclists_killed     INTEGER NULL
motorists_injured   INTEGER NULL
motorists_killed    INTEGER NULL
```

每个计数字段分别设置“NULL 或非负”约束。正式事故即使所有伤亡字段缺失，也生成一条全 NULL 的统计记录，不能将缺失自动填零。

不强制总伤亡等于各子类别相加。各项作为官方分别报告的数值保存，不用人员明细覆盖事故汇总。差异作为质量问题展示。[本期数据契约]

### 7.13 风险规则 `risk_rule`

```text
rule_id           BIGINT PRIMARY KEY
rule_code         VARCHAR(40) NOT NULL
version_no        INTEGER NOT NULL
rule_name         TEXT NOT NULL
weight_collision  NUMERIC(10,2) NOT NULL
weight_injured    NUMERIC(10,2) NOT NULL
weight_killed     NUMERIC(10,2) NOT NULL
weight_vru        NUMERIC(10,2) NOT NULL
threshold_medium  NUMERIC(12,2) NOT NULL
threshold_high    NUMERIC(12,2) NOT NULL
status            VARCHAR(20) NOT NULL  -- DRAFT / PUBLISHED / RETIRED
rationale         TEXT NOT NULL
created_by        BIGINT NULL REFERENCES app_user
created_at        TIMESTAMPTZ NOT NULL
UNIQUE (rule_code, version_no)
```

权重非负，阈值非负且高阈值严格大于中阈值。第一版使用原报告的权重和阈值。发布后的数值不可修改，只能创建新版本。[S2，§4]

### 7.14 风险计算批次 `risk_run`

```text
run_id            BIGINT PRIMARY KEY
request_id        UUID NOT NULL UNIQUE
request_hash      VARCHAR(64) NOT NULL    -- request-v1 SHA-256
rule_id           BIGINT NOT NULL REFERENCES risk_rule
period_start      DATE NOT NULL
period_end        DATE NOT NULL
input_revision    BIGINT NULL
status            VARCHAR(20) NOT NULL
input_manifest    JSONB NOT NULL DEFAULT '{}'
coverage_summary  JSONB NOT NULL DEFAULT '{}'
requested_by      BIGINT NOT NULL REFERENCES app_user
created_at        TIMESTAMPTZ NOT NULL
started_at        TIMESTAMPTZ NULL
finished_at       TIMESTAMPTZ NULL
worker_token      UUID NULL
lease_expires_at  TIMESTAMPTZ NULL
attempt_no        INTEGER NOT NULL DEFAULT 0
error_summary     TEXT NULL
CHECK (period_start < period_end)
```

状态取 `QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`。`input_revision` 取实际开始读取一致性快照时的版本，在最终发布时与结果一并写入，不能简单取用户提交请求时的版本。

`input_manifest` 保存来源文件哈希、已发布批次集合、清洗与地点匹配版本、代码版本及必要快照文件标识。JSONB 仅保存运行元数据，核心关联和周期仍使用明确字段。

### 7.15 风险画像 `risk_profile`

```text
profile_id                         BIGINT PRIMARY KEY
run_id                             BIGINT NOT NULL REFERENCES risk_run
intersection_id                    BIGINT NOT NULL REFERENCES intersection
collision_count                    BIGINT NOT NULL
injured_count                      BIGINT NOT NULL
killed_count                       BIGINT NOT NULL
vulnerable_road_user_count          BIGINT NOT NULL
incomplete_casualty_collision_count BIGINT NOT NULL
UNIQUE (run_id, intersection_id)
```

上面的伤亡合计保存已知值总和，另行记录缺少任一评分必需伤亡字段的事故数量。存在不完整记录时，界面显示“已知值合计，存在缺失”，不给出有效分数和等级。不得让缺失自动变成低风险。

约束计数非负，缺失事故数不大于事故总数。默认只为 `collision_count > 0` 的纳入交叉口生成画像。没有画像显示“该批次未生成结果”，不显示低风险。

周期、规则、风险分数和等级通过 `v_risk_profile` 视图提供，避免把可推导值分别人工维护。成功批次的画像只读。

### 7.16 角色 `role`

```text
role_id           SMALLINT PRIMARY KEY
role_code         VARCHAR(20) NOT NULL UNIQUE
role_name         VARCHAR(60) NOT NULL
```

固定初始化 ADMIN、MANAGER、VIEWER。权限矩阵定义在可测试的后端策略代码中，不允许前端自己决定角色能力。

### 7.17 用户 `app_user`

```text
user_id           BIGINT PRIMARY KEY
username          VARCHAR(80) NOT NULL
password_hash     TEXT NOT NULL
display_name      VARCHAR(80) NOT NULL
role_id           SMALLINT NOT NULL REFERENCES role
is_active         BOOLEAN NOT NULL DEFAULT TRUE
auth_version      INTEGER NOT NULL DEFAULT 1
created_at        TIMESTAMPTZ NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
version           INTEGER NOT NULL DEFAULT 1
```

建立 `lower(username)` 唯一索引。密码只保存现代密码哈希。修改密码、禁用/启用用户、变更角色或执行全会话退出时增加 `auth_version`。仍有OPEN、IN_PROGRESS或PENDING_REVIEW任务的执行人不得停用或变更任何角色。先按允许的业务动作处理任务。P0 只允许 OPEN 任务重新分配，其他任务先完成或由有权限者取消后另建任务。不删除历史关联。

### 7.18 治理任务 `governance_task`

```text
task_id           BIGINT PRIMARY KEY
task_code         VARCHAR(40) NOT NULL UNIQUE
request_id        UUID NOT NULL UNIQUE
request_hash      VARCHAR(64) NOT NULL    -- request-v1 SHA-256
profile_id        BIGINT NOT NULL REFERENCES risk_profile
title             VARCHAR(160) NOT NULL
description       TEXT NOT NULL
measure_type      VARCHAR(40) NOT NULL
priority          VARCHAR(20) NOT NULL
status            VARCHAR(30) NOT NULL
created_by        BIGINT NOT NULL REFERENCES app_user
assignee_id       BIGINT NULL REFERENCES app_user
due_date          DATE NULL
effective_on      DATE NULL
assessment_scope  JSONB NOT NULL
is_simulated      BOOLEAN NOT NULL DEFAULT TRUE
deleted_at        TIMESTAMPTZ NULL
created_at        TIMESTAMPTZ NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
version           INTEGER NOT NULL DEFAULT 1
```

P0 工单统一从风险画像建立。交叉口通过 `profile_id` 取得，不同时保存冗余的 `intersection_id`。手工指定一个没有任何画像的路口建单放到 P2。

`measure_type` 固定使用 `MARKING_MAINTENANCE`、`SIGNAL_REVIEW`、`PEDESTRIAN_FACILITY_REVIEW`、`FIELD_SURVEY`、`OTHER`，分别表示标线维护、信号配时检查、行人设施检查、现场调查及其他。`priority` 固定为 LOW、MEDIUM、HIGH、URGENT。工单分类不表示系统具有道路工程决策或实际施工授权。

`assessment_scope` 在建立任务时冻结评价用中心坐标、半径和选择理由。P0 只保存，P1 前后比较使用。`effective_on` 是演示措施生效的业务日期，可以与真实操作创建时间不同，但必须保留 `is_simulated` 提示。

`deleted_at` 仅用于删除草稿的逻辑标记。已发布任务通过取消处理，完成任务不能直接改回草稿。

### 7.19 治理记录与历史 `task_history`

```text
history_id        BIGINT PRIMARY KEY
task_id           BIGINT NOT NULL REFERENCES governance_task
sequence_no       INTEGER NOT NULL
request_id        UUID NOT NULL UNIQUE
request_hash      VARCHAR(64) NOT NULL    -- request-v1 SHA-256
event_type        VARCHAR(30) NOT NULL
from_status       VARCHAR(30) NULL
to_status         VARCHAR(30) NOT NULL
actor_id          BIGINT NOT NULL REFERENCES app_user
note              TEXT NOT NULL
changed_fields    JSONB NOT NULL DEFAULT '{}'
created_at        TIMESTAMPTZ NOT NULL
UNIQUE (task_id, sequence_no)
```

事件包括 `CREATE`、`EDIT`、`PUBLISH`、`ASSIGN`、`START`、`PROGRESS`、`SUBMIT`、`APPROVE`、`REJECT`、`CANCEL`、`DELETE_DRAFT`。无状态改变的事件允许前后状态相同。

P0 将执行记录和状态历史合并在本表，避免两套记录相互不一致。记录只追加，补充错误说明使用新记录。`sequence_no` 与工单修改后的 `version` 对齐，创建时均为 1。

### 7.20 导入批次 `import_batch`

```text
batch_id          BIGINT PRIMARY KEY
request_id        UUID NOT NULL UNIQUE
request_hash      VARCHAR(64) NOT NULL    -- request-v1 SHA-256
manifest_hash     TEXT NOT NULL
cleaning_version  VARCHAR(40) NOT NULL
input_manifest    JSONB NOT NULL
requested_start   DATE NULL
requested_end     DATE NULL
status            VARCHAR(30) NOT NULL
rows_read         BIGINT NOT NULL DEFAULT 0
rows_accepted     BIGINT NOT NULL DEFAULT 0
rows_rejected     BIGINT NOT NULL DEFAULT 0
rows_skipped      BIGINT NOT NULL DEFAULT 0
created_by        BIGINT NOT NULL REFERENCES app_user
created_at        TIMESTAMPTZ NOT NULL
started_at        TIMESTAMPTZ NULL
finished_at       TIMESTAMPTZ NULL
published_revision BIGINT NULL
worker_token      UUID NULL
lease_expires_at  TIMESTAMPTZ NULL
attempt_no        INTEGER NOT NULL DEFAULT 0
error_summary     TEXT NULL
```

一个批次可以包含 Crashes、Person、Vehicles 三份输入，或明确声明的单源更新。各文件来源、哈希、字段、行数和日期范围记录在 manifest。不能把三个文件的不同范围隐瞒为同一范围。

状态取 `UPLOADED`、`VALIDATING`、`READY`、`PUBLISHING`、`SUCCEEDED`、`FAILED`、`CANCELLED`。相同 manifest 和清洗版本已经成功发布时，返回既有结果或明确标记跳过，不重复插入事故事实。请求幂等由 `request_id` 控制，内容重复判断由 manifest 和版本控制。

### 7.21 原始记录 `raw_record`

```text
raw_record_id     BIGINT PRIMARY KEY
batch_id          BIGINT NOT NULL REFERENCES import_batch
source_kind       VARCHAR(12) NOT NULL   -- CRASHES / PERSON / VEHICLES
row_no            BIGINT NOT NULL
source_key        TEXT NULL
payload           JSONB NOT NULL
row_hash          TEXT NOT NULL
validation_status VARCHAR(20) NOT NULL
created_at        TIMESTAMPTZ NOT NULL
UNIQUE (batch_id, source_kind, row_no)
```

`validation_status` 固定为 UNVALIDATED、ACCEPTED、REJECTED、SKIPPED。原始 payload 不修改，字段修订通过新的输入批次表达。相同来源主键的重复行也要先保留，以便报告冲突，不能因在暂存层设置来源主键唯一而悄悄丢弃。

原始 CSV 文件及其 SHA-256 保存在本地数据目录。JSONB 便于检查字段，不能替代对原文件的保存。

### 7.22 数据问题 `data_issue`

```text
issue_id          BIGINT PRIMARY KEY
batch_id          BIGINT NOT NULL REFERENCES import_batch
raw_record_id     BIGINT NULL REFERENCES raw_record
issue_code        VARCHAR(50) NOT NULL
severity          VARCHAR(10) NOT NULL   -- INFO / WARNING / ERROR
field_name        TEXT NULL
description       TEXT NOT NULL
status            VARCHAR(20) NOT NULL   -- OPEN / ACKNOWLEDGED / RESOLVED
resolution_note   TEXT NULL
resolved_by       BIGINT NULL REFERENCES app_user
resolved_at       TIMESTAMPTZ NULL
created_at        TIMESTAMPTZ NOT NULL
```

批次级问题可以不关联单条原始记录。`RESOLVED` 仅表示问题得到有记录的处理，不能仅通过点击按钮把拒绝行计为正式数据。重清洗和重新发布应形成新批次或有明确的重试记录。

### 7.23 审计 `audit_log`

```text
audit_id          BIGINT PRIMARY KEY
actor_id          BIGINT NULL REFERENCES app_user
action            VARCHAR(60) NOT NULL
entity_type       VARCHAR(50) NOT NULL
entity_id         TEXT NULL
request_id        UUID NULL
details           JSONB NOT NULL DEFAULT '{}'
created_at        TIMESTAMPTZ NOT NULL
```

记录账户变更、交叉口确认、归属修正、规则发布和批次发布。工单业务历史以 `task_history` 为主要依据，不重复存放整份工单内容。

禁止记录明文密码、密码哈希、JWT、API 令牌和完整数据库连接字符串。

### 7.24 分析数据版本 `dataset_state`

```text
state_id          SMALLINT PRIMARY KEY CHECK (state_id = 1)
revision          BIGINT NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
last_change_note  TEXT NOT NULL
```

单行保存影响分析结果的数据版本。成功发布数据、调整地点归属、确认或停用分析交叉口时，在同一事务中增加版本。纯用户显示名修改和工单处理不增加事故分析版本。

版本号用于标识和判断结果是否过期，不等于数据库能够按任意版本直接查询历史数据。复现历史风险结果还需要保留成功画像、输入文件、参数和映射快照。

## 8. 完整性、规范化与派生数据

### 8.1 不能遗漏的约束

迁移中建立所有主键和外键，字典唯一约束，计数非负约束，周期有效约束，规则阈值顺序约束，以及每次计算每个交叉口唯一的约束。

关联已有人员、车辆或工单历史的实体采用限制删除。禁止为演示方便关闭外键。导入发现无父事故的子记录时留在暂存层并报告原因。

`casualty_stat.collision_id` 的主键和外键只能保证一条事故至多对应一条统计，不能单独保证每起事故至少有一条统计。发布事务必须同时写入两表，并执行反连接校验。为体现数据库约束，可实现提交时检查的延迟约束触发器，保证正式事故都有对应统计行。

### 8.2 3NF 文档要求

对正式基础关系写出候选键、业务函数依赖和分解理由。不能仅凭存在自增主键就宣称满足 3NF。重点解释以下设计。

- 车辆类型名称保存在字典表，车辆引用其编号。
- 事故原因名称保存在字典表，事故槽位引用原因编号。
- 事故来源时间不重复抄入人员和车辆正式表，原始重复值保存在暂存层供一致性检查。
- 工单通过画像定位交叉口，不重复保存可由画像确定的交叉口编号。
- 风险周期和规则放在运行批次，画像保存该批次下的交叉口指标。
- 风险分数和等级属于派生值，以视图统一生成。

原报告已讨论风险等级应由规则维护。本期进一步区分基础表和分析读取结果。若 P1 使用物化视图保存分数、等级和组合显示字段，应写明这是可重建的派生存储，不把它当作所有字段独立满足 3NF 的证明。[S2，§3]

原始 JSON、不可变事件快照和聚合结果也需要在报告中说明其用途。不能把全部业务字段塞进 JSONB 后跳过关系设计。

### 8.3 必须有实际用途的数据库机制

P0 至少实现以下机制。

| 机制 | 用途 |
|---|---|
| 普通视图 | 风险分数及等级、事故基础查询、工单显示字段 |
| 事务 | 导入发布、任务变更与历史同时写入、完整风险结果发布 |
| 数据库函数 | 统一执行工单状态变更，检查版本并追加历史 |
| 触发器或受限权限 | 阻止历史修改、阻止已发布规则数值修改 |
| 延迟检查或发布校验 | 保证正式事故具有伤亡统计记录 |
| 复合与空间索引 | 时间地点查询、原因查询、附近事故查询 |

数据库函数负责关键状态及数据一致性，服务层负责身份和对象权限。数据库连接只由受信后端使用。不要声称函数参数中的 `actor_id` 本身就能认证真实用户。

## 9. 数据导入、清洗与发布流程

### 9.1 分阶段处理

导入先落原始文件和暂存记录，再校验，最后发布到正式关系表。下载和暂存失败不能影响现有正式数据。

| 阶段 | 行为 | 可见结果 |
|---|---|---|
| 接收 | 校验文件类型、大小及路径，计算哈希，创建批次 | UPLOADED，已有文件 manifest |
| 暂存 | 分块读取 CSV 或 JSON，保留源记录和行号 | 原始记录可追溯 |
| 校验 | 字段、主键、数据类型、重复、范围、父子关系检查 | 数据问题清单和计数 |
| 预览 | 呈现拟新增、更新、跳过和拒绝的数据数量 | READY，管理员可决定发布 |
| 发布 | 在一个正式发布事务内写入基础表、关联表及版本 | SUCCEEDED 或整体回滚 |
| 后续 | 标记已有分析结果可能过期，允许提交新的风险计算 | 原结果仍可读，不直接覆盖 |

原始大文件可分块提交到暂存层。P0 的正式发布以选定范围的原子事务完成，不能每写一张正式表就单独提交。规模过大时先缩小批次。分区切换等复杂发布方式不在 P0 范围。

### 9.2 清洗规则

| 情况 | 处理 |
|---|---|
| 缺少事故主键或事故日期 | 该事故行拒绝进入正式表，记录 ERROR |
| 缺少子表主键或父事故编号 | 子行拒绝，保留原始记录 |
| 选定范围外的有效行 | 标记跳过，明确原因，不算校验失败 |
| 子表引用不存在的事故 | 区分范围外与真正缺父记录，隔离或补取，不伪造父行 |
| 数值字段为空 | 保存 NULL，不默认填零 |
| 伤亡人数为负或无法解析 | 保存原值，规范化字段转 NULL，并记录 WARNING |
| 经纬度无效、只有一个值、为异常零坐标 | 地点保留，`geom` 为空，记录质量问题 |
| 有效坐标但远离研究范围 | 标记范围异常，默认不进入交叉口分析，不能改写为纽约中心 |
| 同批次相同来源键且内容相同 | 保留暂存行，正式处理一次，其余记为重复跳过 |
| 同批次相同来源键但内容冲突 | 不任意选最后一行，记录冲突并阻止该组发布，要求有记录的处理策略 |
| 人员表或车辆表的日期与事故主表冲突 | 正式查询使用事故主表日期，保留冲突记录 |
| 车型、街道的空白和大小写差异 | 按有版本的映射规则标准化，原值保留 |

“研究范围异常”是项目质量判断，不能把一个简化经纬度矩形等同于纽约行政边界。使用边界数据时记录具体来源，未使用时明确标为矩形预筛。

### 9.3 写入顺序与幂等

发布前锁定 `dataset_state` 单行，序列化影响分析数据的写入。根据暂存校验结果，先处理字典和地点，再写事故及伤亡汇总、事故原因槽位，最后写车辆和人员。

来源键相同且内容未变时不更新正式数据。内容改变时执行受控 UPSERT，并保留新旧原始输入。一次事故记录的伤亡统计和原因槽位在同一事务更新。

更新 Crashes 时应按该行完整的 1—5 原因字段重建对应槽位。某个原槽位已变为空时必须移除旧关联，不能只插入新原因而留下旧值。前提是输入模式已经核实这些列完整存在，不能把导出缺列误解成源值被清空。

一般增量导入不根据“本批次没出现”删除旧事故或明细。只有显式完整替换模式、确定的范围以及完整性证据才能支持删除同步；P0 不实现这种删除模式。

在提交前检查无孤立外键、正式事故均有伤亡汇总、批次计数能够解释。提交时同时增加 `dataset_state.revision`、填写 `published_revision` 并写审计。

同一输入重复发布后，事故数量、人员数量、车辆数量和统计值应不增加。相同 `request_id` 的重试返回同一操作结果。

### 9.4 计数定义

`rows_read` 是原始输入行数。对于完成校验的批次，满足 `rows_read = rows_accepted + rows_rejected + rows_skipped`。新增或更新多少正式关系行另行记录在 manifest 的发布摘要，不与原始行数混用。一条 Crashes 行可能产生多张表中的记录。

缺少坐标等 WARNING 可以伴随接受行。ERROR 的行是否阻断整批发布由清洗策略决定，默认允许明确隔离无效行，但必须在预览中显示。涉及主键内容冲突、必需列缺失或无法确定范围时，整批不得发布。

### 9.5 作业恢复

P0 只启动一个 worker，作业在数据库中领取并记录执行令牌及租期。长任务续租，完成时再次检查令牌，防止过期 worker 提交旧结果。

worker 重启时检查租期已失效的作业，标记失败并允许有记录的重试。暂存数据可复用，正式发布事务必须整体成功或整体回滚。风险画像的失败批次不能成为默认查询结果。

数据库连接丢失、磁盘满、文件缺失和解析中断都应有可理解的错误摘要。不能把 traceback 或服务器路径直接完整返回给普通用户。

## 10. 标准交叉口识别与地点匹配

### 10.1 分开显示观察点与管理对象

地图提供事故观察点和标准交叉口两类图层。没有经纬度的事故仍可在列表和行政区统计中查询。没有确认归属的事故可以展示为观察点，但不混入正式交叉口风险排名。

保留统计覆盖信息，包括全部事故数、有坐标事故数、已匹配到确认交叉口的事故数、未匹配数量和评分字段完整数量。交叉口排名的分母和行政区总体事故数量可能不同，界面需要说明。

### 10.2 P0 匹配方案

首先标准化行政区与街道名称。街道对按固定顺序存储，保证 A/B 和 B/A 可以识别为同一候选组合。邮编可辅助核查，不作为必须相同的交叉口身份条件。

对于已经确认的交叉口，只有街道组合相符、行政区相容且距离在阈值内时才考虑自动归属。满足条件的交叉口恰好一个时可设为 `AUTO_MATCHED`。存在多个候选、道路层级疑问或名称冲突时保持待确认，不仅按最近距离强行归属。

对尚未匹配的、具有两条街道和有效坐标的地点，按行政区及标准化街道对分组生成候选。使用固定排序和固定锚点半径归组，不采用可能把多个路口连续串起来的无边界扩张。候选中心记录为来源观察点或有明确计算方法的代表点，并标明系统推导。

默认候选与匹配半径为 50 米，这是可调整的课程参数，尚未经过准确率验证。生成候选后先人工检查一组代表性路口，保存复核说明。P1 可以比较 20、50、80 米下的匹配覆盖和人工核查结果，不能在没有标签时报告“准确率”。

### 10.3 空间计算约定

空间对象使用 SRID 4326。创建点时参数顺序是经度、纬度。GeoJSON 的坐标顺序同样为经度、纬度，地图组件接收的顺序按其 API 明确转换并测试。

附近查询使用 `ST_DWithin` 的 geography 形式，距离单位为米。经纬度 geometry 的角度单位不能直接当作米。[W4]

下面是迁移完成后的参考 SQL，参数由驱动绑定。

```sql
SELECT l.location_id
FROM location AS l
WHERE l.geom IS NOT NULL
  AND ST_DWithin(
    l.geom::geography,
    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
    :radius_m
  );
```

必须建立与 `geom::geography` 表达式对应的 GiST 索引，不能只创建 geometry 索引就宣称上面的距离查询一定使用它。具体计划由 EXPLAIN 验证。

### 10.4 人工修正

管理人员可以确认候选、拒绝候选和调整地点归属。修改提交时提供版本号、目标交叉口和原因，后端验证权限、目标状态及版本。

已冻结交叉口的位置更正按新建替代对象处理。地点改派会增加数据版本。旧画像保留，界面提示需生成新版本分析。不得修改旧画像来制造看起来连续的结果。

## 11. 风险识别、规则与计算快照

### 11.1 风险含义

本项目识别的是在给定数据范围内，按指定规则得到的历史碰撞风险指标。它不表示未来事故概率，也未按交通流量、行人流量或行驶里程归一化。界面避免把分数叫作预测概率。

原数据中的一般受伤统计不能自动解释为“重伤人数”。没有使用额外严重程度字段和相应定义时，不生成重伤指标。

### 11.2 第一版规则

继承上学期规则。[S2，§4]

```text
N = 纳入该交叉口和周期的事故数
I = 受伤人数
K = 死亡人数
V = 行人受伤 + 行人死亡 + 骑行者受伤 + 骑行者死亡

S = 1 * N + 3 * I + 10 * K + 5 * V

LOW     当 S < 10
MEDIUM  当 10 <= S < 30
HIGH    当 S >= 30
UNKNOWN 当评分所需伤亡字段存在缺失
```

V 中的人员可能已经计入 I 或 K，因此该规则有意给行人和骑行者额外权重。显示分项贡献时说明这一点，不能声称四项代表互不重叠的人员群体。

权重和阈值仅为原课程方案的初始规则，未经现实效果验证。规则变更创建新版本，不覆盖历史版本。不同长度统计周期的原始分数不能直接据此说明风险升降。

### 11.3 计算步骤

提交计算请求时先验证周期和规则，创建 `risk_run`。worker 在短事务中领取任务，再使用只读的 PostgreSQL `REPEATABLE READ` 事务读取分析数据，保证多个读取看到同一快照。[W6a]

按两个阶段执行，避免心跳更新与长事务共同修改作业状态行。

**读取与计算阶段**。在只读快照中取得 `dataset_state.revision`、来源清单和地点归属。选定事故日期范围，仅纳入确认交叉口及有效归属。每起事故保留一行，连接一对一伤亡汇总，再由 SQL 按交叉口计算指标和覆盖摘要。将已经聚合的结果、参数及匹配快照写入受控中间文件，保存行数与哈希。该阶段不修改 `risk_run`，心跳通过其他短事务续租。

**结果发布阶段**。快照读取结束后，使用独立写事务锁定运行记录，检查 worker 令牌及中间文件完整性。批量写入全部画像，同时填写输入版本、manifest、覆盖摘要及 SUCCEEDED 状态。整个结果发布事务成功后才对用户可见。

计算阶段失败时没有正式画像。发布阶段失败时整批画像回滚，另行记录失败状态。查询 API 只返回成功批次，不让用户看到一半交叉口有数据的结果。重复发布必须检查批次状态及唯一约束，不能重复累计。

数据库版本号只用于标识快照，不支持时光查询。映射快照和输入 manifest 必须来自同一读取快照，并通过原子落盘保存。文件保存失败时不能宣称该批次满足完整复现要求。

读取结束后可能有新数据提交。本次结果仍对应已经记录的输入版本，界面通过 `is_stale` 呈现与当前数据的差异，不把发布时刻伪装成数据采集时刻。

### 11.4 SQL 视图与分数

实现 `v_risk_profile`，连接 `risk_profile`、`risk_run`、`risk_rule` 和 `intersection`，提供周期、规则名、分项指标、分数、等级及 `is_stale`。

先在一个中间 CTE 中计算分数，再在外层 CASE 生成等级，避免前端、后端和多个 SQL 文件各实现一遍规则。若 `incomplete_casualty_collision_count > 0`，分数为 NULL，等级为 UNKNOWN。

`is_stale` 通过运行输入版本与当前分析版本比较。这个判断可以保守地标记过期，即使修改发生在另一时间范围，也不伪称已经进行精确影响分析。

### 11.5 规则最小测试

使用明确标记的单元测试数据，覆盖以下结果。

| 输入 | 预期 |
|---|---|
| N=2，I=1，K=0，V=1 | S=10，MEDIUM |
| N=4，I=2，K=1，V=2 | S=30，HIGH |
| S=9 | LOW |
| S=10 | MEDIUM |
| S=29 | MEDIUM |
| S=30 | HIGH |
| 任一评分必需字段缺失 | score=NULL，UNKNOWN |
| 同一事故有多条车辆和原因记录 | 事故和伤亡合计不因此增加 |

测试数据不混入真实数据数据库的正式分析范围。

## 12. 治理任务业务与事务设计

### 12.1 状态

| 当前状态 | 可执行动作 | 下一状态 | 必要条件 |
|---|---|---|---|
| 无 | 创建 | DRAFT | 已成功画像、确认交叉口、有效操作者 |
| DRAFT | 修改 | DRAFT | 创建者或管理员，版本正确 |
| DRAFT | 发布 | OPEN | 内容完整，选择启用的管理人员为执行人 |
| DRAFT | 删除草稿 | DRAFT，写 `deleted_at` | 创建者或管理员，保留历史 |
| OPEN | 重新分配 | OPEN | 创建者或管理员，记录原因 |
| OPEN | 开始执行 | IN_PROGRESS | 当前执行人 |
| IN_PROGRESS | 写执行记录 | IN_PROGRESS | 当前执行人，记录内容非空 |
| IN_PROGRESS | 提交复核 | PENDING_REVIEW | 当前执行人，提交说明非空 |
| PENDING_REVIEW | 复核通过 | COMPLETED | 创建者或管理员，且不是执行人 |
| PENDING_REVIEW | 退回 | IN_PROGRESS | 同上，退回意见非空 |
| DRAFT / OPEN / IN_PROGRESS / PENDING_REVIEW | 取消 | CANCELLED | 创建者或管理员，原因非空 |

P0 不允许完成后重开，不允许用通用 PATCH 任意设置 `status`，不允许执行人给自己通过复核。需要补充工作时创建新任务并在说明中引用旧任务。

已经逻辑删除或处于 COMPLETED、CANCELLED 的任务禁止普通修改。终止后的备注可在 P1 设计独立只追加行为，P0 不开放。

### 12.2 任务建立条件

P0 从具体画像建立任务，保持建立依据可追溯。UNKNOWN画像仅允许FIELD_SURVEY调查DRAFT，不得发布或改建其他措施；补齐数据后基于新画像另建任务。LOW 或 MEDIUM 画像建立任务需要说明理由，系统不自动禁止人工调查。

创建时冻结 `profile_id`、评价范围和是否模拟。发布后不允许替换依据画像。后续风险有新版本时，只在页面展示新结果，不篡改旧任务的建立依据。

### 12.3 原子变更与并发

客户端发送 `expected_version` 和 `request_id`。服务层完成认证后，在同一数据库事务调用受控函数。函数锁定任务行，重新校验操作者仍启用、角色及任务内身份有效，再检查当前状态和版本、更新任务、增加版本并写入历史。

```text
change_task(
  task_id,
  expected_version,
  action,
  actor_id,
  request_id,
  payload
)
```

同一 request_id 的相同请求返回已有结果。相同 request_id 携带不同内容时返回冲突。版本不一致返回 HTTP 409，前端提示重新加载，不自动覆盖其他人的修改。

任何一步失败，任务和历史一起回滚。历史插入失败时不能留下已经改变的状态。历史序号与修改后的任务版本一致。

应用数据库角色不直接修改工单状态和历史，通过函数执行。使用 SECURITY DEFINER 时固定安全的 `search_path`，限定对象名称，撤销 PUBLIC 执行权限。不能把任意动态 SQL 传入数据库函数。

行锁行为和事务隔离以 PostgreSQL 文档为依据，测试必须使用两个独立数据库连接。[W6a、W6b]

### 12.4 并发验收场景

两名有权限的用户读取版本 3，同时提交不同修改。只有一项成功变为版本 4，另一项返回 409。历史只增加一条。后者重新获取版本后可以重新提交。

同一执行人因网络重试发送同一提交请求，状态只变更一次，历史只增加一次。构造历史写入失败，任务状态应保持原值。

## 13. 查询统计与治理前后比较

### 13.1 统一事故统计口径

所有事故次数和事故层面伤亡统计先构造每起事故一行的基础数据集。车辆和原因筛选使用 EXISTS，或先去重事故编号再关联。

```sql
SELECT
  COUNT(*) AS collision_count,
  SUM(s.persons_injured) AS known_injured_count,
  COUNT(*) FILTER (WHERE s.persons_injured IS NULL) AS injured_missing_count
FROM collision AS c
JOIN casualty_stat AS s ON s.collision_id = c.collision_id
WHERE c.crash_date >= :date_from
  AND c.crash_date < :date_to
  AND EXISTS (
    SELECT 1
    FROM vehicle AS v
    WHERE v.collision_id = c.collision_id
      AND v.vehicle_type_id = :vehicle_type_id
  );
```

这段 SQL 是迁移完成后的参考查询，不代表当前已经运行。没有已知伤亡值时 SUM 可能为 NULL，API 应保留“无已知值”语义。

不要把事故、人员、车辆和事故原因全部直接 JOIN 后再 SUM 伤亡。`COUNT(DISTINCT collision_id)` 只能修复事故计数，不能同步修复已经放大的 SUM。`SUM(DISTINCT persons_injured)` 也不正确，不同事故可能恰好有相同伤亡人数。

### 13.2 统计模块

| 模块 | 必须展示的内容 | 特别说明 |
|---|---|---|
| 行政区 | 事故数、已知伤亡数、缺失统计 | 缺失行政区作为未知组保留 |
| 时间趋势 | 按月事故数、伤亡数 | 空月份补零仅限确认有数据覆盖的月份 |
| 时段 | 小时段分布 | 缺少事故时间单列未知，不归入零点 |
| 原因 | 各原因涉及的不同事故数 | 先按事故和原因去重，各组可能重叠 |
| 车辆类型 | 涉事车辆记录数、涉及的不同事故数 | 两种指标分开命名 |
| 人员 | 按来源类别和伤亡状态统计 | 明确这是人员明细口径，不与 Crashes 汇总强行一致 |
| 风险 | 指定周期及规则版本的等级、排名、分项贡献 | 显示纳入范围、覆盖率和过期标记 |
| 工单 | 状态、负责人、处理情况 | 仅展示系统模拟业务，不包装为真实城市治理绩效 |

原因或车型分组中的同一事故可能属于多个组，因此组别事故数之和可能超过全体不同事故数。界面不能把这些组直接画成互斥占比饼图。

### 13.3 P1 治理前后描述性比较

只有任务已完成且设置 `effective_on` 时允许生成比较。使用任务创建时冻结的空间中心和半径，按原始事故点进行同范围筛选。这个范围是评价用圆形范围，与建立画像时的交叉口归属范围可能不同，页面必须分别说明。

默认比较生效前 90 天与生效后跳过 7 天再观察 90 天。90 天及 7 天均为演示参数，可调整，但每份导出保留准确日期、空间范围和规则版本。

比较使用同一个当前数据快照和相同字段口径。确认两段均有完整来源范围覆盖后，才计算数量变化。数据文件的最小和最大日期本身不足以证明中间没有缺页或缺月份，必须结合导入 manifest 的完整性校验。

基期数量为 0 时不计算百分比变化，返回 NULL。后期数据尚未覆盖时显示“观察期数据不足”，不能填 0 并报告全部减少。

所有比较标注“课程模拟工单，描述性统计，不支持因果效果判断”。不将日期前后变化直接归因于治理措施。未匹配坐标、缺失值、季节性和交通暴露差异都作为限制说明，不生成未经验证的治理效果结论。

## 14. 物理设计与性能实验

### 14.1 初始索引方案

迁移先建立有明确查询用途的索引，再用实际执行计划调整。主键和唯一约束已覆盖的索引不重复创建。

| 对象 | 初始索引 | 服务的查询 |
|---|---|---|
| collision | `(crash_date DESC, collision_id DESC)` | 日期筛选、稳定分页 |
| collision | `(location_id, crash_date)` | 地点及日期范围查询 |
| location | `(borough_id, location_id)` | 行政区筛选 |
| location | `GiST(geom)`，非空行 | 地图矩形范围与空间关系查询 |
| location | `GiST((geom::geography))`，非空行 | 以米为单位的距离查询 |
| intersection | `GiST(center_geom)` | 交叉口地图筛选 |
| location_assignment | `(intersection_id, location_id)` | 从交叉口查询关联地点 |
| person | `(collision_id)` | 事故人员明细 |
| vehicle | `(collision_id)`、`(vehicle_type_id, collision_id)` | 明细及车型筛选 |
| collision_factor | `(factor_id, collision_id)` | 按原因查事故 |
| risk_profile | 唯一索引 `(run_id, intersection_id)` | 单次运行结果及幂等 |
| risk_profile | `(intersection_id, run_id DESC)` | 路口历史画像 |
| governance_task | `(assignee_id, status, updated_at DESC)`，未删除行 | 我的待办 |
| governance_task | `(profile_id)` | 画像相关工单 |
| task_history | 唯一索引 `(task_id, sequence_no)` | 工单完整历史 |
| raw_record | `(batch_id, source_kind, source_key)` | 原始数据追踪及重复检查 |
| data_issue | `(batch_id, status)` | 批次问题列表 |

这些是候选初始设计，不保证每次查询一定选择索引。低选择性条件或小表使用顺序扫描可能合理。`crash_time` 和只有三四个值的等级字段不默认单独建索引。

默认风险等级在视图中计算，不能像普通表列一样直接给普通视图建索引。P1 若证明排序或筛选确有瓶颈，可建立可重建的物化读取视图，再评估相应索引。

### 14.2 必做性能实验

| 编号 | 场景 | 比较内容 |
|---|---|---|
| B01 | 日期范围事故列表 | 无对应二级索引与日期复合索引 |
| B02 | 地点加日期查询 | 单列索引与地点日期复合索引 |
| B03 | 附近事故查询 | 相同 geography 距离谓词，无匹配空间索引与有匹配空间索引 |
| B04 | 复杂车型或原因统计 | 语义相同的去重子查询、EXISTS 或预聚合查询方案 |
| B05，P1 | 多次重复读取风险结果 | 普通查询与维护成本明确的物化结果 |

无索引基线在独立实验数据库执行，保留主键、唯一约束和外键。不能为了制造差距破坏完整性约束。不要在正在演示的数据库上删除索引或执行破坏性实验。

SQL 改写前后必须通过结果一致性检查。错误的多表 SUM 查询只用于正确性反例，不能作为“优化前正确业务实现”的性能基线。

### 14.3 实验记录格式

每组实验记录代码提交、数据库和扩展版本、CPU、内存、存储、容器资源限制、来源文件哈希、事故及各子表行数、查询参数、相关索引和执行计划。

建议每个条件预热 3 次，测量至少 20 次，记录中位数、P95 和返回结果摘要。A/B 条件交替执行，说明缓存条件，不用一次快慢差异作结论。没有真正控制冷缓存时，不把实验叫作冷缓存测试。

保存 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` 和普通查询实际耗时。EXPLAIN ANALYZE 会执行查询，也有测量开销，应与完整请求耗时分开记录。[W5]

```text
benchmarks/results/<run_name>/
  environment.json
  dataset_manifest.json
  query_parameters.json
  correctness.json
  timings.csv
  plans/
  summary.md
```

数据规模可分为 1 万、5 万和 10 万起真实事故，前提是实际取得对应范围。人员、车辆随事故集合一致抽取。数据不足时如实使用现有规模，不复制真实行后冒充更多真实事故。

### 14.4 应用性能目标

以下为本计划的目标，尚无实测结果。M0 记录本机配置后可调整。

| 场景 | 初始目标 |
|---|---|
| 普通分页查询 | 本地开发机、已预热、单用户条件下 P95 不超过 1 秒 |
| 常用聚合统计 | 同上，P95 不超过 2 秒，必要时限制日期范围 |
| 地图查询 | 同上，P95 不超过 2 秒，严格限制返回点数量 |
| 创建和变更任务 | 同上，P95 不超过 1 秒，事务一致性优先 |
| 导入和风险计算 | 异步执行，显示状态，不阻塞页面等待整个计算结束 |

未达到目标时记录瓶颈和实际结果。目标数值不是课程评分保证，也不能提前填入最终测试报告。

## 15. 后端 API 契约

### 15.1 通用规范

统一前缀 `/api/v1`。ID 使用字符串，日期使用 ISO 格式，系统时刻使用带偏移的 ISO 时间，风险分数等 Decimal 值用字符串或 NULL 返回。

列表默认每页 20 条，最大 100 条，排序字段白名单化并增加主键稳定排序。事故大范围翻页支持基于 `(crash_date, collision_id)` 的游标。游标中关联筛选条件摘要，筛选改变后重新查询。

精确总数可能较耗时，可以通过 `include_total` 参数选择查询。未计算总数时返回 NULL，不能把当前页行数充当总数。

参考成功响应如下。

```json
{
  "data": {
    "items": [],
    "next_cursor": null,
    "total": null
  },
  "meta": {
    "request_id": "00000000-0000-4000-8000-000000000001",
    "data_revision": "12",
    "source_scope": "official_collision_data"
  }
}
```

参考错误响应如下。

```json
{
  "error": {
    "code": "TASK_VERSION_CONFLICT",
    "message": "任务已被其他用户修改，请刷新后重试。",
    "details": {"current_version": 4}
  },
  "meta": {"request_id": "00000000-0000-4000-8000-000000000001"}
}
```

示例版本和 ID 仅说明格式。未认证返回 401，无权限返回 403，资源不存在返回 404，版本或幂等冲突返回 409，参数错误返回 422，异步任务创建返回 202。

### 15.2 身份接口

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/auth/login` | 验证账户密码，返回短期访问令牌 |
| GET | `/auth/me` | 返回当前用户、角色和权限摘要 |
| POST | `/auth/logout` | 使当前用户已有会话版本失效，前端清除令牌 |
| POST | `/auth/change-password` | 验证旧密码并更新哈希及认证版本 |
| GET / POST | `/users` | 管理员查询、创建用户 |
| PATCH | `/users/{user_id}` | 管理员修改显示名、启停及角色，检查版本 |

P0 的退出采用该用户全部令牌失效策略，界面说明会同时退出其他设备。账户没有公共注册入口。

### 15.3 导入与维护接口

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/imports` | 上传文件及范围声明，创建批次，自动进入暂存与校验流程 |
| GET | `/imports` | 批次列表及状态 |
| GET | `/imports/{batch_id}` | manifest、计数、错误摘要和发布版本 |
| GET | `/imports/{batch_id}/issues` | 分页查看问题 |
| POST | `/imports/{batch_id}/publish` | 管理员确认 READY 批次，提交发布请求 |
| PATCH | `/data-issues/{issue_id}` | 确认或记录处理结果，不能直接改写原始事实 |
| GET / PATCH | `/dictionaries/{kind}` | 受控读取或维护字典显示信息 |
| GET | `/audit-logs` | 按权限查询审计 |

上传接口不接受任意服务器文件路径或任意远程 URL。大文件通过受控 CLI 读取已挂载目录，网页上传设置明确大小上限，默认建议 256 MB。

worker 自动领取已上传批次进行校验，校验完成停在 READY。只有有权限的发布请求才将其变为 PUBLISHING，worker 再执行正式写入。

### 15.4 事故、地图和交叉口接口

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/collisions` | 时间、行政区、街道、车型、原因等联合筛选 |
| GET | `/collisions/{collision_id}` | 事故基础信息和伤亡汇总 |
| GET | `/collisions/{collision_id}/persons` | 按权限返回人员明细 |
| GET | `/collisions/{collision_id}/vehicles` | 车辆明细 |
| GET | `/map/collisions` | 日期及矩形范围内的事故点 |
| GET | `/intersections` | 候选或确认交叉口列表 |
| GET | `/intersections/{intersection_id}` | 档案、关联地点、风险历史和工单摘要 |
| POST | `/intersection-candidates/generate` | 在受控范围生成候选 |
| POST | `/intersections/{intersection_id}/confirm` | 确认候选及依据 |
| POST | `/intersections/{intersection_id}/reject` | 拒绝候选并说明理由 |
| PATCH | `/location-assignments/{location_id}` | 人工修正归属，要求版本和原因 |

地图接口要求日期范围及合法 bbox，参数顺序固定为 `west,south,east,north`。默认返回上限 2,000 个点。超过上限时返回 `truncated=true` 和提示，要求缩小范围。不能悄悄截断后把图称为全量分布。

P0 候选生成范围应控制在可及时完成的规模。大批量候选生成使用 CLI 或复用受控后台运行方式，不添加一个未经设计的临时队列系统。

### 15.5 风险与统计接口

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/risk-rules` | 查看已发布规则及版本 |
| POST | `/risk-runs` | 创建指定周期和规则的计算任务 |
| GET | `/risk-runs` | 查看计算批次 |
| GET | `/risk-runs/{run_id}` | 状态、版本、覆盖摘要和错误 |
| GET | `/risk-profiles` | 必须限定 run_id，提供排序、等级和交叉口筛选 |
| GET | `/risk-profiles/{profile_id}` | 分项指标、贡献、规则、数据来源及过期状态 |
| GET | `/statistics/boroughs` | 行政区事故及伤亡统计 |
| GET | `/statistics/trends` | 时间趋势 |
| GET | `/statistics/factors` | 原因统计 |
| GET | `/statistics/vehicle-types` | 车型统计 |
| GET | `/statistics/persons` | 人员明细统计，按角色授权 |
| GET | `/statistics/governance` | 模拟工单统计 |

页面默认选择明确周期和规则下最近成功的运行批次，不能把不同 run 的路口结果混合排序。未完成计算时返回明确的空状态，不自动生成演示值。

### 15.6 治理接口

| 方法 | 路径 | 行为 |
|---|---|---|
| GET / POST | `/governance-tasks` | 查询或从画像创建草稿 |
| GET | `/governance-tasks/{task_id}` | 任务详情及当前版本 |
| PATCH | `/governance-tasks/{task_id}` | 只修改当前状态允许的内容，不接受任意状态字段 |
| DELETE | `/governance-tasks/{task_id}` | 只允许逻辑删除草稿 |
| POST | `/governance-tasks/{task_id}/publish` | 发布 |
| POST | `/governance-tasks/{task_id}/assign` | 分配或重新分配 |
| POST | `/governance-tasks/{task_id}/start` | 开始执行 |
| POST | `/governance-tasks/{task_id}/progress` | 追加执行记录 |
| POST | `/governance-tasks/{task_id}/submit` | 提交复核 |
| POST | `/governance-tasks/{task_id}/review` | 通过或退回 |
| POST | `/governance-tasks/{task_id}/cancel` | 取消 |
| GET | `/governance-tasks/{task_id}/history` | 返回按序号排列的完整历史 |
| GET，P1 | `/governance-tasks/{task_id}/comparison` | 使用冻结空间范围生成前后描述性比较 |

所有写接口需要 request_id，所有已有任务修改需要 expected_version。创建成功返回 task_id、task_code 和 version，前端不自行生成正式任务编号。

### 15.7 导出与健康检查

P0 提供按当前筛选条件导出 CSV 和可打印页面。网页导出默认上限 5,000 行，超过时要求缩小范围，或由有权限人员使用 CLI 完整导出。不能静默只导出前 5,000 行。

CSV 正确转义逗号、换行和引号，并处理以公式起始字符开头的用户文本，避免表格软件将其当作公式执行。

`/health/live` 只报告进程存活，`/health/ready` 检查数据库连接、迁移版本和 PostGIS 可用性。不向未授权用户输出密码、详细网络拓扑或完整异常栈。

## 16. 前端页面与交互要求

### 16.1 页面结构

| 页面 | 主要内容 | 必须处理的状态 |
|---|---|---|
| 登录 | 账户密码、错误提示 | 错误密码、停用用户、登录限流 |
| 总览 | 当前数据范围、事故与伤亡摘要、最近风险批次、工单待办 | 没有数据、数据过期、部分字段缺失 |
| 事故查询 | 筛选栏、分页表格、详情入口、导出 | 加载、空结果、请求失败 |
| 事故详情 | 基础信息、伤亡汇总、原因、车辆、人员 | 明细缺失与权限不足分开显示 |
| 风险地图 | 事故点与交叉口图层、图例、周期规则筛选 | 坐标缺失、点数截断、底图失败 |
| 交叉口管理 | 候选列表、证据、人工确认、关联地点 | 候选不等于确认，版本冲突 |
| 风险结果 | 排名、分项贡献、来源和规则版本 | UNKNOWN、旧版本、计算失败 |
| 治理任务 | 状态筛选、我的待办、建立草稿 | 角色和任务内身份限制 |
| 任务详情 | 描述、执行人、动作按钮、历史时间线 | 409 冲突、禁止自审、模拟标记 |
| 统计报表 | 趋势、行政区、原因、车型、人员 | 统计口径、缺失和组别重叠说明 |
| 数据管理 | 批次上传、校验预览、问题列表、发布 | 网络失败、部分拒绝、重试结果 |
| 用户管理 | 用户列表、创建、启停和角色 | 防止误停用最后一个可用管理员 |

### 16.2 交互原则

界面语言以中文为主，来源字段和技术标识保留必要英文。街道名保持原始名称，不做无依据的中文翻译。默认优先桌面端，保证 1366×768 和常见更大桌面尺寸可用，再处理较窄窗口。

每个页面都具备加载、空数据、错误和无权限状态。操作失败不能只在控制台输出。删除、取消、停用和发布前显示确认说明。

颜色不能作为风险等级的唯一表示，同时提供文字和图例。任务流程用状态标签和历史表达，避免以复杂动效替代业务内容。

首页显示实际数据覆盖范围、来源、成功导入时间和选定风险运行版本。不要用当前日期暗示数据已经更新到当天。

### 16.3 地图服务与离线演示

底图 URL 和署名配置化。使用第三方地图服务时遵守其使用条件。OSM 公共瓦片服务不允许为离线演示批量预下载瓦片，不能把“缓存整座城市”作为默认方案。[W8]

网络不可用时，仍应显示事故列表、统计和可用的本地几何图层，可退化为无底图的点位展示并说明。确需离线底图时另行使用明确允许该用途的数据或服务，不自动抓取公共瓦片。

## 17. 测试计划与通过标准

### 17.1 测试层次

单元测试覆盖纯清洗规则、时间边界、匹配规则、风险公式和权限策略。数据库集成测试验证约束、空间 SQL、事务、幂等和数据库函数。API 测试检查鉴权、错误码、字段契约和分页。浏览器测试走完整业务过程。

集成测试必须连接 PostgreSQL/PostGIS。不能只用 SQLite 替代后宣称外键行为、空间查询或 PostgreSQL 事务测试已经通过。测试库与演示库使用不同数据库名及凭据。

### 17.2 核心用例

| 编号 | 用例 | 预期 |
|---|---|---|
| T01 | 完全相同文件重复导入 | 业务数量不增加，返回可解释的重复结果 |
| T02 | 相同来源主键内容修订 | 当前记录正确更新，旧原始记录仍可查 |
| T03 | 同一批次主键冲突 | 不随机覆盖，生成阻断问题 |
| T04 | 子表缺少父事故 | 隔离并报告，不关闭外键 |
| T05 | 事故没有坐标 | 列表保留，地图说明未显示数量 |
| T06 | 伤亡值缺失与真实为零 | 两者展示及评分不同 |
| T07 | 更新事故原因槽位为空 | 旧槽位关联移除，其他槽位正确 |
| T08 | 不同事故有相同伤亡人数 | SUM 正确，不误用 SUM DISTINCT |
| T09 | 同一事故有多车、多原因 | 统计不放大 |
| T10 | 日期结束边界 | 结束日排他，前端选择语义一致 |
| T11 | 纽约当地事故时间和系统操作时间 | 不发生静默时区平移 |
| T12 | 经纬度顺序交换、距离单位错误 | 校验或测试能够发现 |
| T13 | 多个候选路口都符合半径 | 保持待确认，不任意指派 |
| T14 | 自动重跑遇到人工确认 | 不覆盖人工结果 |
| T15 | 修改地点归属 | 版本增加，旧画像标记过期 |
| T16 | 评分 9、10、29、30 及缺失 | 等级边界正确 |
| T17 | 风险计算中途失败 | 无部分结果成为有效批次 |
| T18 | VIEWER 直接调用写接口 | 后端 403 |
| T19 | 非执行人提交验收 | 后端拒绝 |
| T20 | 执行人复核自己的任务 | 后端拒绝 |
| T21 | 工单同版本并发修改 | 一项成功、一项 409、历史只增加一次 |
| T22 | 工单同请求网络重试 | 只发生一次修改 |
| T23 | 工单历史写入失败 | 任务状态一同回滚 |
| T24 | 直接修改历史或已发布规则 | 数据库拒绝 |
| T25 | 用户停用后使用旧令牌 | 被拒绝 |
| T26 | 列表与 CSV 相同筛选 | 同范围结果一致，超上限不静默截断 |
| T27 | 导入发布失败后重试 | 无部分发布或重复累计 |
| T28 | worker 重启 | 失效任务有明确状态，可安全重试 |
| T29 | 地图服务不可访问 | 列表、统计和工单仍可用 |
| T30 | 数据库备份恢复 | 表、约束、扩展、视图、历史及关键汇总校验通过 |
| T31，P1 | 比较基期为零或后期不完整 | 百分比为 NULL 或数据不足，不报告虚假改善 |

### 17.3 浏览器验收流程

使用真实数据演示管理员导入与发布，切换普通用户查询事故，再切换管理人员确认候选交叉口、生成风险结果、建立工单并分配。由另一名管理人员开始执行、提交记录，再由符合条件的人复核。最后查看不可修改的历史及导出报表。

录制或截图中明显展示“真实碰撞数据”和“课程模拟治理任务”的区分。若演示使用单元测试数据，必须切换到明确标识的测试环境。

### 17.4 证据要求

保存实际运行命令、环境、退出码、测试报告和关键截图。未运行的测试写“未执行”，失败测试保留失败原因。不得生成虚构的性能 CSV、通过率、事故数量或截图。

测试是否通过按关键行为判断，不以代码覆盖率数字代替。至少保证 T01—T30 的对应行为有自动化或明确的操作证据，P1 功能另附测试。

## 18. 安全、部署、备份与运行维护

### 18.1 应用安全

密码使用 Argon2 等适合密码存储的算法。P0 采用短期 JWT 访问令牌，前端仅保存在内存中，每次请求由后端读取当前用户是否启用、当前角色及认证版本。刷新页面需要重新登录是可接受的 P0 简化，不把长期令牌写入浏览器持久存储。[密码哈希与 JWT 的框架实现参考 W7；会话策略为本期选择]

登录接口限制连续失败尝试。开发环境可以使用单实例限流，但文档必须说明该限制，不能宣称它已支持多节点全局限流。远程访问启用 HTTPS，CORS 使用明确的来源白名单。

SQL 参数绑定，排序字段采用白名单，禁止开放任意 SQL 查询接口。用户输入作为纯文本渲染，任务说明不直接作为 HTML 插入页面。上传文件使用服务器生成的文件名并限定到专用目录，检查文件类型和大小。

配置通过环境变量读取，提供不含真实凭据的 `.env.example`。不在仓库中保存数据库密码、Socrata 令牌、JWT 密钥或固定弱管理员密码。首次管理员密码通过环境变量或交互生成。

### 18.2 数据库角色分离

数据库至少区分迁移管理角色、应用运行角色和数据导入 worker 角色。迁移角色负责建扩展、表、函数和权限，不作为普通 Web 请求的连接用户。

应用角色只能读取事故事实，并受控修改业务数据。工单关键变更通过函数执行。worker 只能执行导入、计算及其状态维护所需操作。只读测试角色用于验证最小权限。

应用中的三类用户不必对应三个共享数据库登录账户。业务角色权限由后端逐请求检查，数据库运行角色限制基础能力，两层设计在报告中分别说明。

对 schema、表、序列和函数权限显式配置。不能仅撤销表权限却让 PUBLIC 仍可执行有写入能力的高权限函数。

### 18.3 备份范围

提供受控 CLI，使用 `pg_dump` 的自定义格式备份，再用 `pg_restore` 恢复到独立测试数据库。数据库备份与恢复机制参考 PostgreSQL 官方文档。[W6c]

同时保存迁移版本、代码提交、依赖锁文件、原始数据 manifest、对应原始文件和风险映射快照。数据库备份不会自动包含这些文件，需要在操作说明中单独列出。

数据库登录角色及环境配置通过初始化脚本重建，不能认为单库备份自动提供全部集群用户和外部密钥。备份文件可能包含账户哈希和业务记录，禁止放入公共仓库或公共下载目录。

### 18.4 恢复演练

恢复必须在明确指定的新数据库中进行。默认拒绝将恢复目标指向当前演示库。涉及覆盖或删除时需要操作者显式确认目标。

演练至少检查表数量、关键表行数、主键外键、PostGIS 扩展、视图、数据库函数、索引、风险结果、工单历史和序列可继续产生新编号。恢复后运行冒烟测试和关键汇总对照。

P0 不提供浏览器上传任意数据库备份并在在线库执行恢复的功能。管理页面可以显示备份说明，真正恢复使用维护命令。

### 18.5 计划中的命令入口

以下是应由 Codex 实现的命令契约，现在不代表仓库中已经存在相应脚本。

```text
python -m app.cli probe-data
python -m app.cli import-files --manifest <manifest_path>
python -m app.cli generate-intersection-candidates --scope <scope_file>
python -m app.cli generate-risk --start 2025-01-01 --end 2026-01-01 --rule rule-v1
python -m app.cli seed-demo-users
python -m app.cli seed-demo-tasks
python -m app.cli verify-data
python benchmarks/run_benchmarks.py --config <benchmark_config>
```

数据库初始化、迁移和前端构建命令以实际选定工具为准写入 README。Windows 端提供 PowerShell 用法，涉及中文路径、空格路径时有对应测试。禁止假定用户已经安装 Linux 工具。

`seed-demo-users` 与 `seed-demo-tasks` 默认只允许在明确标记的开发或演示环境运行。模拟工单不能通过创建虚假事故记录来满足外键。

### 18.6 运行维护

日志保留请求 ID、用户或作业标识、关键事件和耗时，避免泄露敏感字段。数据库和文件目录的增长情况写入维护说明。原始记录默认保留到课设验收完成，不自动删除复现所需数据。

风险结果不必做实时更新。P0 由管理员或管理人员手动触发，提交后显示计算状态。定时更新作为后续可选功能，初期不同时启动多套调度器。

## 19. 分阶段实施计划

### 19.1 总原则

每个阶段都交付可运行结果、测试和文档。先完成数据库与真实数据，再完成业务流程，最后进行界面完善及性能实验。每次让 Codex 处理一个阶段或一个范围明确的子任务。

指南要求第 10 周中期检查、第 16 周答辩。计划在中期前完成 M0—M6 的主功能，在后期完成 M7—M8。具体日历日期以课程安排为准，不凭本计划推算当前教学周。[S1，§3]

### 19.2 M0 仓库与数据可行性核对

**状态：已完成。** 调查及数据库补验分别见 [M0记录](docs/milestones/M0.md)、[数据库记录](docs/milestones/M0-database.md)。下列工作内容保留为阶段定义，不要求重复执行全部探测；资料整理及开发方式更新见§0.4。

**工作内容**

检查当前目录是否已有项目，查看 Git 状态、现有代码和说明文件，列出可以复用的内容。核对原方案摘要和本计划的差异，不覆盖现有工作。

完成三类数据字段及小样本探测。记录不能访问的接口和离线入口。验证 PostgreSQL/PostGIS、Python、Node 和依赖组合，确定锁定策略。确认首个真实数据范围。

**交付**

`docs/data_probe.md`、`docs/environment.md`、`docs/decisions/0001-implementation-baseline.md`、README、分阶段任务清单、平台依赖锁和数据库镜像锁；本轮另归并形成 `docs/references/prior_work_summary.md`。

**通过条件**

明确实际可用的数据入口和字段映射，明确待解决问题，有可安装的目标技术组合。尚未下载真实数据时可以先实现离线导入和测试夹具，但真实数据验收仍标记未完成，不能把 M2 宣告通过。

**禁止事项**

未经检查重建仓库、批量删除现有文件、自动上传私有资料、假装下载成功、提前开发 P2 功能。

### 19.3 M1 数据库结构、基础后端和认证

**状态：完成。** 23表、索引/3基础视图、跨表完整性约束、迁移/app/worker角色、认证和账户管理、ER/数据字典及规范化说明已完成。真实PostgreSQL/PostGIS空库迁移、权限拒绝、JWT失效及两连接并发边界通过独立复验，见[M1模型记录](docs/milestones/M1-model.md)。以上为M1历史范围；worker导入在M2落实，计算与完整工单动作分别在M4、M5落实。

**工作内容**

建立工程骨架、迁移、23 张关系表、必要约束、数据库角色及基础视图。按外键依赖顺序创建表。先实现管理员初始化、三类角色、登录、退出、用户启停和健康检查。

**交付**

可重复迁移的数据库、初版 E-R 图和关系模型图、数据字典、认证 API、数据库权限说明、约束与鉴权测试。

**通过条件**

从空库创建成功，PostGIS 可用，主外键及唯一约束实际生效，VIEWER 写请求被拒绝，停用用户的旧令牌失效。不是只在 ORM 中声明约束。

### 19.4 M2 真实数据导入与事故查询

**状态：完成。** 三源CSV、幂等/修订、原子发布、角色投影、事故查询及页面通过实测；2025全年547,631行已发布，正式事故/人员/车辆为85,546 / 292,070 / 170,015，revision=2。网页重复导入3,232行全部跳过，事实与revision不变；104项独立全量回归、最新24项M2回归、3项管理员边界、桌面/窄屏与网页发布流程通过，见[M2记录](docs/milestones/M2.md)。

**工作内容**

完成 CSV 暂存、字段校验、数据问题记录、受控发布、幂等和来源追踪。实现事故查询、详情、人员和车辆分页。前端同步完成最小可用事故页面。

**交付**

真实数据 manifest、导入批次报告、数据质量说明、基础查询界面、T01—T11 中相关测试。

**通过条件**

三类真实数据能进入正式数据库。重复导入不增加数量，来源修订可追踪，事故汇总不被明细连接放大。记录实际导入条数、范围和异常，不使用预计值。

### 19.5 M3 地图与交叉口档案

**工作内容**

实现有效事故点地图、附近查询、候选生成、人工确认、地点归属和审计。保存匹配算法版本及参数。

**交付**

地图与交叉口页面、代表性候选复核记录、空间查询 SQL、坐标与匹配测试。

**通过条件**

候选和确认对象明确分开，缺失坐标事故不丢失，同一观察地点最多一个当前归属，人工判断不会被自动覆盖。

### 19.6 M4 风险规则、运行批次和画像

**状态：本机验收完成。** 95个已确认路口在2025周期生成95条画像，输入revision98；121项独立实库回归、迁移回退重升、前端及桌面/窄屏检查通过。范围、快照及验证见[M4记录](docs/milestones/M4.md)和[ADR 0006](docs/decisions/0006-m4-risks.md)。

**工作内容**

初始化原报告规则，实现后台批量计算、统一 SQL 视图、覆盖摘要、快照标识、过期提醒和历史结果查询。

**交付**

风险页面、规则及计算说明、运行 manifest、边界及失败回滚测试。

**通过条件**

手算测试通过，UNKNOWN 与 LOW 区分，失败计算不暴露部分结果，同一排名不混用批次，旧结果可追溯。

### 19.7 M5 治理业务与事务

**工作内容**

实现从画像建立草稿、发布分配、执行记录、提交复核、退回通过、取消、草稿删除及不可变历史。完成数据库函数和对象权限。

**交付**

工单页面、状态说明、权限矩阵、数据库事务函数、两连接并发测试及幂等测试。

**通过条件**

能由不同用户完成全过程，自审被阻止，冲突返回 409，历史失败触发回滚，模拟业务标记明确。

### 19.8 M6 统计整合与中期演示

**工作内容**

完成总览、行政区与时间统计、原因、车型、人员分析、CSV 导出和打印样式。整理中期可操作演示。

**交付**

可运行的主要系统、中期进度说明、功能清单、已知问题列表、当前 E-R 图和测试摘要。

**通过条件**

P0 主业务贯通，没有依赖前端假数据的核心页面。中期能够解释表结构、来源映射、一个复杂 SQL 和一个工单事务。

### 19.9 M7 性能、安全和恢复测试

**工作内容**

补齐自动化测试，执行 B01—B04，保存执行计划、实际耗时和结果一致性验证。完成权限核查、备份和新库恢复演练。资源允许再实施 P1。

**交付**

基准测试结果目录、测试报告、优化前后说明、备份恢复说明、安全检查清单。

**通过条件**

结果来自真实运行，不伪造达标。实验没有破坏演示库。恢复后关键功能与数据对照一致。

### 19.10 M8 最终报告、录像和交付核验

**工作内容**

编写课程要求长度的报告，核对文档和实现一致性，录制完整功能录像，在干净环境复现启动和迁移。检查源码及材料中没有密钥或私有数据误提交。

**交付**

最终报告、源码、依赖锁定与部署说明、数据库迁移和初始化脚本、数据获取及导入说明、测试证据、功能录像。

**通过条件**

能够按 README 启动；每个已宣称完成的功能都有运行证据；原方案调整在报告中有解释；未完成功能如实列出；作者能够说明设计和关键实现。

### 19.11 每阶段记录模板

每完成一个阶段，在 `docs/milestones/Mx.md` 保存以下内容。

```text
阶段名称
已完成内容
新增或修改的文件
数据库迁移与兼容影响
实际执行的命令
测试结果和证据路径
本阶段真实数据范围
未解决问题及影响
相对 PROJECT_PLAN.md 的偏差及理由
下一阶段建议
```

## 20. 报告、图表和演示材料计划

### 20.1 报告组织

报告应覆盖问题定义、可行性、需求分析、总体与详细设计、数据库实现、应用实现、测试和维护，与课程指南一致。[S1，§2—3]

以下约 12,600 字是建议分配，不是固定章节字数，也不代表计划文件需要控制在这个范围。

| 内容 | 建议字数 | 必须说明 |
|---|---:|---|
| 摘要 | 400 | 真实数据、数据库实现、业务范围和结果边界 |
| 1 问题定义与背景 | 800 | 原项目延续及本期新增治理管理 |
| 2 可行性分析 | 600 | 数据获取、技术、个人工作量和风险 |
| 3 需求分析 | 1,300 | 角色、功能、非功能、数据字典和数据流 |
| 4 概念设计 | 1,000 | 核心实体、四类业务扩展及联系 |
| 5 逻辑设计 | 1,800 | 关系模式、主外键、字段映射和 3NF |
| 6 物理设计 | 1,600 | 类型、约束、索引、空间对象和存储安排 |
| 7 系统实现 | 1,800 | 导入、接口、风险、工单事务和权限 |
| 8 测试与性能优化 | 2,000 | 功能、完整性、并发、查询实验及真实结果 |
| 9 运行维护 | 800 | 配置、日志、备份、恢复和数据更新 |
| 10 总结与限制 | 500 | 完成情况、数据局限及未实现扩展 |

参考文献列出实际使用的公开数据、技术文档和研究材料。报告中的图表在正文中有引用，截图与本次实现相符，表结构与迁移相符。最终字数统计口径按教师要求执行。

### 20.2 应形成的图表

提供系统总体架构图、第 0 层和第 1 层数据流图、概念 E-R 图、关系模型图、治理状态图、数据导入流程图、关键页面截图，以及至少四组性能实验结果表。

图应由实际关系和流程生成。数据库结构更改后同步更新图。概念图、逻辑图和应用流程图分别说明用途，不用一张架构图代替所有数据库设计图。

这些是开发过程应生成的交付物。本计划本身不包含已经实现并验证的数据库结构图或性能图。

### 20.3 功能录像建议顺序

先展示真实数据来源、范围和版本，再展示数据导入与问题记录、事故查询和明细、地图与交叉口确认、风险分项计算、工单建立及多人处理、历史记录、统计导出，最后展示测试及恢复证据。

录像中的速度提升和数据量都来自实际实验。工单界面保持模拟标识，避免把课程数据处理结果呈现为官方治理结论。

## 21. 给 Codex 的执行规则与任务入口

### 21.1 执行规则

1. 先读完整计划和当前仓库文件。存在现有工作时优先复用，不重置、不批量覆盖。
2. 按 M0—M8 顺序推进。当前轮只完成用户指定阶段，不擅自实现全部 P2。
3. 本计划中的接口、命令和目录是目标设计，创建后再在 README 中记录实际可运行命令。
4. 数据库迁移作为结构变更的执行入口。ORM、SQL、数据字典和图表必须同步。
5. 核心查询和统计在数据库完成，不把完整数据拉到前端后计算，也不使用固定数组冒充数据库结果。
6. 实际下载失败或依赖安装失败时保留错误，使用明确标识的本地测试方式继续可独立开发的部分，不声称已经完成真实数据验收。
7. 字段或来源文档冲突时先记录证据和影响。涉及主键、统计口径或业务状态的重大变化先提出设计调整，不静默更改。
8. 修复问题后运行相关测试。未执行的测试明确说明，不生成通过率和性能结果占位值。
9. 执行破坏性操作、覆盖原始数据、恢复现有数据库、推送公共仓库或修改外部服务前取得明确授权。
10. 不自动创建云资源、购买地图服务、接入无关大模型 API，或使用其他个人项目的服务器及凭据。
11. 只记录实现需要的技术决策、来源和测试证据，不在代码或文档中加入无关个人信息。
12. 每阶段汇报完成内容、修改文件、执行命令、测试结果、剩余问题和下一阶段范围。

### 21.2 当前任务入口

M0调查和数据库验证已完成，不再保留首次M0提示词作为默认任务。后续先读§0.4、S2摘要和阶段记录，再按用户指定的阶段或子任务推进。日常进度以 [任务清单](docs/milestones/tasks.md) 为准，实际命令以README为准；不重复复制长篇说明。

### 21.3 后续阶段提示词模板

```text
继续执行 PROJECT_PLAN.md 中的 M<阶段编号>。
先阅读上一阶段记录和当前代码，只完成本阶段约定范围。
数据库结构变化必须通过迁移，并同步更新数据字典、接口和测试。
完成后运行本阶段的验证命令，保存真实结果到 docs/milestones/。
不能运行的测试明确注明原因。不要用模拟数据替代真实数据验收，不实现 P2 功能。
```

## 22. 交付前总检查

- [ ] 本期题目已经登记，标题与报告、系统页面一致。
- [ ] 三类官方数据来源、范围、字段及实际行数可追溯。
- [ ] 事故事实、规则计算结果和模拟工单明确区分。
- [ ] 人员及车辆记录主键与原始业务代码没有混用。
- [ ] 候选交叉口和确认交叉口有区别，缺失坐标记录没有被删除。
- [ ] 多表统计没有重复累计事故和伤亡。
- [ ] 风险权重、阈值、周期、版本、覆盖率及缺失处理可解释。
- [ ] 已发布规则、成功画像和工单历史不会被任意覆盖。
- [ ] 任务状态、对象权限、自审限制、幂等和并发冲突均有验证。
- [ ] 全部关键约束实际存在于 PostgreSQL，数据库函数和视图可解释。
- [ ] 前端核心页面使用真实 API，错误和空状态可见。
- [ ] 性能实验结果真实、查询语义一致、运行环境记录完整。
- [ ] 备份已恢复到新库并核验，不仅仅生成过备份文件。
- [ ] README 在干净环境可执行，版本和迁移锁定，密钥没有进入仓库。
- [ ] 报告达到课程字数要求，代码、图表、截图及录像相互一致。
- [ ] 未完成功能和数据限制如实说明，没有以计划代替已完成成果。

## 23. 来源索引与尚待验证事项

### 23.1 课程及原方案定位

| 来源 | 重点位置 | 支持的内容 |
|---|---|---|
| S1，课程要求摘要 | §1 | 选题、Canvas登记日期与个人项目定位 |
| S1，课程要求摘要 | §2 | 软件生命周期、三层设计、3NF、索引/SQL优化/测试、完整性和权限 |
| S1，课程要求摘要 | §3 | 独立项目交付、报告字数、源码/录像、周次/答辩与成绩构成 |
| S1，课程要求摘要 | §4—5 | 城市交通参考、纽约/OSM入口、自由工具选择与小组边界 |
| S1，课程要求摘要 | §6 | 正确源文件、历史页码、SHA及校验备份 |
| S2，前期资料摘要 | §1—2 | 背景、三类用户、查询统计、三源、九实体十关系和主键 |
| S2，前期资料摘要 | §3—4 | 完整性/3NF、索引、暂存、分层方案、风险权重与空间处理 |
| S2，前期资料摘要 | §5—6 | 已替换设计、原PDF页码/DOCX段落/TXT行号及参考线索 |

本计划列出的任务状态、接口、23 表实施模型、性能目标、测试用例和里程碑拆分均为本期新增设计。课程材料没有逐项给出这些细节。

课程材料强调个人独立完成，但未具体说明生成式开发工具的允许范围。项目作者应遵循教师另外说明的使用和披露要求，本计划不把工具使用方式解释为已经获得课程许可。

### 23.2 外部技术核对资料

以下资料核对日期为 2026-09-28。网页获取或搜索呈现可能包含缓存，实际编码仍须保存当时的元数据与环境探测结果。只引用官方数据说明或技术文档。

| 编号 | 资料 | 用途 |
|---|---|---|
| W1 | Socrata API Foundry，Motor Vehicle Collisions - Person | 区分 unique_id、person_id、vehicle_id 和人员字段 |
| W2 | Socrata API Foundry，Motor Vehicle Collisions - Vehicles | 区分 unique_id 与 vehicle_id |
| W3 | 美国数据目录中的纽约官方碰撞数据说明 | 公开数据及记录可能修订的边界 |
| W4 | PostGIS，ST_DWithin | geography 距离单位及空间查询方法 |
| W5 | PostgreSQL，Using EXPLAIN | 查询计划、实际执行及性能测量 |
| W6a | PostgreSQL，Transaction Isolation | 一致性快照与隔离级别 |
| W6b | PostgreSQL，Explicit Locking | 工单行锁与并发行为 |
| W6c | PostgreSQL，pg_dump | 备份格式与恢复相关约束 |
| W7 | FastAPI，OAuth2 with Password and hashing, Bearer with JWT tokens | 密码哈希及 JWT 接入参考 |
| W8 | OpenStreetMap Foundation，Tile Usage Policy | 底图署名、服务配置及禁止公共瓦片批量离线下载 |

```text
W1 https://dev.socrata.com/foundry/data.cityofnewyork.us/f55k-p6yu
W2 https://dev.socrata.com/foundry/data.cityofnewyork.us/bm4k-52h4/embed
W3 https://catalog.data.gov/dataset/motor-vehicle-collisions-crashes
W4 https://postgis.net/docs/ST_DWithin.html
W5 https://www.postgresql.org/docs/current/using-explain.html
W6a https://www.postgresql.org/docs/current/transaction-iso.html
W6b https://www.postgresql.org/docs/current/explicit-locking.html
W6c https://www.postgresql.org/docs/current/app-pgdump.html
W7 https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
W8 https://operations.osmfoundation.org/policies/tiles/
```

### 23.3 已验证范围与后续待办

M0已验证官方元数据/限定样本/范围查询入口、年度键和10起父子关联；锁定环境与两平台连接通过。M1在该基础上完成23表模型、数据库权限、认证和账户页面，独立实库套件82项全部通过，Vue类型检查/构建及页面检查有本轮证据。模型测试使用独立夹具，不能代替真实数据导入或完整工单验收。来源和版本证据见§0.4。

M2完成104项完整实库回归、读取一致性/上传前鉴权补测和前端检查；最新父键查询修正后另有24项M2实库回归、3项管理员边界及CLI隔离验收通过。2025全年三源已原子发布，正式事故/人员/车辆为85,546 / 292,070 / 170,015，revision=2。桌面、窄屏及网页重复上传/发布通过，3,232行重复输入无增量。首次发布租约失败的回滚与重试记录保留，年度缺失和容量按实际库统计；准确状态见[M2记录](docs/milestones/M2.md)。

| 阶段 | 仍需验证或落实 |
|---|---|
| M1（完成） | 字段契约、23表迁移、认证/角色/失败路径通过。复用M0固定版本；运行时补丁升级另行重锁和回归，不声称补丁安全更新完成 |
| M2（完成） | 首批、全年正式发布、质量/容量核验与网页重复导入通过；3起死亡计数未知、2,842起缺坐标等质量限制保留，见M2记录 |
| M3（完成） | 95个路口道路身份已核对，另1拒绝、4待定；复杂路口/历史路网限制见M3记录 |
| M4（完成） | 后台作业、覆盖、统一评分视图、快照和历史页面；121项独立实库回归及浏览器验证通过，首批覆盖0.41% |
| M5 | 工单权限、状态、并发/幂等及完整模拟业务流程 |
| M7—M8 | 性能、备份新库恢复、浏览器全流程与干净环境交付 |

原生Docker Registry端点EOF仍存在；本机已通过官方替代端点、TLS及SHA校验取得镜像和离线归档。保留错误，不把它扩大为“数据库不可用”，也不声称所有网络入口已经修复。

需要准确率的地点匹配评价尚无人工标签，需要因果解释的治理效果评价也没有对应研究设计。本项目先完成可追溯、可解释和可操作的数据库应用，不预先报告这些尚未验证的结果。
