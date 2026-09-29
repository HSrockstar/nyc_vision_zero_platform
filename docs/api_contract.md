# M1认证与账户API

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

事故事实查询、导入、路口、风险、工单动作均是M2—M5接口，此阶段不存在。M1提供它们的表、约束、视图和幂等内容契约；不能通过用户API或任意SQL端点写入这些关系。
