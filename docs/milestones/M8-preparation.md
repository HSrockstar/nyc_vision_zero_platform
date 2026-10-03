# M8：报告固定章节与隔离演示准备

日期：2026-10-03。当前交付为[报告固定章节草稿](../report/固定章节草稿.md)、[数据流图](../diagrams/data-flow.md)、[T01—T30证据映射](../testing/T01-T30.md)及可重复建立的独立演示库。最终1.0万—1.5万字报告、重构后的页面截图/浏览器全流程、录像和干净机器安装仍待完成。

## 演示数据边界

事故、人员、车辆与画像来自已验证的真实数据备份。模拟账户、工单和治理记录由本机工具建立，标题和说明明确标为“课程模拟”；它们不表示纽约政府实际治理。风险画像仍限已确认95个路口、349/85,546起事故（约0.41%），不能据此声称覆盖全市风险。

演示库由已通过M7完整恢复验证的新库播种。命令仅接受已完成恢复的新目标，拒绝已有演示凭据或业务任务的库。四个演示账户为 `demo_admin`、`demo_manager`、`demo_executor`、`demo_viewer`，分别对应ADMIN、MANAGER、MANAGER、VIEWER；密码随机生成，仅保留在 `.m8-work/demo/<库名>/credentials.json` 的受限目录，禁止放入报告、日志、截图或Git。

生成六张工单，分别停在DRAFT、OPEN、IN_PROGRESS、PENDING_REVIEW、COMPLETED、CANCELLED；通过既有治理动作建立历史。管理人员创建与复核、另一管理人员执行，保留禁止自审和VIEWER拒绝路径。创建新的模拟管理员后停用复制来的原账户，原开发库账户不变。源事故事实与风险画像不因播种改变。

实际演示库为 `vision_zero_m1_test_a820261003de`：[播种摘要](../evidence/M7/demo-summary.json)记录4个新账户、1个复制账户停用、6种状态各1张工单及19条历史。[真实HTTP验收](../evidence/M7/demo-http.json)18项全部通过，包括四角色登录、查询、统计、VIEWER越权拒绝、执行人自审拒绝和拒绝后版本不变；临时Uvicorn已停止。[worker前台入口](../evidence/M7/demo-worker-console.log)退出码0、idle。

播种后19张未涉及模拟账户/审计/工单/历史的表与开发库备份逐表哈希一致，见[事实保持证据](../evidence/M7/demo-source-facts-unchanged.json)。演示库再次备份，并完整恢复到 `vision_zero_m1_test_a920261003de`；[恢复证据](../evidence/M7/restore-demo.json)证明非空治理历史及全部23表摘要、结构、序列和权限一致。新恢复副本的数据库登录凭据独立重建，应用模拟账号仍是原演示备份内账号，其随机密码保留在a820私有凭据文件。

## 重复准备与启动

先按[M7恢复说明](M7.md)从 `.m7-work/backups/m7-20261003-final` 恢复到另一个全新目标，再播种；不要覆盖已有演示库。“重置演示”就是再恢复一个新库，旧库保留作证据，不提供一键清空。

```powershell
# $target 为本轮新建并已通过恢复的随机库名
Push-Location backend
try {
  ..\.venv\Scripts\python.exe -X utf8 -m app.cli seed-demo --database $target
  if ($LASTEXITCODE -ne 0) { throw '演示准备失败，保留现场' }
} finally { Pop-Location }

# 两个终端分别前台运行；Ctrl+C停止
.\.venv\Scripts\python.exe -X utf8 scripts/run_isolated.py backend --database $target --port 8002
.\.venv\Scripts\python.exe -X utf8 scripts/run_isolated.py worker --database $target
```

`run_isolated.py`只监听 `127.0.0.1`，只对子进程载入目标配置，不修改根 `.env`。它拒绝开发库和缺少成功恢复记录的库。现有前端自定义后端地址使用 `VISION_ZERO_API_TARGET`（见[README](../../README.md)）；本会话未启动、检查或修改前端，接入方式及页面表现由前端重构会话验收。

建议展示次序：用VIEWER说明事故、缺失值和统计范围；用管理人员说明真实画像与选址范围；打开已完成工单查看多人处理历史；从待执行或待复核工单继续一次授权动作；查看治理统计的模拟标识。演示会改变隔离库工单状态，需要重复相同起点时另建新库。

## 报告收尾清单

- 保留现有需求、模型、约束、事务、权限、数据追溯、性能和恢复章节，引用实际证据；可直接利用ER图、状态图和数据流图。
- 前端重构稳定后补页面设计、桌面/窄屏截图、T10/T29和完整业务链的浏览器验收。
- 完成最终字数、图表与引用核对；记录全新环境依赖安装、迁移、恢复、后端/worker/前端启动结果。
- 录制时区分官方碰撞数据与课程模拟治理，避开密码、令牌和本地配置。按课程要求人工核对交付包与提交事项。

未执行P1治理效果比较、物化视图、扩大真实路口确认范围或课程平台提交。本轮不承诺模拟工单能证明治理因果效果。
