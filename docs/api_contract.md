# M1认证、M2数据、M3空间、M4风险、M5治理与M6统计API

前缀 `/api/v1`，JSON请求。成功返回 `{data,meta:{request_id}}`，错误返回 `{error:{code,message},meta:{request_id}}`；`X-Request-ID`支持UUID并在响应头返回。ID全部字符串；版本、数量和expires_in为数字。认证数据响应 `Cache-Control: no-store`。

| 方法 / 路径 | 输入 | 权限及结果 |
|---|---|---|
| POST /auth/login | username,password | 返回access_token、token_type=bearer、expires_in、user；失败401，限流429 |
| GET /auth/me | Authorization: Bearer | 返回当前账户、角色、当前阶段权限摘要；无效/失效令牌401 |
| POST /auth/logout | Authorization: Bearer | 增认证版本，当前账户全部会话失效 |
| POST /auth/change-password | old_password,new_password | 验旧密码、Argon2id更新、令牌失效；错误原密码400 |
| GET /users | page=1,page_size=20，最大100 | ADMIN；稳定user_id排序，返回items/total |
| POST /users | username,display_name,role,password | ADMIN；201；登录名大小写不敏感唯一；重复409 |
| PATCH /users/{user_id} | expected_version及display_name/role/is_active | ADMIN；版本冲突409；不能改用户名/密码/ID |

用户名为3—80位ASCII字母开头的字母、数字、下划线、点或连字符；显示名1—80字且非空白。新密码12—128字符，不记录或回显。三角色固定ADMIN、MANAGER、VIEWER；无公共注册、刷新令牌或管理员重置密码接口。

账户PATCH显式null、空修改、额外字段和非法ID返回422。停用或换角色导致认证版本增加；只有显示名变更不强制登出，但总version增加。最后管理员返回USER_LAST_ADMIN（409）；在办执行人返回USER_HAS_ACTIVE_TASKS（409）；VIEWER/MANAGER访问管理接口403。数据库约束冲突固定DATA_CONFLICT，不暴露驱动详情。

M2已实现以下数据接口。M3地图和路口、M4风险及M5治理动作见后续接口表。

| 方法 / 路径 | 输入与行为 | 权限 |
|---|---|---|
| GET /collisions | start/end左闭右开，默认2025全年；borough_id/street/vehicle_type_id/factor_id联合筛选；page_size默认20最大100；签名cursor；include_total默认false | 登录用户 |
| GET /collisions/{id} | 八项伤亡、地点、原因槽位与来源批次；缺失为null，ID字符串 | 登录用户 |
| GET /collisions/{id}/persons、/vehicles | page默认1；page_size默认20最大100；items/total | 登录用户；VIEWER人员仅记录ID、事故ID、类别、伤情，无年龄/性别/来源代码 |
| POST /imports | multipart：request_id、requested_start/end、header_mode=auto/api/display、crashes/persons/vehicles三个CSV；202返回UPLOADED | ADMIN |
| GET /imports、/imports/{id} | 列表page/page_size；计数/状态/修订；ADMIN另有文件摘要、校验和发布manifest | ADMIN、MANAGER；后者无文件、raw或问题详情 |
| POST /imports/{id}/publish | JSON request_id；READY进入PUBLISHING，由worker事务发布；202 | ADMIN |
| POST /imports/{id}/retry | JSON request_id；FAILED重新校验，上限10次作业尝试；不自动发布 | ADMIN |
| GET /imports/{id}/issues | 分页items/total；安全描述、来源、逻辑CSV行号，不返回payload | ADMIN |
| PATCH /data-issues/{id} | status=ACKNOWLEDGED/RESOLVED，resolution_note非空最大2000；不修改事实或隔离结果 | ADMIN |
| GET /raw-records/{id} | 原始CSV字段和值、批次及校验结果；页面不自动展示全文 | ADMIN |
| GET /dictionaries/{kind} | kind=vehicle-types/factors；items中的id/canonical_name/display_name/is_active | 登录用户 |
| PATCH /dictionaries/{kind}/{id} | 只允许display_name、is_active；规范值不可改 | ADMIN |
| GET /audit-logs | page/page_size，安全变更摘要 | ADMIN全范围、MANAGER本人、VIEWER拒绝 |

