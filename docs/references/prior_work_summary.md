# 前期资料保留摘要

整理日期：2026-09-29。本文件替代上学期报告、选题说明和写作大纲的日常阅读，只保留本项目仍需使用的内容。原报告是设计成果，不能作为已完成系统、真实导入或性能测试的证据；当前实施以 [PROJECT_PLAN.md](../../PROJECT_PLAN.md)、[ADR](../decisions/0001-implementation-baseline.md) 和 [数据探测](../data_probe.md) 为准。

## 1. 项目定位与需求

保留选题说明P2—P4、原报告第1—2章和大纲第68—195行的共同主线：围绕Vision Zero减少交通死亡和严重伤害的目标，将纽约公开碰撞数据组织为可查询、统计和追溯的关系数据库，为识别重点地点及治理管理提供依据。项目重点是数据库设计与应用，不以训练预测模型为目标。当前题目沿用“风险识别与高危交叉口治理管理系统”。

| 用户 | 保留的业务需求 | 本期落实方向 |
|---|---|---|
| 系统管理员 | 数据接入、清洗、字典和异常管理 | 增加用户管理、受控发布和审计 |
| 交通管理人员 | 时间/行政区/原因/车型/伤亡统计、风险判断 | 增加交叉口确认及治理任务执行、复核 |
| 普通查询用户 | 按编号、日期、行政区和街道查询事故 | 只读查询、明细查看与基础统计 |

保留事故查询、行政区统计、原因分析、车辆类型分析、人员伤亡分析及风险画像六类核心需求。事故详情分别展开人员、车辆、原因和伤亡汇总；统计需区分事故数、明细记录数和伤亡人数，不能通过多表连接重复累计。治理任务与历史记录是本期扩展，演示工单明确标为课程模拟业务。

## 2. 数据来源与核心关系模型

三源均来自NYC Open Data的Motor Vehicle Collisions系列，原报告第1.2节与参考文献第1—3项的来源仍保留：

| 数据源 | Dataset ID | 粒度与用途 |
|---|---|---|
| Crashes | h9gi-nx95 | 一起事故：时间、地点、原因槽位、伤亡汇总 |
| Person | f55k-p6yu | 事故中的一条人员记录 |
| Vehicles | bm4k-52h4 | 事故中的一条车辆记录 |

以 `collision_id` 关联父事故与子明细。M0已核对：Crashes以 `collision_id` 为键；人员、车辆以各源 `unique_id` 映射系统记录主键；源 `person_id`、`vehicle_id` 保存为TEXT代码。记录编号不等同自然人身份或跨事故同一车辆；P0不建立人员到车辆的直接外键。

原报告第3—4章的**九个概念实体、十个主要关系**保留为本期23表模型的业务起点，完整字段由本期数据字典维护：

| 原关系 | 值得保留的含义与关键约束 | 本期处理 |
|---|---|---|
| Borough | 行政区字典，编号主键、名称唯一 | 保留 |
| Location | 事故观察地点、街道/坐标/邮编，引用行政区 | 与标准交叉口分离，缺位置仍保留事故 |
| Collision | 事故核心表，collision_id主键，日期/时间/地点 | 保留官方事故事实 |
| Person | 多条人员记录引用一起事故 | 记录键来自Person.unique_id，原person_id另存 |
| Vehicle | 多条车辆记录引用一起事故及车辆类型 | 记录键来自Vehicles.unique_id，原vehicle_id另存 |
| VehicleType | 车辆类型字典，名称唯一 | 保留原值及有版本的规范化映射 |
| ContributingFactor | 事故原因字典，名称唯一 | 保留来源类别含义 |
| CollisionFactor | 事故—原因关联；PK(collision_id,factor_order)，factor_id外键 | 保留槽位1—5，同一槽位最多一条；不声称对应车辆明细键 |
| CasualtyStat | collision_id同时为主键和事故外键 | 保存Crashes的一事故一行伤亡汇总 |
| RiskProfile | 一个对象在某周期内的聚合指标 | 本期改为标准交叉口+计算批次，周期/规则进入RiskRun |

