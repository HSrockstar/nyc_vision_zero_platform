# M1—M2关系模型与规范化依据

本文件解释23表的候选键与函数依赖；字段/约束完整列表见 [数据字典](data_dictionary.md)，联系见 [概念模型](diagrams/conceptual.md) 和 [关系模型](diagrams/relational.md)。每行的候选键分别确定该表其余属性；可空字段不会被当作唯一身份。

| 表 | 候选键 | 函数依赖及分解理由 |
|---|---|---|
| borough | borough_id；borough_name | 标准行政区决定显示名和启用状态，地点只保存外键 |
| role | role_id；role_code | 固定三角色，角色名称从用户表分离 |
| app_user | user_id；lower(username) | 登录名按大小写不敏感唯一；角色名称不复制，密码仅哈希 |
| import_batch | batch_id；request_id | 批次决定manifest、清洗版本、计数及当前发布请求；publish_request_id可空但非空时唯一，不能当作覆盖所有行的候选键；manifest_hash不唯一，失败/重试应保留 |
| raw_record | raw_record_id；(batch_id,source_kind,row_no) | 同来源键允许多条原始行；payload是不可变输入证据，验证状态可维护 |
| location | location_id；location_key | 地点属性与摘要输入属于观察地点；事故日期不属于地点键；坐标只保留geom |
| intersection | intersection_id；intersection_code | 标准交叉口与观察地点分开，替代关系不改旧身份 |
| location_assignment | location_id | 一个观察地点只有一个当前判断；判断方法/距离/证据依赖这一判断，交叉口信息不复制 |
| collision | collision_id；source_record_id | 事故决定报告日期/时间和当前来源；子表不复制事故日期 |
| person | person_id；source_record_id | 来源unique_id决定人员记录；文本person_id和vehicle_id不是候选键 |
| vehicle_type | vehicle_type_id；canonical_name | 车型名称字典与车辆事实分离 |
| vehicle | vehicle_id；source_record_id | 来源unique_id决定车辆记录；车型名称通过字典读取 |
| contributing_factor | factor_id；canonical_name | 原因名称独立存储，不在每个槽位重复维护 |
| collision_factor | (collision_id,factor_order) | 槽位决定原因；不能使用三字段主键允许同一槽位多原因 |
| casualty_stat | collision_id | 一事故一汇总；独立伤亡指标不是彼此决定，不强制总数等于子类和 |
| risk_rule | rule_id；(rule_code,version_no) | 一规则版本决定权重/阈值；发布后冻结，新规则建新版本 |
| risk_run | run_id；request_id | 周期/规则/输入快照由运行决定，不复制到每个画像 |
| risk_profile | profile_id；(run_id,intersection_id) | 同批次路口决定指标；分数与等级经统一视图计算 |
| governance_task | task_id；task_code；request_id | 工单通过profile_id取得交叉口，不存冗余intersection_id；评价范围是当时冻结依据 |
| task_history | history_id；request_id；(task_id,sequence_no) | 不可变事件记录；序号与工单版本对齐由M5动作事务落实 |
| data_issue | issue_id | 问题决定严重性/处理状态；raw_record与批次一致由触发器检查；M2按(batch_id,raw_record_id,issue_code,field_name)且NULLS NOT DISTINCT去重，批次级问题允许空引用 |
| audit_log | audit_id | 请求可触发多个审计事件，request_id不唯一；只追加 |
| dataset_state | state_id=1 | 单例revision用于过期标记，不等于任意历史版本可查询 |

事故、人员、车辆、地点、路口、规则、用户等正式基础关系按以上业务依赖分解，避免非键属性传递决定另一组可独立维护的实体属性。候选键不能仅因自增ID存在而省略分析；本设计保留来源键、自然唯一键和组合键。

raw_record.payload是原始文档，import_batch/risk_run manifest是处理元数据，task_history.changed_fields与工单assessment_scope是事件/历史快照，risk_profile是已发布聚合结果。这些字段允许JSONB或冻结派生存储，但没有把业务关联、身份、状态、周期及权限塞入JSON。它们的历史含义分别解释，不能以“所有表都有主键”宣称全部信息独立满足3NF。

v_collision_base保持一事故一行，不连接一对多人员、车辆或原因。v_risk_profile统一产生score、risk_level、is_stale，普通视图不保存可独立修改的分数。v_governance_task组装展示字段，未复制到工单基础关系。数据库中原始伤亡缺失仍是NULL，画像另存缺失事故数，因此不会把UNKNOWN变为LOW。

结构约束负责主外键、唯一性、NULL、枚举、非负、周期以及关键冻结边界；跨来源内容清洗、真实父子覆盖、完整批次原子发布和工单动作权限分别在M2—M5验证，本文件不代替业务验收。

## 明确的受控冗余

data_issue同时保留batch_id和可空raw_record_id，以支持批次级问题和行级问题。对行级问题存在raw_record_id→batch_id的非键函数依赖，因此这一支撑关系不声称严格满足3NF。跨表触发器强制二者同批，batch_id索引支持统一批次查询；这是有完整性约束的质量工作台冗余。若未来移除该查询需求，可以拆分批次问题与行问题。事件与输入JSON快照也按其历史语义评价，不能用基础关系3NF替代快照完整性检查。