数据读取响应另有meta.data_revision。GET/HEAD使用只读一致事务快照，列表、总数和修订号保持一致。游标绑定筛选条件、分页大小与revision；条件或修订改变返回409 CURSOR_INVALID。原因和车型筛选用EXISTS，避免人员/车辆/原因连接放大事故总数；人员明细不替代Crashes伤亡汇总。

同一导入request_id绑定操作者、日期范围、版本、实际三文件SHA-256及表头模式；同内容重放返回既有批次，内容不同409。发布/重试请求号绑定操作、操作者和目标并保留历史。上传不接受服务器路径或URL，总CSV256MiB；multipart解析前先校验当前ADMIN身份，再限制实际请求字节（另留1MiB表单开销）和两并发；请求体读取空闲30秒、总300秒。每库原始副本4GiB配额，单CSV最多300万行/字段1MiB。未认证/无权限401/403，大小/并发超限413/429，读取超时408，CSV契约错误422；输入错误不回显源值或路径。

## M3空间与人工归属

| 方法 / 路径 | 输入与结果 | 权限 |
|---|---|---|
| GET /map/collisions | `start,end`左闭右开；`west,south,east,north`必填且递增；`limit`默认500、最大2000。返回地图点、`returned/truncated`和整个日期期的`total/geocoded/missing_coordinates/confirmed_assigned/unmatched` | 登录用户 |
| GET /map/nearby | `longitude,latitude,radius_m,limit`；半径1—1000米、返回最多200条并标记截断；geography米制距离 | 登录用户 |
| GET /intersections | `status`可选，范围可选但需四边界齐全；`page/page_size`，最大200条；候选和已确认对象分状态 | 登录用户 |
| GET /intersections/{id} | 状态、中心、最多20条关联地点及关联总数；复核说明只向管理角色返回 | 登录用户 |
| GET /location-assignments/{location_id} | 地点街道、坐标、当前归属/状态/版本；完整证据和复核时间只向管理角色返回 | 登录用户 |
| POST /intersection-candidates/generate | `borough_id`=1—5，`after_location_id`默认0，`max_locations`最多100，`radius_m`为20—80米；返回批次统计、下一游标及算法版本 | ADMIN、MANAGER |
| POST /intersections/{id}/confirm、/reject | `version,note`，仅候选可处理；版本或状态冲突409；同步处理受影响生成归属并增加数据修订 | ADMIN、MANAGER |
| PATCH /location-assignments/{location_id} | `version,status,intersection_id,reason`；状态为`MANUAL_CONFIRMED/REJECTED/UNMATCHED`，确认时目标必须是启用的已确认交叉口；版本冲突409 | ADMIN、MANAGER |

路口与地点ID以十进制字符串返回，输入不能通过JavaScript浮点数舍入。每个地点至多一个当前归属；事故通过地点继承归属。候选不计入已确认事故数。人工改派必须记录原因与审计，自动重跑不会覆盖人工结果。M3算法及部署范围见[ADR 0005](decisions/0005-m3-spatial.md)。

## M4风险接口

| 方法 / 路径 | 输入与行为 | 权限 |
|---|---|---|
| GET /risk-rules | 返回已发布/退休版本、权重、阈值、依据；不返回草稿 | 登录用户 |
| POST /risk-runs | request_id UUID、rule_id字符串、period_start/end日期；202排队；同请求同内容返回原任务，不同内容409 | ADMIN/MANAGER；发布前再次核验 |
| GET /risk-runs | start/end精确周期、rule_id、status可选；page/page_size默认20，最大100 | 登录用户 |
| GET /risk-runs/{run_id} | 状态、输入revision、coverage_summary、input_manifest、固定错误摘要及is_stale；不返回租约令牌 | 登录用户 |
| GET /risk-profiles | 必需run_id；risk_level、intersection_id可选；sort=score/collision_count降序，NULL末尾；page/page_size默认20最大100 | 登录用户；仅成功批次 |
| GET /risk-profiles/{profile_id} | 成功画像、四项已知值贡献、规则、批次来源及过期标记 | 登录用户 |

