# M1独立复核记录

日期：2026-09-29。只读权限审计与独立测试复验由专业子Agent执行，主Agent核对源码、实际目录、日志和最终diff后整合。

## 权限及配置审计

已修复并复核：worker从整库读取减到仅迁移版本；自定义函数撤销PUBLIC EXECUTE并以全局默认ACL阻止未来函数默认公开；函数固定pg_catalog/public/pg_temp顺序；Python维护入口自身核对容器和数据卷归属；本地秘密读写逐级拒绝symlink/reparse，pending独占创建；401同时清令牌、账户表和密码输入。

认证逐请求读取当前用户/角色/启用/auth_version；写事务先取得共用锁；API及DB共同保护最后管理员与在办执行人，真实两连接测试通过。HTTP验证错误不含input，驱动错误固定消息，SQL参数隐藏，密码与JWT不写审计。初始密码仅保留Git忽略文件，不输出到stdout。

未发现确认的P0/P1阻断项。应用角色读取所有业务关系是当前单服务设计边界；它包括将来导入的raw_record/person，M2导入前须复核API所需原始数据读取范围和输出投影。迁移角色是受信任的对象所有者，不等同运行账号。单进程内存限流与初始密码文件依赖本机工作区ACL均已明确；多实例限流、HTTPS/CORS和后续业务对象权限不在本阶段验收内。

## 独立测试

最终冻结版命令：`$env:VISION_ZERO_RUN_DB_TESTS='1'; .\.venv\Scripts\python.exe -X utf8 -m pytest backend\tests -q`。

82 passed、0 failed、0 skipped，48.28秒，退出码0，见[原始日志](tests-frozen.log)。先前77项、81项复验日志保留；新增配置/卷归属修复后有对应冻结复验。唯一警告为Starlette TestClient/httpx弃用提示。

实际PG17.11/PostGIS3.6.4，23业务表/34外键/70业务CHECK，另有扩展spatial_ref_sys的1个CHECK；3业务视图，另有扩展2视图。测试汇总中public CHECK=71、views=5，不能把扩展对象算成新增业务功能。

测试在随机独立数据库执行，验证空库/重复升级/base回退再升级/外部schema保留，约束失败/空间米制/运行角色拒绝/认证失效/两连接管理员和执行人竞争。开发库不降级、不写测试夹具，不删库/卷/角色。
