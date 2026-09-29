# M1物理数据字典

版本：M1 / 0002_business_model，2026-09-29。23表逐列按实际元数据生成，DDL冻结在迁移SQL中；真实数据库Alembic check通过。字段映射见[field_mapping](field_mapping.md)，关系见[关系模型](diagrams/relational.md)。

内部主键BIGINT Identity；官方collision/person/vehicle源键不自动生成。所有外键ON DELETE RESTRICT；NULL表示缺失，不能补0。API中的BIGINT标识使用字符串。JSONB保存输入、证据、审计及快照，关联键保持独立列。
## borough：行政区字典

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `borough_id` | `SMALLINT` | 否 | PK;  | `—` | 标准行政区标识 |
| `borough_name` | `VARCHAR(40)` | 否 | — | `—` | 标准行政区名称 |
| `display_name` | `VARCHAR(80)` | 是 | — | `—` | 界面显示名称 |
| `is_active` | `BOOLEAN` | 否 | — | `true` | 是否启用 |

完整性与索引：

- UNIQUE：`borough_name`。
- CHECK `ck_borough_id`：`borough_id BETWEEN 1 AND 5`。

## contributing_factor：原因字典

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `factor_id` | `BIGINT` | 否 | PK;  | `Identity` | 规范原因标识 |
| `canonical_name` | `TEXT` | 否 | — | `—` | 规范化字典名称 |
| `display_name` | `TEXT` | 是 | — | `—` | 界面显示名称 |
| `is_active` | `BOOLEAN` | 否 | — | `true` | 是否启用 |

完整性与索引：

- UNIQUE：`canonical_name`。
- CHECK `ck_factor_name`：`btrim(canonical_name) <> ''`。

## dataset_state：数据修订

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `state_id` | `SMALLINT` | 否 | PK;  | `—` | 固定为1的数据修订单例主键 |
| `revision` | `BIGINT` | 否 | — | `0` | 正式数据修订单例，M1初值0 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |
| `last_change_note` | `TEXT` | 否 | — | `—` | 最近修订原因 |

完整性与索引：

- CHECK `ck_dataset_singleton`：`state_id = 1 AND revision >= 0`。

## role：固定角色

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `role_id` | `SMALLINT` | 否 | PK;  | `—` | 固定角色标识 |
| `role_code` | `VARCHAR(20)` | 否 | — | `—` | 固定角色代码 |
| `role_name` | `VARCHAR(60)` | 否 | — | `—` | 角色中文名称 |

完整性与索引：

- UNIQUE：`role_code`。
- CHECK `ck_role_fixed`：`(role_id = 1 AND role_code = 'ADMIN') OR (role_id = 2 AND role_code = 'MANAGER') OR (role_id = 3 AND role_code = 'VIEWER')`。

## vehicle_type：车型字典

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `vehicle_type_id` | `BIGINT` | 否 | PK;  | `Identity` | 规范车型标识 |
| `canonical_name` | `TEXT` | 否 | — | `—` | 规范化字典名称 |
| `display_name` | `TEXT` | 是 | — | `—` | 界面显示名称 |
| `is_active` | `BOOLEAN` | 否 | — | `true` | 是否启用 |

完整性与索引：

- UNIQUE：`canonical_name`。
- CHECK `ck_vehicle_type_name`：`btrim(canonical_name) <> ''`。

## app_user：应用账户

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `user_id` | `BIGINT` | 否 | PK;  | `Identity` | 内部账户主键，API使用字符串 |
| `username` | `VARCHAR(80)` | 否 | — | `—` | 不区分大小写唯一的登录名 |
| `password_hash` | `TEXT` | 否 | — | `—` | Argon2id哈希，不返回前端 |
| `display_name` | `VARCHAR(80)` | 否 | — | `—` | 界面显示名称 |
| `role_id` | `SMALLINT` | 否 | FK→role.role_id | `—` | 固定角色标识 |
| `is_active` | `BOOLEAN` | 否 | — | `true` | 是否启用 |
| `auth_version` | `INTEGER` | 否 | — | `1` | 启停、换角色、改密、退出时递增，旧JWT失效 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |
| `version` | `INTEGER` | 否 | — | `1` | 乐观锁版本，更新提交expected_version |

完整性与索引：

- CHECK `ck_user_names`：`btrim(username) <> '' AND btrim(display_name) <> ''`。
- CHECK `ck_user_versions`：`auth_version > 0 AND version > 0`。
- 唯一索引 `uq_app_user_username_lower`（btree）：`lower(username)`。

