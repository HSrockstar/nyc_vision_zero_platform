# ADR 0003：M1模型、业务契约与认证

- 日期：2026-09-29；实施范围为完整M1，M2—M8业务动作尚未开始。
- 保留 `0001_environment` 历史迁移，增加 `0002_business_model`。23表的固定DDL保存在迁移sql目录，历史迁移不导入未来ORM定义；ORM只参与当前自动差异检查。

## 契约定案

1. API街道映射按M0证据实施，JSON契约版本为nyc-api-v1，CSV按真实表头另核对。添加location.key_input保留地点摘要输入。
2. UNKNOWN画像允许FIELD_SURVEY调查草稿，禁止发布以及其他措施草稿；旧画像不会被新数据变为有效画像，数据补齐后以新画像另建任务。M1落库建立依据检查，完整创建/发布API与历史事务在M5实现。
3. OPEN、IN_PROGRESS、PENDING_REVIEW在办执行人禁止停用或任何角色变更。先按后续M5合法动作处理任务；不删除历史。用户维护和任务分配结构检查共用事务锁76301002，账户权限在取得锁后重新读取。
4. import_batch、risk_run、governance_task、task_history添加request_hash。request-v1摘要覆盖可信actor_id、固定operation、规范化target_id与已校验payload，UTF-8、键排序、无多余空格；日期/Decimal/ID先转字符串，禁止非有限浮点数。相同request_id内容不同须409，同内容还须重新做对象权限检查。M1提供摘要函数与持久字段；重试返回/发布动作在M2/M4/M5完成。

## 数据库边界

三种登录角色分别为 `<database>_migrator`、`<database>_app`、`<database>_worker`，都无superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS及成员继承。迁移角色拥有public业务对象；PostGIS由本机维护初始化，扩展所有者仍是维护账号。PUBLIC无本库CONNECT/TEMP和public CREATE；自定义触发器函数无PUBLIC EXECUTE。

M1应用角色读取业务关系，只有app_user INSERT/UPDATE及audit_log INSERT；不能直接写事故事实、工单状态或历史。worker本阶段只有就绪预检，因此仅授予alembic_version读取和public USAGE，后续按导入/计算用途前向授予权限。三类应用账户不对应三个数据库登录角色。

本机维护连接在Python执行层也核对Docker命名管道、专用容器标签、镜像、端口、数据卷及配置；不依赖使用PowerShell包装才能生效。角色冲突或未知成员关系拒绝，不重置未知角色密码。旧本地配置与角色恢复材料保存到Git忽略目录。

## 认证和回退

Argon2id存密码，HS256短JWT默认15分钟，限制1—30分钟并固定issuer/audience。每个受保护请求查当前账户启用、角色及auth_version。改密、启停、换角色和全会话退出使旧令牌失效；用户名不可改，显示名可改。首次管理员经本机CLI交互、环境变量或随机文件初始化，没有公开注册或固定密码。

写请求在账户事务锁后鉴权；事务提交发生在HTTP响应发送前。最后管理员由API及数据库触发器保护。所有业务错误固定消息，验证错误不返回提交的input；审计不保存密码、哈希或JWT。前端仅内存保存令牌，401清空账户视图，不使用持久存储或认证cookie。

开发库采用前向迁移，不提供自动降级删业务表。业务downgrade只允许新随机验证库，保留PostGIS、外部schema和角色。部署、真实数据发布及M5完整工单流程不包含在此次实现中。实际验收结论见 [M1模型记录](../milestones/M1-model.md)。