原基数为：行政区→地点、地点→事故、事故→人员、事故→车辆、车型→车辆均1:N；事故→伤亡汇总1:1；事故与原因M:N经CollisionFactor实现。原地点→画像1:N，本期迁移到已确认标准交叉口的历次画像。原图3.1带字段和PK/FK，保留其关系含义；M1重新绘制概念E-R与23表关系模型，不把旧图直接当成扩展后的模型。

## 3. 完整性、规范化与实现思路

保留原报告第4.5—5章和第8章的以下原则：

- **规范化**：行政区、车辆类型、事故原因拆为字典；1:N在多端设外键，1:1共享主键，M:N设关联表。逐表写候选键、函数依赖和3NF依据，不能以“拆了表”代替证明。
- **完整性**：记录键非空且唯一、外键不允许孤立明细；伤亡/次数非负；原因槽位1—5；字典名称唯一；引用中的字典限制删除。基础事故事实以导入与查询为主，不照搬任意删除或级联删除建议。
- **类型和时间**：正式数值记录键用BIGINT、源代码及邮编用TEXT；事故当地日期/时间分开保存，系统操作时间使用带时区时间。字段类型以现行计划为准，不保留旧“BIGINT或VARCHAR任选”的模糊写法。
- **原始与正式数据分层**：保存原始字段和批次，校验后写正式关系；记录来源、时间、成功/异常计数及问题。更新事故不能丢失旧来源，清洗规则需要版本。
- **索引围绕查询**：事故日期/地点、人员车辆事故外键、原因/车型、风险对象及周期是候选索引方向；本期加入PostGIS空间索引。保留查询场景，不机械复制全部旧索引名，用真实执行计划判断收益。
- **派生结果**：风险分数/等级由统一规则产生，避免人工分别维护。画像、视图、物化读取和快照分别解释，不沿用“所有画像字段均独立满足3NF”的笼统结论。

保留原报告第6章的数据层、业务层、展示层结构和“先数据接入与查询，再统计/地图/风险”的实现路线。技术备选已收敛为PostgreSQL/PostGIS、FastAPI和Vue；数据库在Docker中，后端/worker及前端在Windows开发。详细版本与实际通过的检查只维护在 [环境说明](../environment.md)，不在旧资料摘要重复罗列。

## 4. 风险规则与空间分析

原报告第6.3节与大纲第914—926行的初始规则保留：

`S = N + 3I + 10K + 5V`

N为周期内事故数，I为受伤人数，K为死亡人数；本期将V明确为行人和骑行者受伤、死亡人数之和。V与I/K有重叠，属于有意额外加权。边界为 **S<10低风险、10≤S<30中风险、S≥30高风险**。

这是课程初始评分，不是未来事故概率、经过校准的风险率或治理效果证明。本期评分按一事故一行的Crashes汇总计算；缺少任一必需伤亡字段时分数NULL、等级UNKNOWN，不能把缺失补零。不同地点或周期比较需使用相同规则并说明覆盖范围；缺交通流量暴露量时不称“发生率”。

保留原报告第8章“同一路口的街道格式与坐标偏差可能产生多个观察地点”的提醒。当前做法是事故地点→候选交叉口→人工确认→单一归属；距离接近仅作为候选证据，50米是可配置默认参数。只有确认交叉口及有效归属进入正式排名，人工结果不被自动重跑覆盖；历史画像保留规则、数据和匹配版本。

## 5. 已替换或不再保留的内容

