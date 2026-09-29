# M2 安全终审

## 结论

在本轮限定范围和当前工作树状态下，没有确认的 P0、P1 或 P2 安全缺陷。此前发现的 multipart 解析先于 FastAPI 路由依赖校验问题已由新增上传入口预授权缓解：`UploadLimit` 在把请求交给 FastAPI 前校验 Bearer token、当前账户状态/版本和管理员角色；路由上的 `administrator` 仍会在写事务和账户锁下重新授权。

FastAPI 0.141.1 的路由实现先执行 `request.form()`，再调用 `solve_dependencies()`；因此上传入口的预授权是必要边界。参见 [FastAPI 0.141.1 routing.py](https://raw.githubusercontent.com/fastapi/fastapi/0.141.1/fastapi/routing.py) 中的 `get_request_handler`（body parsing 与 dependency resolution 顺序）。

## 已核查边界

- 身份与角色：JWT 校验后从数据库读取账户，核对 `is_active` 和 `auth_version`；角色来自当前数据库行。上传中间件做只读预检，写路由仍在 `ACCOUNT_LOCK` 下复核。见 [auth.py](../../../backend/app/auth.py:110) 与 [upload_limit.py](../../../backend/app/upload_limit.py:20)。
- API 投影与对象授权：普通查看角色只能读取人员类型/伤情字段；治理角色读取导入概况和规定的人车字段；原始 payload、导入问题与字典修改要求管理员。审计日志对治理角色按 `actor_id` 限制。当前系统采用全局角色授权，代码中没有租户/批次所有权模型，因此未将跨批次管理员访问认定为越权。见 [data_api.py](../../../backend/app/data_api.py:125)。
- 导入幂等与文件清理：请求摘要绑定操作者、操作、目标及内容；重复上传检查在账户 advisory lock 下串行，失败输入会清理随机暂存目录，数据库事务失败也会清理尚未登记的文件。见 [service.py](../../../backend/app/importing/service.py:20) 与 [storage.py](../../../backend/app/importing/storage.py:52)。
- worker 与发布：来源状态查询按当前批次的来源键/父键收窄；发布事务复核发布人仍为活动管理员，正式事实、修订号和批次状态在同一事务提交。数据库授权只给 worker 所需的账户列和审计返回列。见 [jobs.py](../../../backend/app/importing/jobs.py:106)、[jobs.py](../../../backend/app/importing/jobs.py:264) 与 [0003_import_pipeline.py](../../../backend/migrations/versions/0003_import_pipeline.py:44)。
- 数据库状态保护：触发器限制不可变输入与状态迁移，并限制 app/worker 的状态跃迁。GET/HEAD 会在首条 SQL 前将事务设为 `REPEATABLE READ READ ONLY`，列表、总数和 `data_revision` 取自同一快照。见 [0004_import_role_guard.sql](../../../backend/migrations/sql/0004_import_role_guard.sql:21) 与 [auth.py](../../../backend/app/auth.py:110)。
- 上传资源边界：实际 ASGI body 计数、每进程两个并发槽、单请求体读取时限和 256 MiB 文件上限均已实现；早期 413/429 回应复用同一 request id。授权预检失败在解析 multipart 前返回。

## 已排除项

- 未发现客户端可控角色或仅依赖 JWT 中旧角色的授权路径。
- 未发现 M2 查询接口上的未授权原始记录读取或批次/问题修改路径。
- 未发现上传文件名用于目录拼接；暂存文件名由服务器随机生成并以固定种类命名。
- 未发现本范围内的 SSRF、动态 SQL 注入或经 API 暴露密钥的路径。
- 重复请求清理、保存失败清理、数据库提交失败清理及发布事务回滚逻辑均有相应代码路径；本审查没有重新运行这些测试。

## 覆盖范围与盲区

覆盖 `backend/app/data_api.py`、`upload_limit.py`、`importing/*`、`auth.py` 的会话与鉴权逻辑、相关模型及 0003/0004 SQL/Alembic 迁移。检查只读；没有连接数据库、运行测试、读取 `.env`、私有配置或真实 raw 行。

上传并发 semaphore 与存储目录 quota lock 都是进程内对象。当前仓库开发启动脚本将 Uvicorn 绑定到 `127.0.0.1` 且未配置多 worker；本审查没有部署入口证据，不能确认代理、超时和多进程部署的聚合限制。若部署改为多 worker/多副本，应验证跨进程总并发及 4 GiB quota，必要时改为共享限额。该条件风险没有按当前本机范围列为漏洞。

父线程正在运行受影响的 M2 集成测试；本报告不把未由本审查执行/读取结果的测试写成通过。