## location：观察地点

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `location_id` | `BIGINT` | 否 | PK;  | `Identity` | 观察地点标识 |
| `location_key` | `TEXT` | 否 | — | `—` | 稳定观察地点键 |
| `key_input` | `JSONB` | 否 | — | `'{}'::jsonb` | 生成稳定键的规范化输入和版本，JSON对象 |
| `borough_id` | `SMALLINT` | 是 | FK→borough.borough_id | `—` | 标准行政区标识 |
| `zip_code` | `VARCHAR(20)` | 是 | — | `—` | 文本邮编，保留前导零 |
| `on_street_name` | `TEXT` | 是 | — | `—` | 道路名称 |
| `cross_street_name` | `TEXT` | 是 | — | `—` | 逻辑横街；API off_street_name映射到此列 |
| `off_street_name` | `TEXT` | 是 | — | `—` | 逻辑街道外地址；API cross_street_name映射到此列 |
| `geom` | `geometry(POINT,4326)` | 是 | — | `—` | WGS84观察点，可空，经度在前 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：

- UNIQUE：`location_key`。
- CHECK `ck_location_coordinates`：`geom IS NULL OR (NOT ST_IsEmpty(geom) AND ST_X(geom) BETWEEN -180 AND 180 AND ST_Y(geom) BETWEEN -90 AND 90)`。
- CHECK `ck_location_key_input`：`jsonb_typeof(key_input) = 'object'`。
- 索引 `ix_location_borough`（btree）：`location.borough_id, location.location_id`。
- 索引 `ix_location_geography`（gist）：`(geom::geography)`，WHERE `geom IS NOT NULL`。
- 索引 `ix_location_geom`（gist）：`location.geom`，WHERE `geom IS NOT NULL`。

## audit_log：操作审计

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `audit_id` | `BIGINT` | 否 | PK;  | `Identity` | 审计内部主键 |
| `actor_id` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 执行操作的应用账户 |
| `action` | `VARCHAR(60)` | 否 | — | `—` | 操作类型 |
| `entity_type` | `VARCHAR(50)` | 否 | — | `—` | 被操作对象类型 |
| `entity_id` | `TEXT` | 是 | — | `—` | 被操作对象标识文本 |
| `request_id` | `UUID` | 是 | — | `—` | 调用方UUID幂等键 |
| `details` | `JSONB` | 否 | — | `'{}'::jsonb` | 安全的审计摘要，不包含秘密 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：