不存在的批次404；未成功批次画像列表为空且带run_status，详情404。成功但没有事故的周期不生成画像，coverage_ratio为null；不能解释为低风险。编号与修订号用字符串，Decimal分数/贡献/规则值用精确十进制字符串；未知分数为null。退休规则仅可查历史，新请求422。文件只通过受控本机入口保留，不提供Web路径读写。详见[ADR 0006](decisions/0006-m4-risks.md)。

## M5课程模拟治理任务

以下接口均要求当前启用的ADMIN/MANAGER；VIEWER读取和写入均403。路径前缀仍为`/api/v1`。

| 方法 / 路径 | 输入 | 结果与对象权限 |
|---|---|---|
| GET /governance-tasks | status、my_todo=false、page=1、page_size=20（1—100） | 排除软删除，返回items/total/page/page_size；我的待办限本人执行的OPEN/IN_PROGRESS/PENDING_REVIEW |
| GET /governance-tasks/assignees | search显示名（最多80字符）、page、page_size=100 | 当前启用ADMIN/MANAGER的ID、显示名、角色 |
| POST /governance-tasks | request_id、profile_id、title、description、measure_type、priority；due_date/effective_on可空，radius_m默认50（1—1000）、rationale可空 | 201，来自成功批次及当前启用CONFIRMED路口；LOW/MEDIUM必须给建立理由；UNKNOWN仅FIELD_SURVEY草稿 |
| GET /governance-tasks/{task_id} | — | 完整任务及allowed_actions；软删除仅创建者/当前ADMIN可见，其他404 |
| GET /governance-tasks/{task_id}/history | — | items按sequence_no排列，软删除可见性与详情相同 |
| PATCH /governance-tasks/{task_id} | 公共写入字段及至少一个可改字段：title/description/measure_type/priority/due_date/effective_on | 创建者/ADMIN，仅DRAFT；日期显式null表示清空，省略不变；不能更换profile或范围 |
| DELETE /governance-tasks/{task_id} | 公共写入字段，放JSON请求体 | 创建者/ADMIN，仅DRAFT软删除，保留历史 |
| POST /governance-tasks/{task_id}/publish | 公共写入字段及assignee_id | 创建者/ADMIN，DRAFT→OPEN；UNKNOWN拒绝发布 |
| POST /governance-tasks/{task_id}/assign | 公共写入字段及assignee_id | 创建者/ADMIN，仅OPEN重分配，执行人必须启用且为ADMIN/MANAGER |
| POST /governance-tasks/{task_id}/start | 公共写入字段 | 当前执行人，OPEN→IN_PROGRESS |
| POST /governance-tasks/{task_id}/progress | 公共写入字段 | 当前执行人，IN_PROGRESS追加记录 |
| POST /governance-tasks/{task_id}/submit | 公共写入字段 | 当前执行人，IN_PROGRESS→PENDING_REVIEW |
| POST /governance-tasks/{task_id}/review | 公共写入字段及decision=APPROVE/REJECT | 创建者/ADMIN但不得是当前执行人；通过→COMPLETED，退回→IN_PROGRESS |
| POST /governance-tasks/{task_id}/cancel | 公共写入字段 | 创建者/ADMIN，任意非终态→CANCELLED；UNKNOWN调查草稿允许取消 |

公共写入字段为`request_id`（UUID）、`expected_version`（正整数）、`note`（去空白后非空，最多10000字符）；创建只需request_id，不使用expected_version/note。title最多160字符，description最多10000，rationale最多2000。措施为MARKING_MAINTENANCE/SIGNAL_REVIEW/PEDESTRIAN_FACILITY_REVIEW/FIELD_SURVEY/OTHER，优先级为LOW/MEDIUM/HIGH/URGENT。

返回ID为字符串、version为整数，包含创建者与执行人显示名、原画像等级、`assessment_scope`冻结快照、`is_simulated=true`、deleted_at及当前身份可用动作。范围保存路口中心、米制半径和建立理由。历史包含event_type、from_status/to_status、actor_id/actor_name、note及changed_fields；sequence_no与该次任务version相同。

request-v1摘要绑定当前操作者、操作、目标、expected_version与规范化payload。同UUID同内容重放不增加版本或历史，返回任务当前投影（仍校验当前角色和软删除可见性）；同UUID不同内容409。新请求的旧版本409，失效状态409，对象身份无权限403，非法字段422。终态与软删除任务不允许新写；历史API为只读。客户端写失败应重新加载详情，不自动覆盖或盲目生成新的UUID重试。

