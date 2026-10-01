# 中期演示脚本（M6）

用途：第10周中期检查的操作脚本与讲解要点。状态日期：2026-10-01。所有数据边界以开发库当前事实为准：2025全年官方事故85,546起、人员292,070条、车辆170,015条；95个已确认交叉口、95条2025年度画像（run 1，输入revision 98）；模拟治理工单在开发库中为空，治理演示需要独立验证库与合成账户（见第5节）。全程区分"真实碰撞数据"与"课程模拟治理任务"。

## 1. 数据来源、范围和缺失说明

- 打开登录页，先讲数据边界：三源官方CSV（Crashes/Person/Vehicles）于M2发布2025全年547,631行；事故日期左闭右开；缺失坐标（2,842起）、缺失伤亡值（死亡3起）与明细不完整均保留缺失状态，不补零。
- 系统操作时间与事故当地时间分开；页面首页不暗示数据更新到当天。
- 讲解依据：[M2记录](M2.md)、[字段映射](../field_mapping.md)。

## 2. 管理员导入/发布演示入口

- admin登录 → "事故查询与数据管理"上传区：演示三CSV上传表单、左闭右开范围声明、批次状态（校验→可发布→发布）与问题清单。
- 本轮不在开发库重复发布正式输入；演示可用[M2记录](M2.md)中已验收的重复导入证据（3,232行全部跳过、事实与revision不增量）说明幂等。
- 讲解要点：发布为原子事务，发布时同事务写revision与审计；失败批次不产生部分数据。

## 3. VIEWER事故查询与基础统计

- 切换只读账户（viewer）登录：事故查询页多条件筛选（日期/行政区/街道/车型/原因）、签名游标分页、事故详情（原因槽位、伤亡汇总、人员车辆分页；VIEWER人员无年龄性别）。
- 进入"统计报表"：总览、行政区、月度、小时、原因Top10、车型表格均可见；人员细分与模拟工单统计区块不显示，"下载统计报表CSV"按钮隐藏。
- VIEWER直接请求 `/api/v1/statistics/persons`、`/statistics/governance`、`/exports/statistics.csv` 均返回403（后端拒绝，不依赖按钮隐藏）；同一浏览器上下文先管理员后VIEWER时，人员/治理统计与受限按钮被清除，证据见[修正轮浏览器验收](../evidence/M6/fix1/m6_browser_acceptance_fix1.json)与[M6记录](M6.md)。

## 4. 地图、正式交叉口与风险画像

- 地图展示事故观察点与交叉口图层；说明2,842起缺坐标事故保留在列表与统计但不画点。
- 交叉口管理：95个已确认、1个已拒绝、4个待定；候选≠确认；正式归属（AUTO_MATCHED/MANUAL_CONFIRMED且交叉口CONFIRMED且启用）覆盖349起事故，覆盖率0.41%。
- 风险画像run 1：高14/中44/低37；展示分项贡献与评分公式 `S = 1×N + 3×I + 10×K + 5×V`；UNKNOWN与LOW区分；分数是历史碰撞指标，不是未来概率。
- 依据：[M3记录](M3.md)、[M4记录](M4.md)。

## 5. 两名管理人员的模拟治理流程（独立验证库）

开发库工单为0，本节在**独立合成验证库**演示（明确标记的测试环境与合成账户），不向开发库添加工单：

- manager A（创建者）从HIGH画像建立草稿 → 发布并分配给manager B。
- manager B开始执行 → 追加执行记录 → 提交复核。
- manager A复核通过（或先退回一次再通过）；期间演示：执行人自审被后端拒绝、同版本并发修改另一人409、同request_id重试幂等、历史时间线只追加且序号与version一致。
- 全程界面显示"课程模拟"标记。
- 环境准备：`.m6-work/prepare_browser.py` 建立随机合成库与四类账户；演示后保留该库供复核。

## 6. 工单历史和统计

- 任务详情页时间线：CREATE→PUBLISH→ASSIGN→START→PROGRESS→SUBMIT→APPROVE，每条含操作者、状态迁移、说明。
- "统计报表"页治理区块（ADMIN/MANAGER）：按状态/执行人/处理情况统计；未分配单列；总数不因历史条数重复累计；明确"已完成"依据状态COMPLETED。

## 7. CSV与打印

