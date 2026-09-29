# M1数据库与认证权限

本阶段为本机开发，数据库与后端只监听loopback；Vite同源代理访问后端，没有跨域白名单或认证cookie。远程部署HTTPS/CORS及后续上传边界另行验收。

| 数据库账号 | 所有权与允许能力 | 拒绝的能力 |
|---|---|---|
| 本机postgres维护账号 | 校验专用容器后初始化PostGIS、配置专用角色 | 不由Web/worker使用；不操作其他数据库 |
| vision_zero_dev_migrator | 拥有public业务对象、执行Alembic及首次管理员初始化 | 无集群管理员、创建数据库/角色、复制、绕过RLS或其他角色成员权 |
| vision_zero_dev_app | 读取业务关系；INSERT/UPDATE app_user；INSERT audit_log；仅相应两个序列USAGE | 不能建表/扩展、修改事故事实/规则/工单/历史、删除用户/审计 |
| vision_zero_dev_worker | public USAGE、alembic_version SELECT、PostGIS就绪检查 | 本阶段不读人员/原始行/账户密码，不写任何业务表 |

随机验证库使用相同命名后缀但独立角色及随机密码。业务用户ADMIN/MANAGER/VIEWER是app_user+role中的身份，后端逐请求判断，与数据库运行账号权限不同。运行凭据不发给前端。

PUBLIC被撤销专用库CONNECT/TEMP、public CREATE及全部自定义触发器函数EXECUTE。PostGIS函数保留官方扩展所需执行权，运行账号没有CREATE以安装扩展。tiger/tiger_data/topology的PUBLIC schema访问在专用库撤销，不改其他项目数据库。高权限用户触发器固定 `search_path=pg_catalog,public,pg_temp`，关系全限定public；其他触发器以调用者权限执行。后续M5写函数必须独立审查并限制PUBLIC EXECUTE。

provision-roles使用随机凭据、角色归属注释和最小权限属性，未知同名角色或成员关系拒绝；当前.env先备份，角色材料先写忽略目录再变更库，最后原子更新.env。秘密文件路径逐级拒绝符号链接/重解析点，临时文件独占创建；不覆盖预置pending文件。Python维护连接校验本机Docker endpoint、运行容器镜像/标签/端口/卷及数据库配置，脚本与直接CLI入口都执行边界校验。

认证使用Argon2id及15分钟HS256 JWT，固定算法/issuer/audience和必需claims，签名密钥由48字节随机源生成。逐请求从库读取当前角色、启用状态和auth_version；改密、启停、换角色、退出使已有令牌失效。退出作用于该用户全部设备。令牌只在页面内存，刷新需重登，401清空当前账户和用户表。

登录失败按规范化用户名5次/5分钟、连接IP30次/5分钟限制，包含进行中的尝试。Vite代理用户共享本机IP，因此用户名桶分别限制账户，IP桶阻挡多账户喷洒；不信任任意转发头。此实现只支持单后端进程，重启会清空限流状态，不能宣称跨节点全局限流。

账户写事务先取得统一事务锁76301002，再重新校验当前身份和版本。最后可用管理员保护同时存在于API和数据库触发器；在办执行人的停用/角色变更与任务分配结构检查共用锁。未来M5动作函数要保持同一锁顺序。认证和审计提交在HTTP响应发送前完成。

首次管理员通过本机CLI初始化；已存在可用管理员时拒绝重复初始化。交互/环境变量密码不会输出到stdout；`--generate`仅将随机初始密码写到Git忽略的 `.m1-work/model/initial-admin.txt`，不覆盖已有文件。初始化后的账户维护必须经管理员API。

错误不返回数据库异常、DSN、密码或验证input；SQLAlchemy隐藏参数。审计仅保存操作者、请求ID及安全的变更摘要，不保存密码、密码哈希、JWT或完整DSN。开发库不执行业务downgrade；随机验证库可回退再升级，测试库与相关角色保留供复核。

方法依据：[PostgreSQL 17权限](https://www.postgresql.org/docs/17/ddl-priv.html)、[函数安全边界](https://www.postgresql.org/docs/17/sql-createfunction.html)、[FastAPI密码/JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)。具体兼容性以本项目固定版本测试证据为准。