## import_batch：导入批次

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `batch_id` | `BIGINT` | 否 | PK;  | `Identity` | 所属导入批次 |
| `request_id` | `UUID` | 否 | — | `—` | 调用方UUID幂等键 |
| `request_hash` | `VARCHAR(64)` | 否 | — | `—` | 操作者/操作/目标/payload的SHA-256；实际重放处理留后续业务API |
| `manifest_hash` | `VARCHAR(64)` | 否 | — | `—` | 输入清单SHA-256 |
| `cleaning_version` | `VARCHAR(40)` | 否 | — | `—` | 清洗规则版本 |
| `input_manifest` | `JSONB` | 否 | — | `'{}'::jsonb` | 输入文件、版本及处理快照清单 |
| `requested_start` | `DATE` | 是 | — | `—` | 导入请求日期闭区间起点 |
| `requested_end` | `DATE` | 是 | — | `—` | 导入请求日期开区间终点 |
| `status` | `VARCHAR(30)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `rows_read` | `BIGINT` | 否 | — | `0` | 读取的原始行总数 |
| `rows_accepted` | `BIGINT` | 否 | — | `0` | 接受的原始行数 |
| `rows_rejected` | `BIGINT` | 否 | — | `0` | 拒绝的原始行数 |
| `rows_skipped` | `BIGINT` | 否 | — | `0` | 重复等跳过的原始行数 |
| `created_by` | `BIGINT` | 否 | FK→app_user.user_id | `—` | 建立记录的应用账户 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 实际开始时刻 |
| `finished_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 完成时刻 |
| `published_revision` | `BIGINT` | 是 | — | `—` | 成功发布时的数据修订 |
| `worker_token` | `UUID` | 是 | — | `—` | 当前worker租约令牌UUID |
| `lease_expires_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | worker租约失效时刻 |
| `attempt_no` | `INTEGER` | 否 | — | `0` | 作业尝试次数 |
| `error_summary` | `TEXT` | 是 | — | `—` | 脱敏作业错误摘要 |

完整性与索引：

- UNIQUE：`request_id`。
- CHECK `ck_import_balance`：`status NOT IN ('READY', 'PUBLISHING', 'SUCCEEDED') OR rows_read = rows_accepted + rows_rejected + rows_skipped`。
- CHECK `ck_import_counts`：`rows_read >= 0 AND rows_accepted >= 0 AND rows_rejected >= 0 AND rows_skipped >= 0 AND attempt_no >= 0`。
- CHECK `ck_import_manifest_hash`：`manifest_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_import_manifest_object`：`jsonb_typeof(input_manifest) = 'object'`。
- CHECK `ck_import_period`：`(requested_start IS NULL AND requested_end IS NULL) OR (requested_start IS NOT NULL AND requested_end IS NOT NULL AND requested_start < requested_end)`。
- CHECK `ck_import_published`：`status <> 'SUCCEEDED' OR (published_revision IS NOT NULL AND published_revision > 0 AND finished_at IS NOT NULL)`。
- CHECK `ck_import_request_hash`：`request_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_import_status`：`status IN ('UPLOADED', 'VALIDATING', 'READY', 'PUBLISHING', 'SUCCEEDED', 'FAILED', 'CANCELLED')`。

## intersection：标准路口

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `intersection_id` | `BIGINT` | 否 | PK;  | `Identity` | 标准路口标识 |
| `intersection_code` | `VARCHAR(40)` | 否 | — | `—` | 唯一业务路口编号 |
| `borough_id` | `SMALLINT` | 是 | FK→borough.borough_id | `—` | 标准行政区标识 |
| `street_a` | `TEXT` | 否 | — | `—` | 标准路口道路A |
| `street_b` | `TEXT` | 否 | — | `—` | 标准路口道路B |
| `center_geom` | `geometry(POINT,4326)` | 否 | — | `—` | WGS84路口中心点，非空 |
| `status` | `VARCHAR(20)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `source_method` | `VARCHAR(30)` | 否 | — | `—` | 路口来源方法 |
| `is_active` | `BOOLEAN` | 否 | — | `true` | 是否启用 |
| `supersedes_id` | `BIGINT` | 是 | FK→intersection.intersection_id | `—` | 被此路口档案替代的旧档案 |
| `confirmation_note` | `TEXT` | 是 | — | `—` | 人工确认依据 |
| `confirmed_by` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 确认人账户 |
| `confirmed_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 人工确认时刻 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |
| `version` | `INTEGER` | 否 | — | `1` | 乐观锁版本，更新提交expected_version |

完整性与索引：

- UNIQUE：`intersection_code`。
- CHECK `ck_intersection_confirmation`：`status <> 'CONFIRMED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND confirmation_note IS NOT NULL AND btrim(confirmation_note) <> '')`。
- CHECK `ck_intersection_coordinates`：`NOT ST_IsEmpty(center_geom) AND ST_X(center_geom) BETWEEN -180 AND 180 AND ST_Y(center_geom) BETWEEN -90 AND 90`。
- CHECK `ck_intersection_fields`：`version > 0 AND btrim(street_a) <> '' AND btrim(street_b) <> ''`。
- CHECK `ck_intersection_source`：`source_method IN ('DERIVED', 'MANUAL', 'EXTERNAL')`。
- CHECK `ck_intersection_status`：`status IN ('CANDIDATE', 'CONFIRMED', 'REJECTED')`。
- CHECK `ck_intersection_supersedes`：`supersedes_id IS NULL OR supersedes_id <> intersection_id`。
- 索引 `ix_intersection_center`（gist）：`intersection.center_geom`。