## M6统计、导出与打印

所有事故统计接口共享同一筛选：`start/end`左闭右开（start≥end返回422 INVALID_RANGE）、`borough_id=1—5`、`street`（M2同规则转义；去首尾空白后为空视为无条件，街道字段全NULL的事故不被排除）、`vehicle_type_id`、`factor_id`。车型/原因筛选用EXISTS选出涉及的事故；车辆与人员记录数统计选中事故内的全部明细。伤亡为casualty_stat汇总口径：全部未知时合计返回NULL，缺失以独立计数返回；不同事故数与记录数分列。响应含`filters`摘要（street为自由文本，只返回street_filter布尔，不回显原文；未使用车型/原因筛选时口径文字为"符合当前筛选条件的事故及其全部明细"）。GET运行在REPEATABLE READ READ ONLY快照中，`meta.data_revision`与聚合同快照。

| 方法 / 路径 | 输入与结果 | 权限 |
|---|---|---|
| GET /statistics/overview | 不同事故数、已知受伤/死亡合计与缺失事故数、人员/车辆明细记录数、有坐标/缺坐标、正式归属已确认交叉口事故数及覆盖率（分母0为null，Decimal字符串） | 登录用户 |
| GET /statistics/boroughs | 分组事故数、伤亡合计与缺失；未知行政区单独成组（borough_id=null），不因字典INNER JOIN丢失 | 登录用户 |
| GET /statistics/trends | `granularity=month`（默认）或`hours`。month按月分组（含injured_missing_count/killed_missing_count伤亡缺失事故数），空月份计数为null并标注coverage（WITH_DATA/NO_RECORDS_COVERAGE_UNCONFIRMED/OUTSIDE_DECLARED_RANGES），不补零；月份跨度与统计CSV月度节共用120个月上限，超出422。hours返回0—23各小时计数与unknown_time_collision_count，缺失时间不并入0点 | 登录用户 |
| GET /statistics/factors | 按(collision_id, factor_id)去重的各原因不同事故数，降序；no_factor_collision_count单列无原因记录事故；组间可重叠 | 登录用户 |
| GET /statistics/vehicle-types | 各车型车辆记录数与不同事故数双计数；未知车型组保留（vehicle_type_id=null） | 登录用户 |
| GET /statistics/persons | 按person_type×person_injury的明细记录数；缺失保留未知；不与Crashes汇总对齐 | ADMIN/MANAGER；VIEWER 403 |
| GET /statistics/governance | 课程模拟工单统计：排除软删除；status/assignee_id/created_from/created_to（UTC创建日期，左闭右开）筛选；by_status/by_assignee（未分配单列）/measure_type/priority/handling；总数不连接历史记录；与事故筛选无关 | ADMIN/MANAGER；VIEWER 403 |

| 方法 / 路径 | 输入与结果 | 权限 |
|---|---|---|
| GET /exports/collisions.csv | 同/collisions筛选（无分页）；排序crash_date、collision_id升序；数据行上限5000，超限400 EXPORT_ROW_LIMIT要求缩小范围；UTF-8 BOM+CRLF；`#`说明行（不计入数据行）含生成时间、revision、排他区间、筛选与口径说明；NULL为空字段；文本列公式起始字符（=+-@，含前导空白/控制字符绕过）前置单引号防护 | 登录用户 |
| GET /exports/statistics.csv | 统一统计报表：单快照一次生成总览/行政区/月度（含缺失列）/小时/原因/车型/人员各节，含同样说明行；聚合结果不设事故CSV的5000行数据上限（说明行声明）；月度节与月度趋势共用120个月上限，超出422；权限同人员统计 | ADMIN/MANAGER；VIEWER 403 |

前端统计页面区分"正在编辑的表单"与"已应用筛选"：下载与打印绑定最近一次成功且revision一致的条件；日期无效提示且保留已展示报表；加载中/失败/revision不一致时输出停用；导出文件说明行的revision与页面版本不同时前端提示重新查询。打印含可打印标题与已应用条件摘要（`.print-header`）。修正轮细节见[ADR 0008](decisions/0008-m6-statistics-export.md)。