- **真实开发库成功下载范围**：统计页开始日选 `2025-01-01`，结束日（含当天）选 `2025-01-07`，其他筛选为空，先成功查询再点"下载事故CSV"；提交区间为 [2025-01-01, 2025-01-08)。2026-10-01 在开发库 REPEATABLE READ READ ONLY 快照下确认 **1,349 起 ≤ 5,000**（revision 98），见[只读范围核对](../evidence/M6/fix2/development-before.json)与[脚本](../evidence/M6/fix2/read_development.py)。原一月范围实际 **6,482 起**，不能用作成功导出演示；演示当天如数据版本变化，先重新查询确认行数。打开CSV讲解说明行、UTF-8中文与NULL空字段。本轮只读核对了真实范围，未实际下载开发库CSV。
- **合成浏览器验收与特殊文本示例**：独立验证库中 [2025-01-01, 2025-02-01) 为 **3 条合成事故**；实际浏览器下载落盘事故CSV 1,141字节、统计CSV 2,728字节，见[fix2报告](../evidence/M6/fix2/acceptance-02/acceptance.json)。逗号/引号/换行转义与公式字符防护使用合成夹具说明，不能声称是真实开发库首周样本内容。
- **超限拒绝演示用2025全年**：范围恢复默认全年（开发库85,546起 > 5,000）→ 下载得到"超过5000行上限，请缩小日期范围或其他筛选条件"的明确拒绝，不静默截断。
- "下载统计报表CSV"（ADMIN/MANAGER）：分节展示总览/行政区/月度（含伤亡缺失列）/小时/原因/车型/人员，同一数据库快照生成，为聚合结果、无5000行上限；其说明行revision与页面版本不同时前端会提示重新查询。
- "打印报表"：有效报表打印预览保留统计面板和已应用条件摘要（排他区间、行政区/街道/车型/原因、revision、口径、缺失/重叠说明、课程模拟标记），打印后四幅图表恢复屏幕尺寸。加载中、混合revision、失败、无有效报表或日期为空/倒置时，页面输出按钮停用；Ctrl+P或浏览器菜单的打印媒体隐藏标题、数据表和图表，只展示不可打印说明。旧成功结果可以在屏幕保留查看，并明确标注。见[新打印样例](../evidence/M6/fix2/acceptance-02/normal-print.pdf)和[18项独立回归](../evidence/M6/fix2/acceptance-02/acceptance.json)；[fix1报告](../evidence/M6/fix1/m6_browser_acceptance_fix1.json)作为历史轮次保留。

## 8. 一个去重聚合SQL及其手算结果

讲解原因统计SQL（`backend/app/statistics.py` `factors`，等价形式）：

```sql
WITH m6_scope AS (           -- 一事故一行：日期左闭右开 + EXISTS车型/原因筛选
  SELECT c.collision_id, s.persons_injured, s.persons_killed, ...
  FROM collision c
  JOIN location l USING (location_id)
  JOIN casualty_stat s USING (collision_id)
  WHERE c.crash_date >= :start AND c.crash_date < :end
    AND EXISTS (SELECT 1 FROM vehicle v
                WHERE v.collision_id = c.collision_id AND v.vehicle_type_id = :type)
)
SELECT f.canonical_name,
       COUNT(DISTINCT cf.collision_id) AS collision_count   -- 同事故同原因多槽位只计一次
FROM collision_factor cf
JOIN contributing_factor f USING (factor_id)
WHERE cf.collision_id IN (SELECT collision_id FROM m6_scope)
GROUP BY f.factor_id, f.canonical_name;
```

手算夹具（独立验证库，1月3起合成事故）：c1受伤2死亡0、两辆同车型、原因A占两个槽位；c2受伤2死亡1、车型A+B、原因A与B；c3伤亡全NULL、未知车型、无原因。预期与实测：事故3起；已知受伤4/缺失1；已知死亡1/缺失1；车辆5条、人员4条；原因A涉及2起不同事故（多槽位不放大）、B涉及1起；无原因事故1起；车型A车辆3条涉及2起事故。对应用例 `test_m6_statistics.py::test_manual_fixture_overview_and_groups`；初始轮11项定向日志是历史证据，当前16项M6测试的逐项结果见[fix2全量日志](../evidence/M6/fix2/pytest-full-final.log)。

## 9. 一个治理事务的状态、版本、权限和原子历史

- 写入路径：服务层认证后，同一事务调用受控函数 `change_task(...)`；先取M1共用账户锁，再锁任务行，重验角色、任务内身份、状态与 `expected_version`；更新任务、`version+1`、追加 `task_history`（`sequence_no`与新version一致）后一并提交。
- 任一步失败整体回滚：历史插入失败不留已变更状态；版本过期409；同request_id同内容幂等重放、异内容409；自审、越权身份、终态写入均被拒。
- 数据库侧由两个SECURITY DEFINER函数执行并固定 `search_path`，app/worker角色无权直接写工单与历史。依据：[ADR 0007](../decisions/0007-m5-governance.md)。

## 10. 当前完成清单和剩余范围

已完成（均有实库证据）：M0环境与数据探测；M1 23表/权限/认证；M2三源导入与事故查询；M3空间归属与交叉口档案；M4风险批次与画像；M5模拟治理全流程；M6统计整合、CSV导出、打印与中期演示材料。

剩余：M7（T01—T30补齐、B01—B04性能实验、权限核查、备份与新库恢复演练）；M8（最终报告、录像、干净环境交付核验）。P1（治理前后比较、物化视图、规则管理页面）仅在P0完成后评估。当前未提交或推送，Git状态以现场为准。