## risk_rule：版本规则

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `rule_id` | `BIGINT` | 否 | PK;  | `Identity` | 规则版本内部标识 |
| `rule_code` | `VARCHAR(40)` | 否 | — | `—` | 规则业务代码 |
| `version_no` | `INTEGER` | 否 | — | `—` | 同规则代码的版本号 |
| `rule_name` | `TEXT` | 否 | — | `—` | 规则显示名 |
| `weight_collision` | `NUMERIC(10, 2)` | 否 | — | `—` | 每起事故权重 |
| `weight_injured` | `NUMERIC(10, 2)` | 否 | — | `—` | 每名受伤人员权重 |
| `weight_killed` | `NUMERIC(10, 2)` | 否 | — | `—` | 每名死亡人员权重 |
| `weight_vru` | `NUMERIC(10, 2)` | 否 | — | `—` | 每名弱势道路使用者伤亡的附加权重 |
| `threshold_medium` | `NUMERIC(12, 2)` | 否 | — | `—` | 中风险阈值 |
| `threshold_high` | `NUMERIC(12, 2)` | 否 | — | `—` | 高风险阈值 |
| `status` | `VARCHAR(20)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `rationale` | `TEXT` | 否 | — | `—` | 规则权重和阈值的说明 |
| `created_by` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 建立记录的应用账户 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：

- CHECK `ck_rule_status`：`status IN ('DRAFT', 'PUBLISHED', 'RETIRED')`。
- CHECK `ck_rule_values`：`version_no > 0 AND weight_collision >= 0 AND weight_injured >= 0 AND weight_killed >= 0 AND weight_vru >= 0 AND threshold_medium >= 0 AND threshold_high > threshold_medium AND weight_collision <> 'NaN'::numeric AND weight_injured <> 'NaN'::numeric AND weight_killed <> 'NaN'::numeric AND weight_vru <> 'NaN'::numeric AND threshold_medium <> 'NaN'::numeric AND threshold_high <> 'NaN'::numeric`。
- UNIQUE：`rule_code, version_no`。

## location_assignment：地点归属

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `location_id` | `BIGINT` | 否 | PK; FK→location.location_id | `—` | 观察地点标识 |
| `intersection_id` | `BIGINT` | 是 | FK→intersection.intersection_id | `—` | 标准路口标识 |
| `match_status` | `VARCHAR(30)` | 否 | — | `—` | 地点归属判断状态 |
| `match_method` | `VARCHAR(40)` | 否 | — | `—` | 地点归属方法 |
| `algorithm_version` | `VARCHAR(40)` | 否 | — | `—` | 归属算法版本 |
| `distance_m` | `NUMERIC(10, 2)` | 是 | — | `—` | 米制距离，非负且不是NaN |
| `evidence` | `JSONB` | 否 | — | `'{}'::jsonb` | 匹配判断证据 |
| `reviewed_by` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 地点判断复核账户 |
| `reviewed_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 地点判断复核时刻 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |
| `version` | `INTEGER` | 否 | — | `1` | 乐观锁版本，更新提交expected_version |

完整性与索引：

- CHECK `ck_assignment_distance`：`distance_m >= 0 AND distance_m <> 'NaN'::numeric`。
- CHECK `ck_assignment_review`：`match_status <> 'MANUAL_CONFIRMED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)`。
- CHECK `ck_assignment_status`：`match_status IN ('UNMATCHED', 'CANDIDATE', 'AUTO_MATCHED', 'MANUAL_CONFIRMED', 'REJECTED')`。
- CHECK `ck_assignment_target`：`match_status NOT IN ('AUTO_MATCHED', 'MANUAL_CONFIRMED') OR intersection_id IS NOT NULL`。
- CHECK `ck_assignment_version`：`version > 0`。
- 索引 `ix_assignment_intersection`（btree）：`location_assignment.intersection_id, location_assignment.location_id`。

## raw_record：原始行

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `raw_record_id` | `BIGINT` | 否 | PK;  | `Identity` | 原始行内部标识 |
| `batch_id` | `BIGINT` | 否 | FK→import_batch.batch_id | `—` | 所属导入批次 |
| `source_kind` | `VARCHAR(12)` | 否 | — | `—` | 三类官方数据来源枚举 |
| `row_no` | `BIGINT` | 否 | — | `—` | 原始输入行号，正整数 |
| `source_key` | `TEXT` | 是 | — | `—` | 原始来源记录键 |
| `payload` | `JSONB` | 否 | — | `'{}'::jsonb` | 不可覆盖的原始行JSON对象 |
| `row_hash` | `VARCHAR(64)` | 否 | — | `—` | 原始行SHA-256 |
| `validation_status` | `VARCHAR(20)` | 否 | — | `—` | 原始行校验状态，正式引用行须保持ACCEPTED |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：

- CHECK `ck_raw_hash`：`row_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_raw_line`：`row_no > 0`。
- CHECK `ck_raw_payload`：`jsonb_typeof(payload) = 'object'`。
- CHECK `ck_raw_source`：`source_kind IN ('CRASHES', 'PERSON', 'VEHICLES')`。
- CHECK `ck_raw_validation`：`validation_status IN ('UNVALIDATED', 'ACCEPTED', 'REJECTED', 'SKIPPED')`。
- UNIQUE：`batch_id, source_kind, row_no`。
- 索引 `ix_raw_batch_source_key`（btree）：`raw_record.batch_id, raw_record.source_kind, raw_record.source_key`。

