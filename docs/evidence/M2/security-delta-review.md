# M2 最新增量只读安全复核

主Agent集成补验（2026-09-30）：下文保留2026-09-29静态复核时的范围与待验记录。Docker恢复后，独立验证Agent已完成[24项M2 PostgreSQL回归](pytest-delta-postgres.log)，其中包含API/display两项父键空白规范化回归；[3项管理员边界](pytest-delta-roles.log)、[CLI隔离验收](retry-cli-isolated-smoke.log)及[迁移差异检查](alembic-check-delta.log)通过。年度真实发布与网页重复导入也已通过，见[最终状态](verification-status.json)及[M2记录](../../milestones/M2.md)。该补验不扩大本静态报告的审计范围；修复前P2已有动态验证证据。

日期：2026-09-29。范围限于 `backend/app/importing/jobs.py::source_state()` 的父键 `UNION` 查询、`backend/app/cli.py::retry-import`，以及直接影响它们的清洗、重试服务和数据库角色/状态约束。检查为静态读取；未连接数据库、未读取真实 raw 行、未运行年度重试或测试，也未修改产品代码。

## 结论

- P0：无确认发现。
- P1：无确认发现。
- P2：修复前确认 1 项——父键 SQL 规范化与清洗器不一致，会把合法子记录误判为缺失父事故并拒绝导入。主线程已在当前工作树修复；本复核静态确认空白集合与 `str.strip()` 对齐。真实 PostgreSQL 回归仍待 Docker 恢复后完成，故不宣称动态验证通过。
- `retry-import` 的数据库状态、审计和事务边界未见本次增量造成的绕过。CLI 身份依赖仓库声明的本机受信维护入口；若未来扩展到非管理员可执行 CLI 的部署模式，需要重新审查主体绑定。

## 信任边界与范围核对

- 父键来自 `raw_record.payload`，查询同时要求当前 `batch_id` 和固定的 `CRASHES`、`PERSON`、`VEHICLES` 类型。正式父事故只按这个批次来源键集合读取；既有正式事实也只按当前批次、当前类型的 `source_key` 查行哈希和清洗版本。[jobs.py:106](../../../backend/app/importing/jobs.py:106) [jobs.py:111](../../../backend/app/importing/jobs.py:111) [jobs.py:116](../../../backend/app/importing/jobs.py:116)
- 查询由 SQLAlchemy 表达式构造，批次号、来源类型和 JSON 字段名不是拼接到 SQL 的用户字符串；JSON 字段名来自固定的 `HEADERS` 配置。当前路径未发现 SQL 注入。父键集合替代逐正式父行执行 JSON `OR EXISTS` 的查询形态；收到的运行数据为 547,631 行耗时 2.642 秒，这个测量由主审提供，本复核未独立连接数据库验证。
- HTTP 重试路由使用 `ADMIN = Depends(administrator)`，上游会话检查 JWT、账户活动状态、认证版本和数据库角色；随后批次行加锁再进入共同的 `request_action()`。[data_api.py:27](../../../backend/app/data_api.py:27) [data_api.py:199](../../../backend/app/data_api.py:199) [auth.py:161](../../../backend/app/auth.py:161) [auth.py:175](../../../backend/app/auth.py:175)
- 本机 CLI 使用应用数据库连接，持有账户 advisory lock 和批次行锁，并从数据库重新读取活动管理员角色。M2 迁移为应用角色授予了重试所需的批次状态/请求字段更新权；worker 查询事实和 raw 输入使用已有 worker 角色。该增量没有新增数据库权限授予。[cli.py:85](../../../backend/app/cli.py:85) [cli.py:87](../../../backend/app/cli.py:87) [0003_import_pipeline.py:38](../../../backend/migrations/versions/0003_import_pipeline.py:38) [0003_import_pipeline.py:44](../../../backend/migrations/versions/0003_import_pipeline.py:44)

## P2：父键空白规范化不一致会误拒绝子记录（修复前发现）