| 旧内容及来源 | 处理 |
|---|---|
| TXT第521行：三字段原因主键 | 以原报告最终两字段PK为准，避免同一槽位出现多个原因记录 |
| TXT第631—652行：unique_id或person_id/vehicle_id任选 | 按M0实际字段契约区分正式记录键和源代码 |
| PDF第8、17页 / TXT第260—273行：Location直接代表交叉口 | 分离观察地点和标准交叉口，画像对象按本期模型调整 |
| PDF第16页：Unknown、Unspecified、空值统一未知 | 原值分别保留；展示可分组，不能丢弃不同来源含义 |
| TXT第590—597行：街道列按名字直接映射 | 当前API off_street_name承载横街、cross_street_name承载地址；显式、有版本地映射，CSV另验表头 |
| TXT第179行：直接细分driver/occupant | 先使用官方字段支持的类别，驾驶员/乘客细分需额外字段核验 |
| DOCX P5“获取便捷” / TXT第78行“不能下载可只做设计” | 只保留公开来源；访问可能失败，须记录错误、支持官方CSV，完整导入仍要真实验收 |
| 旧20页篇幅安排、章节页码分配、封面身份信息、反复写作指导 | 不迁入本期；报告按[课程要求S1](course_requirements.md)1.0万—1.5万字，章结构见当前计划 |
| MySQL/Flask等并列备选、旧风险索引和完整字段清单 | 不重复保留；已由现行技术方案和数据字典接管 |
| KDE、K-means、天气/流量融合和自动拓扑 | 仅留文献线索，非本期P0工作，不因有旧建议而扩大范围 |

## 6. 来源与参考线索

三份原材料已完整检查，PDF关键表及第9页图3.1核对；DOCX有5个正文段落、无表格；TXT共946行。后续引用本摘要，以此表中的原位置追溯，不再要求原文件位于根目录。

| 原材料 | 保留依据的位置 | 角色 |
|---|---|---|
| 2452273-胡懿晨.pdf（20页） | 物理第4—7页背景/需求，第8—13页实体/关系/3NF，第14—16页约束/索引/清洗，第17页风险与架构，第19—20页改进与文献 | 最终设计主依据 |
| 2452273-胡懿晨-选题-面向 Vision Zero 的纽约交通碰撞风险画像与高危交叉口管理系统设计.docx | P2—P5 | 早期定位和功能意图，重复内容合并 |
| 报告大纲设计.txt | 第68—195行需求，第380—408行联系，第914—926行公式；过时项见§5 | 辅助来源，不覆盖最终报告 |

源文件历史SHA-256见 [M0原始清单](../evidence/M0/original-files.json)。按用户明确要求删除根目录三份原文件；删除前的三源和计划1.0已校验压缩保存于 `.m0-work/materials-consolidation-20260929/originals-before-consolidation.zip`。秋季指南随后另行归并为 [课程要求S1](course_requirements.md)，其来源和回退备份见S1 §6。忽略目录中的备份仅用于本地回退，不作为新增日常资料入口。

原报告参考文献的可复用线索保留如下，正式报告引用前另核对原文，不把未实施方法写为成果：

- NYC Motor Vehicle Collisions三源（ID见§2）；City of New York，Vision Zero Action Plan（2014）及官方Vision Zero网站。
- Kang B. *Identifying street design elements associated with vehicle-to-pedestrian collision reduction at intersections in New York City*. Accident Analysis & Prevention, 2019, 122: 308–317。
- Sehtman-Shachar S, Billig P C, Stein A, Kaplan S. *The immediate effects of vision-zero corridor upgrades on pedestrian crashes in New York: A before-and-after spatial point process approach*. Accident Analysis & Prevention, 2024, 200: 107531。
- Anderson T K. *Kernel density estimation and K-means clustering to profile road accident hotspots*. Accident Analysis & Prevention, 2009, 41(3): 359–364；Xie Z, Yan J. *Detecting traffic accident clusters with network kernel density estimation and local spatial statistics: an integrated approach*. Journal of Transport Geography, 2013, 31: 64–71。两者仅作备用方法背景。
- Silberschatz A, Korth H F, Sudarshan S. *Database System Concepts*, 7th ed., McGraw-Hill Education, 2019。用于数据库规范化与设计原理。