## risk_run：计算批次

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `run_id` | `BIGINT` | 否 | PK;  | `Identity` | 计算批次标识 |
| `request_id` | `UUID` | 否 | — | `—` | 调用方UUID幂等键 |
| `request_hash` | `VARCHAR(64)` | 否 | — | `—` | 操作者/操作/目标/payload的SHA-256；实际重放处理留后续业务API |
| `rule_id` | `BIGINT` | 否 | FK→risk_rule.rule_id | `—` | 规则版本内部标识 |
| `period_start` | `DATE` | 否 | — | `—` | 周期闭区间起点 |
| `period_end` | `DATE` | 否 | — | `—` | 周期开区间终点 |
| `input_revision` | `BIGINT` | 是 | — | `—` | 本次计算读取的数据修订 |
| `status` | `VARCHAR(20)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `input_manifest` | `JSONB` | 否 | — | `'{}'::jsonb` | 输入文件、版本及处理快照清单 |
| `coverage_summary` | `JSONB` | 否 | — | `'{}'::jsonb` | 输入覆盖率和缺失摘要 |
| `requested_by` | `BIGINT` | 否 | FK→app_user.user_id | `—` | 请求运行的应用账户 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 实际开始时刻 |
| `finished_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 完成时刻 |
| `worker_token` | `UUID` | 是 | — | `—` | 当前worker租约令牌UUID |
| `lease_expires_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | worker租约失效时刻 |
| `attempt_no` | `INTEGER` | 否 | — | `0` | 作业尝试次数 |
| `error_summary` | `TEXT` | 是 | — | `—` | 脱敏作业错误摘要 |

完整性与索引：

- UNIQUE：`request_id`。
- CHECK `ck_run_complete`：`status <> 'SUCCEEDED' OR (input_revision IS NOT NULL AND finished_at IS NOT NULL)`。
- CHECK `ck_run_counts`：`attempt_no >= 0 AND (input_revision IS NULL OR input_revision >= 0)`。
- CHECK `ck_run_period`：`period_start < period_end`。
- CHECK `ck_run_request_hash`：`request_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_run_status`：`status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')`。

## collision：官方事故

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `collision_id` | `BIGINT` | 否 | PK;  | `—` | 官方COLLISION_ID；不是生成主键 |
| `location_id` | `BIGINT` | 否 | FK→location.location_id | `—` | 观察地点标识 |
| `crash_date` | `DATE` | 否 | — | `—` | 纽约当地事故日期 |
| `crash_time` | `TIME WITHOUT TIME ZONE` | 是 | — | `—` | 纽约当地事故时间，缺失不补零点 |
| `source_record_id` | `BIGINT` | 否 | FK→raw_record.raw_record_id | `—` | 对应本批已接受的正确来源原始行 |
| `imported_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 事故事实首次导入时刻 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |

完整性与索引：

- UNIQUE：`source_record_id`。
- CHECK `ck_collision_source_id`：`collision_id > 0`。
- 索引 `ix_collision_date_id`（btree）：`crash_date DESC, collision_id DESC`。
- 索引 `ix_collision_location_date`（btree）：`collision.location_id, collision.crash_date`。

## data_issue：质量问题

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `issue_id` | `BIGINT` | 否 | PK;  | `Identity` | 问题内部主键 |
| `batch_id` | `BIGINT` | 否 | FK→import_batch.batch_id | `—` | 所属导入批次 |
| `raw_record_id` | `BIGINT` | 是 | FK→raw_record.raw_record_id | `—` | 原始行内部标识 |
| `issue_code` | `VARCHAR(50)` | 否 | — | `—` | 质量问题代码 |
| `severity` | `VARCHAR(10)` | 否 | — | `—` | 质量问题严重性 |
| `field_name` | `TEXT` | 是 | — | `—` | 发生问题的来源字段 |
| `description` | `TEXT` | 否 | — | `—` | 业务说明 |
| `status` | `VARCHAR(20)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `resolution_note` | `TEXT` | 是 | — | `—` | 问题解决说明 |
| `resolved_by` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 处理人账户 |
| `resolved_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 问题解决时刻 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：

- CHECK `ck_issue_resolution`：`status <> 'RESOLVED' OR (resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND resolution_note IS NOT NULL AND btrim(resolution_note) <> '')`。
- CHECK `ck_issue_severity`：`severity IN ('INFO', 'WARNING', 'ERROR')`。
- CHECK `ck_issue_status`：`status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')`。
- 索引 `ix_issue_batch_status`（btree）：`data_issue.batch_id, data_issue.status`。

