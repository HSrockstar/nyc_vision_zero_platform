# M1认证、M2数据与M3空间API

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

M2已实现以下数据接口。M3地图和路口接口见下表；风险计算及工单动作仍按M4—M5推进。

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