- **证据位置：** 修复前 SQL 父键使用 `ltrim(btrim(...), '0')`，而默认 `btrim` 只去普通空格。清洗器在 `text_value()` 中使用 Python `str.strip()`，再由 `source_id()` 接受去除空白后的 ASCII 正整数：[cleaning.py:61](../../../backend/app/importing/cleaning.py:61) [cleaning.py:68](../../../backend/app/importing/cleaning.py:68)。父键未进入映射时，清洗器将该行标为 `MISSING_PARENT` 并拒绝：[cleaning.py:163](../../../backend/app/importing/cleaning.py:163) [cleaning.py:167](../../../backend/app/importing/cleaning.py:167)。
- **可利用前提：** 当前批次的 PERSON 或 VEHICLES 行引用一个已在正式库中的事故；当前批次的 CRASHES 来源键集合不含该事故；子行父键在数字外围含 tab 或换行等 `str.strip()` 可移除、而 PostgreSQL 默认 `btrim` 不移除的字符。该批次仍可包含其他事故行。
- **影响：** SQL 半连接不取回已存在的父事故；后续 Python 规范化却把父键解析为原有编号，最终因映射缺失把合法行隔离为错误记录。正式事实不会被错误写入，但该子记录无法由这个不可变输入批次发布，导致导入不完整。
- **最小复现思路：** 只在合成验证库中预置父事故编号 `N`；建一个子记录父键为 `\t000N\n` 的批次，并确保该批次 CRASHES 来源键不含 `N`。修复前调用 `source_state()` 后父映射不含 `N`，`normalized()` 会得到 `MISSING_PARENT/REJECTED`。该复现未连接真实库，也未在本复核中运行。
- **修复状态：** 当前 `jobs.py:110-111` 定义 trim 字符集合，再对父键先 `btrim(..., trim_chars)`、后去掉前导零：[jobs.py:109](../../../backend/app/importing/jobs.py:109) [jobs.py:110](../../../backend/app/importing/jobs.py:110) [jobs.py:111](../../../backend/app/importing/jobs.py:111)。集合逐项覆盖 Python `str.strip()` 的 29 个空白码位：ASCII `U+0009–U+000D`、`U+001C–U+0020`，以及 `U+0085`、`U+00A0`、`U+1680`、`U+2000–U+200A`、`U+2028`、`U+2029`、`U+202F`、`U+205F`、`U+3000`；静态核对后没有发现缺项或多项。SQLAlchemy 将固定字符集作为表达式值传给 `btrim`，未引入用户可控 SQL。该修复保持当前批次父键半连接范围。主线程报告代码编译与 diff check 已通过，本复核未重跑；合成 PostgreSQL 回归和真实库复验待 Docker 恢复后进行。
- **建议测试：** 合成父事故存在于正式表、当前批次没有对应 CRASHES 键时，分别验证普通空格、tab、换行及 29 字符集合里的 Unicode 空白都能解析到同一父事故；同时确认无效字符不会被误删后匹配，以及当前批次 CRASHES 父行路径仍通过。该测试尚未由本复核执行。

## 重试状态、幂等、审计与回滚

- CLI `retry-import` 复用 `request_action()`：只允许 `FAILED`，尝试次数达到 10 后拒绝；请求更新为 `UPLOADED`、清空租约和完成状态，不设置发布请求，也不会直接写正式事实。[cli.py:73](../../../backend/app/cli.py:73) [cli.py:98](../../../backend/app/cli.py:98) [service.py:64](../../../backend/app/importing/service.py:64)
- 同一 `request_id` 的摘要绑定 actor、操作和批次；同目标同请求重放返回已登记结果，跨目标或操作冲突则拒绝。请求事件和 `IMPORT_RETRY_REQUESTED` 审计与状态更新处于同一 CLI/API 事务。[service.py:45](../../../backend/app/importing/service.py:45) [service.py:77](../../../backend/app/importing/service.py:77) [service.py:82](../../../backend/app/importing/service.py:82)。CLI 未提供 `--request-id` 时会生成新 UUID，所以需要调用方在不确定提交结果后显式复用同一 UUID，才能获得跨命令调用的幂等性；这不构成越权路径。
- worker 将 `UPLOADED` 领取为校验作业；重试本身不自动发布。正式发布在一个事务中写事实、修订号和成功状态；异常时事务回滚，再由独立失败事务登记 `FAILED` 与失败审计。[jobs.py:63](../../../backend/app/importing/jobs.py:63) [jobs.py:264](../../../backend/app/importing/jobs.py:264) [jobs.py:317](../../../backend/app/importing/jobs.py:317)。状态触发器允许 `FAILED → UPLOADED`，并拒绝 worker 自行授权 `READY → PUBLISHING`。[0004_import_role_guard.sql:21](../../../backend/migrations/sql/0004_import_role_guard.sql:21) [0004_import_role_guard.sql:29](../../../backend/migrations/sql/0004_import_role_guard.sql:29)

## 条件边界与盲区

- **CLI actor 依赖本机受信执行边界。** `retry-import --username` 是调用者可控参数，CLI 只确认其对应数据库用户处于活动状态且角色为 ADMIN，没有密码校验或 OS 用户绑定；CLI 审计以该数据库用户作为 actor。[cli.py:73](../../../backend/app/cli.py:73) [cli.py:85](../../../backend/app/cli.py:85) [cli.py:89](../../../backend/app/cli.py:89)。仓库安全策略明确 CLI 属于本机受信维护入口，当前开发模式无远程 CLI 执行模型：[security.md:3](../../security.md:3) [security.md:36](../../security.md:36)，因此本轮未把 `--username` 记为确认漏洞。若后续部署允许非管理员主体执行 CLI 并使用应用数据库配置，才需要验证是否能冒用活动管理员登记重试及伪造审计归属；安全标准是维持 OS/文件 ACL 的受信边界，或改为真实凭据绑定 actor。
- 未核实实际本机账户 ACL、Docker 恢复后的 PostgreSQL 执行结果、正式部署代理/账户、跨进程 worker 配置或真实数据库授权状态；不读取 `.env`、密钥、真实来源数据。合成数据库回归与真实库复验待主线程恢复 Docker 后继续。既有 [M2 安全终审](../../evidence/M2/security-review.md) 中不属于本次增量的结论未在此重复验证。