## risk_profile：路口画像

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `profile_id` | `BIGINT` | 否 | PK;  | `Identity` | 建立依据的风险画像标识 |
| `run_id` | `BIGINT` | 否 | FK→risk_run.run_id | `—` | 计算批次标识 |
| `intersection_id` | `BIGINT` | 否 | FK→intersection.intersection_id | `—` | 标准路口标识 |
| `collision_count` | `BIGINT` | 否 | — | `—` | 纳入画像的事故数量 |
| `injured_count` | `BIGINT` | 否 | — | `—` | 已知受伤人数合计 |
| `killed_count` | `BIGINT` | 否 | — | `—` | 已知死亡人数合计 |
| `vulnerable_road_user_count` | `BIGINT` | 否 | — | `—` | 已知行人和骑行者伤亡合计 |
| `incomplete_casualty_collision_count` | `BIGINT` | 否 | — | `—` | 评分必需伤亡字段缺失的事故数；大于0则UNKNOWN |

完整性与索引：

- CHECK `ck_profile_counts`：`collision_count > 0 AND injured_count >= 0 AND killed_count >= 0 AND vulnerable_road_user_count >= 0 AND incomplete_casualty_collision_count BETWEEN 0 AND collision_count`。
- UNIQUE：`run_id, intersection_id`。
- 索引 `ix_profile_intersection_run`（btree）：`risk_profile.intersection_id, run_id DESC`。

## casualty_stat：伤亡汇总

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `collision_id` | `BIGINT` | 否 | PK; FK→collision.collision_id | `—` | 官方COLLISION_ID；不是生成主键 |
| `persons_injured` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `persons_killed` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `pedestrians_injured` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `pedestrians_killed` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `cyclists_injured` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `cyclists_killed` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `motorists_injured` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |
| `motorists_killed` | `INTEGER` | 是 | — | `—` | 官方事故汇总计数；NULL为来源缺失，不从人员明细补算 |

完整性与索引：

- CHECK `ck_casualty_cyclists_injured`：`cyclists_injured >= 0`。
- CHECK `ck_casualty_cyclists_killed`：`cyclists_killed >= 0`。
- CHECK `ck_casualty_motorists_injured`：`motorists_injured >= 0`。
- CHECK `ck_casualty_motorists_killed`：`motorists_killed >= 0`。
- CHECK `ck_casualty_pedestrians_injured`：`pedestrians_injured >= 0`。
- CHECK `ck_casualty_pedestrians_killed`：`pedestrians_killed >= 0`。
- CHECK `ck_casualty_persons_injured`：`persons_injured >= 0`。
- CHECK `ck_casualty_persons_killed`：`persons_killed >= 0`。

## collision_factor：原因槽位

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `collision_id` | `BIGINT` | 否 | PK; FK→collision.collision_id | `—` | 官方COLLISION_ID；不是生成主键 |
| `factor_order` | `SMALLINT` | 否 | PK;  | `—` | 槽位1至5，与collision_id组成PK |
| `factor_id` | `BIGINT` | 否 | FK→contributing_factor.factor_id | `—` | 规范原因标识 |

完整性与索引：

- CHECK `ck_factor_order`：`factor_order BETWEEN 1 AND 5`。
- 索引 `ix_factor_collision`（btree）：`collision_factor.factor_id, collision_factor.collision_id`。

## governance_task：模拟工单

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `task_id` | `BIGINT` | 否 | PK;  | `Identity` | 模拟工单内部标识 |
| `task_code` | `VARCHAR(40)` | 否 | — | `—` | 唯一模拟工单编号 |
| `request_id` | `UUID` | 否 | — | `—` | 调用方UUID幂等键 |
| `request_hash` | `VARCHAR(64)` | 否 | — | `—` | 操作者/操作/目标/payload的SHA-256；实际重放处理留后续业务API |
| `profile_id` | `BIGINT` | 否 | FK→risk_profile.profile_id | `—` | 建立依据的风险画像标识 |
| `title` | `VARCHAR(160)` | 否 | — | `—` | 工单标题 |
| `description` | `TEXT` | 否 | — | `—` | 业务说明 |
| `measure_type` | `VARCHAR(40)` | 否 | — | `—` | 模拟治理措施类型 |
| `priority` | `VARCHAR(20)` | 否 | — | `—` | 工单优先级枚举 |
| `status` | `VARCHAR(30)` | 否 | — | `—` | 状态枚举，具体值见CHECK |
| `created_by` | `BIGINT` | 否 | FK→app_user.user_id | `—` | 建立记录的应用账户 |
| `assignee_id` | `BIGINT` | 是 | FK→app_user.user_id | `—` | 执行人账户 |
| `due_date` | `DATE` | 是 | — | `—` | 计划完成日期 |
| `effective_on` | `DATE` | 是 | — | `—` | 课程模拟措施实施日期 |
| `assessment_scope` | `JSONB` | 否 | — | `'{}'::jsonb` | 冻结的评价范围快照 |
| `is_simulated` | `BOOLEAN` | 否 | — | `true` | 固定true，课程模拟治理记录 |
| `deleted_at` | `TIMESTAMP WITH TIME ZONE` | 是 | — | `—` | 仅DRAFT可软删除 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |
| `version` | `INTEGER` | 否 | — | `1` | 乐观锁版本，更新提交expected_version |

完整性与索引：

- UNIQUE：`task_code`。
- UNIQUE：`request_id`。
- CHECK `ck_task_draft_delete`：`deleted_at IS NULL OR status = 'DRAFT'`。
- CHECK `ck_task_fields`：`version > 0 AND btrim(title) <> '' AND btrim(description) <> ''`。
- CHECK `ck_task_measure`：`measure_type IN ('MARKING_MAINTENANCE', 'SIGNAL_REVIEW', 'PEDESTRIAN_FACILITY_REVIEW', 'FIELD_SURVEY', 'OTHER')`。
- CHECK `ck_task_priority`：`priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')`。
- CHECK `ck_task_request_hash`：`request_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_task_simulated`：`is_simulated`。
- CHECK `ck_task_status`：`status IN ('DRAFT', 'OPEN', 'IN_PROGRESS', 'PENDING_REVIEW', 'COMPLETED', 'CANCELLED')`。
- 索引 `ix_task_assignee_status`（btree）：`governance_task.assignee_id, governance_task.status, updated_at DESC`，WHERE `deleted_at IS NULL`。
- 索引 `ix_task_profile`（btree）：`governance_task.profile_id`。

## person：官方人员

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `person_id` | `BIGINT` | 否 | PK;  | `—` | 官方PERSON unique_id；不是来源person_id |
| `collision_id` | `BIGINT` | 否 | FK→collision.collision_id | `—` | 官方COLLISION_ID；不是生成主键 |
| `source_person_id` | `TEXT` | 是 | — | `—` | 来源person_id文本，不作为主键 |
| `source_vehicle_id` | `TEXT` | 是 | — | `—` | 来源vehicle_id文本，不设人员到车辆的FK |
| `person_type` | `TEXT` | 是 | — | `—` | 来源人员类别文本 |
| `person_injury` | `TEXT` | 是 | — | `—` | 来源人员伤亡状态文本 |
| `person_age` | `SMALLINT` | 是 | — | `—` | 课程质量范围0至120，异常M2隔离 |
| `person_sex` | `TEXT` | 是 | — | `—` | 来源性别文本 |
| `source_record_id` | `BIGINT` | 否 | FK→raw_record.raw_record_id | `—` | 对应本批已接受的正确来源原始行 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |

完整性与索引：

- UNIQUE：`source_record_id`。
- CHECK `ck_person_age_quality`：`person_age BETWEEN 0 AND 120`。
- CHECK `ck_person_source_id`：`person_id > 0`。
- 索引 `ix_person_collision`（btree）：`person.collision_id`。

## vehicle：官方车辆

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `vehicle_id` | `BIGINT` | 否 | PK;  | `—` | 官方VEHICLES unique_id；不是来源vehicle_id |
| `collision_id` | `BIGINT` | 否 | FK→collision.collision_id | `—` | 官方COLLISION_ID；不是生成主键 |
| `source_vehicle_id` | `TEXT` | 是 | — | `—` | 来源vehicle_id文本，不设人员到车辆的FK |
| `vehicle_type_id` | `BIGINT` | 是 | FK→vehicle_type.vehicle_type_id | `—` | 规范车型标识 |
| `vehicle_year` | `SMALLINT` | 是 | — | `—` | 课程质量范围1886至2100，异常M2隔离 |
| `travel_direction` | `TEXT` | 是 | — | `—` | 来源行驶方向 |
| `pre_crash` | `TEXT` | 是 | — | `—` | 来源事故前车辆动作 |
| `point_of_impact` | `TEXT` | 是 | — | `—` | 来源撞击位置 |
| `vehicle_damage` | `TEXT` | 是 | — | `—` | 来源主要车辆损坏位置 |
| `source_record_id` | `BIGINT` | 否 | FK→raw_record.raw_record_id | `—` | 对应本批已接受的正确来源原始行 |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区更新时间 |

完整性与索引：

- UNIQUE：`source_record_id`。
- CHECK `ck_vehicle_source_id`：`vehicle_id > 0`。
- CHECK `ck_vehicle_year_quality`：`vehicle_year BETWEEN 1886 AND 2100`。
- 索引 `ix_vehicle_collision`（btree）：`vehicle.collision_id`。
- 索引 `ix_vehicle_type_collision`（btree）：`vehicle.vehicle_type_id, vehicle.collision_id`。

## task_history：事件历史

| 列 | PG类型 | 可空 | PK/FK | 默认/身份 | 含义 |
|---|---|---|---|---|---|
| `history_id` | `BIGINT` | 否 | PK;  | `Identity` | 历史事件内部主键 |
| `task_id` | `BIGINT` | 否 | FK→governance_task.task_id | `—` | 模拟工单内部标识 |
| `sequence_no` | `INTEGER` | 否 | — | `—` | 同工单事件顺序号 |
| `request_id` | `UUID` | 否 | — | `—` | 调用方UUID幂等键 |
| `request_hash` | `VARCHAR(64)` | 否 | — | `—` | 操作者/操作/目标/payload的SHA-256；实际重放处理留后续业务API |
| `event_type` | `VARCHAR(30)` | 否 | — | `—` | 工单事件枚举 |
| `from_status` | `VARCHAR(30)` | 是 | — | `—` | 事件前状态 |
| `to_status` | `VARCHAR(30)` | 否 | — | `—` | 事件后状态 |
| `actor_id` | `BIGINT` | 否 | FK→app_user.user_id | `—` | 执行操作的应用账户 |
| `note` | `TEXT` | 否 | — | `—` | 事件说明 |
| `changed_fields` | `JSONB` | 否 | — | `'{}'::jsonb` | 事件变更字段快照 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 否 | — | `now()` | 带时区创建时间 |

完整性与索引：

- UNIQUE：`request_id`。
- CHECK `ck_history_event`：`event_type IN ('CREATE', 'EDIT', 'PUBLISH', 'ASSIGN', 'START', 'PROGRESS', 'SUBMIT', 'APPROVE', 'REJECT', 'CANCEL', 'DELETE_DRAFT')`。
- CHECK `ck_history_fields`：`sequence_no > 0 AND btrim(note) <> ''`。
- CHECK `ck_history_from`：`from_status IN ('DRAFT', 'OPEN', 'IN_PROGRESS', 'PENDING_REVIEW', 'COMPLETED', 'CANCELLED')`。
- CHECK `ck_history_request_hash`：`request_hash ~ '^[0-9a-f]{64}$'`。
- CHECK `ck_history_to`：`to_status IN ('DRAFT', 'OPEN', 'IN_PROGRESS', 'PENDING_REVIEW', 'COMPLETED', 'CANCELLED')`。
- UNIQUE：`task_id, sequence_no`。

## 视图与跨表约束

| 对象 | 口径 |
|---|---|
| v_collision_base | 每事故一行，连接地点和唯一伤亡汇总，不连接人员/车辆明细 |
| v_risk_profile | 仅成功批次；统一计算score/等级/is_stale，缺失则NULL/UNKNOWN |
| v_governance_task | 展示依据画像、路口及用户，隐藏已软删DRAFT |

触发器保护只追加历史/审计，原始行、已引用地点、已发布规则、成功运行/画像；延迟检查每事故唯一伤亡行；校验原始来源类型/接受状态和问题批次；保护最后管理员、在办执行人；UNKNOWN仅FIELD_SURVEY的DRAFT。完整工单动作与对象权限函数留M5。

权限见[security](security.md)，函数依赖和快照边界见[normalization](normalization.md)。
