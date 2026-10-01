# ADR 0008：M6 统计口径、导出与打印

日期：2026-10-01。状态：已实现并通过本机验收。关联：PROJECT_PLAN §13、§15.5—15.7、§16、§19.8。

## 背景

M6 需要总览、行政区、月度/小时趋势、原因、车型、人员细分、模拟工单统计、CSV 导出和打印。核心风险是多表连接放大事故与伤亡计数、空月份被伪造为 0、导出与页面口径不一致。

## 决定

### 1. 统一口径：先定事故集合，再统计明细

所有事故统计先构造一事故一行的筛选集合（`backend/app/statistics.py` 的 `collision_scope`）：`collision` 连接 `location`（LEFT JOIN `borough` 保留未知行政区）与一对一 `casualty_stat`，日期左闭右开 `[start, end)`；车型与原因筛选使用相关 EXISTS，只负责"选出涉及该车型/原因的事故"。选中集合内的车辆记录数、人员记录数统计这些事故的**全部**明细，不按筛选维度裁剪明细。该口径在页面、接口响应与 CSV 说明行中一致声明。

伤亡只取 `casualty_stat` 汇总字段：`SUM` 为已知值合计，全部未知时返回 NULL（不使用 COALESCE 变成 0），缺失计数用 `COUNT(*) FILTER (WHERE … IS NULL)`。严禁事故×人员×车辆×原因全连接后求和；`COUNT(DISTINCT collision_id)` 仅用于原因/车型分组内的事故去重，不同事故可能伤亡数相同，不使用 `SUM(DISTINCT …)`。

- 原因统计按 `(collision_id, factor_id)` 去重：同事故同原因多槽位只计一次；同事故可进入多个原因组，组间重叠，不做互斥占比图；无原因记录的事故单列 `no_factor_collision_count`，不与来源中的 Unspecified 混同。
- 车型统计同时返回车辆记录数与不同事故数，两个计数单位分开命名；缺失车型保留未知组。
- 人员统计按原始 `person_type × person_injury` 的明细记录数，缺失类别/状态保留未知；不与 Crashes 汇总对齐，不新增年龄性别分布。
- 正式归属沿用 M3/M4 定义：`location_assignment.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED')` 且交叉口 `CONFIRMED` 且启用；候选与拒绝不计入。覆盖率为归属事故数 ÷ 当前筛选事故总数，分母 0 返回 NULL。
- 复用 M2 筛选实现：`data_api.collisions` 委托同一 `apply_collision_filters`，列表、统计、导出共享一套含义（street 转义 `%`、`_`、`\`）。

### 2. 月度空月份不补零

只有确认来源覆盖的空月份才允许补零。当前证据（导入批次 manifest 的 `validation.coverage.selected_range`）是**声明范围**，不构成逐日完整证据，因此接口对空月份一律返回 NULL 计数并标注覆盖状态：`WITH_DATA` / `NO_RECORDS_COVERAGE_UNCONFIRMED`（月份被某成功批次声明范围覆盖，但未确认逐日完整）/ `OUTSIDE_DECLARED_RANGES`（无任何成功批次声明覆盖，可视为来源未覆盖）。覆盖判定只读取含 CRASHES 文件的 SUCCEEDED 批次。前端以断点绘制空月份并在表格标注，不画成 0。不得硬编码"2025 年完整"。

小时分布按 `crash_time` 本地报告时间提取 0—23 小时，缺失时间单列 `unknown_time_collision_count`，不并入 0 点、不做时区换算。

### 3. 接口与权限

沿用 `/api/v1` 前缀与 `{data,meta}` 结构；`meta.data_revision` 来自同一 REPEATABLE READ READ ONLY 快照（复用 `database_session` 的 GET 事务），单次响应的聚合与版本一致。统一统计报表 CSV 在单事务内一次生成各节，天然同版本；前端检测到多接口 revision 不一致时提示重新查询，不静默拼合。

权限：基础事故统计（overview/boroughs/trends/factors/vehicle-types）与事故列表 CSV 允许启用的 ADMIN/MANAGER/VIEWER；人员细分统计与统一统计报表 CSV（含人员节）按"人员详细分析"权限限 ADMIN/MANAGER；治理统计限 ADMIN/MANAGER；VIEWER 直接请求返回 403，不依赖前端按钮隐藏。治理统计的业务筛选独立于事故筛选（status/assignee_id/created_from/created_to），日期使用工单创建时间（UTC，左闭右开），恒排除软删除，"已完成"依据状态 COMPLETED，未分配执行人单列，总数不连接历史记录重复累计。

### 4. CSV 导出

- `GET /exports/collisions.csv`：与 `/collisions` 同一筛选实现，稳定排序 `(crash_date, collision_id)` 升序；数据行上限 5,000，查询取 5,001 行判定，超限返回 400 `EXPORT_ROW_LIMIT` 要求缩小范围，不静默截断，不提供也不声称存在 CLI 大数据导出。
- `GET /exports/statistics.csv`：统一统计报表（总览/行政区/月度/小时/原因/车型/人员各节），ADMIN/MANAGER。
- UTF-8 BOM + CRLF；`#` 说明行（不计入数据行数）记录生成时间、revision、排他统计区间、筛选摘要、口径与缺失/重叠说明；NULL 导出为空字段不导出为 0；数值与日期列保持原格式不做整列文本化。
- 公式注入防护：文本列跳过前导空白与控制字符（ASCII ≤ 0x20）后命中 `=`、`+`、`-`、`@` 时前置单引号；仅防护文本列，不改动数值/日期列。

### 5. 前端与打印

`StatisticsPanel.vue` + `src/api/m6.ts`：日期（结束日含当天，提交换算次日排他上界）、行政区、街道、车型、原因筛选；请求序号防竞态（旧响应丢弃）；失败清空旧结果并提示；revision 不一致提示重查。ECharts（既有锁定依赖）绘制行政区柱状、月度折线（空月断点）、小时分布（未知组异色）、原因 Top 10 条形（图表旁提供完整表格，不裁剪信息）；车型/人员/治理用表格；组间重叠以文字说明，不绘制互斥占比图。图表 resize 与 afterprint 恢复、卸载 dispose。

打印使用 `@media print`：隐藏登录、筛选按钮、地图等无关面板，仅保留统计面板；保留标题、统计区间、revision、计数单位、缺失与重叠说明、课程模拟标记；`break-inside: avoid` 防止图表块被分页切割；表格作为可读打印内容；不新增服务端 PDF 生成。

### 6. 数据库结构

无新增表、列、视图或迁移。现有索引（`ix_collision_date_id`、`ix_vehicle_type_collision`、`ix_factor_collision`、`ix_person_collision` 等）与 `v_collision_base` 已满足 M6 查询；开发库仅做只读升级核对（0007 不变）。

## 修正轮（fix1，2026-10-01）补充决定

独立验收发现 F01—F07 后，按最小改动修正：

1. **行政区选项映射**：数据库种子按字母序固定 1=BRONX、2=BROOKLYN、3=MANHATTAN、4=QUEENS、5=STATEN ISLAND（0002 迁移种子+CHECK约束）。前端选项由错误的"1=曼哈顿"改为与种子一致的中英对照；不新增 borough 字典接口，不为展示名引入可配置字典。
2. **已应用筛选（applied）状态机**：组件区分"正在编辑的表单"与"已展示报表"。仅当一次查询成功且各接口 revision 一致时更新 applied；下载参数、打印摘要一律取自 applied。日期无效时提示且不动已展示报表；加载中、查询失败、revision 不一致时打印与导出按钮停用（失败时清空 applied，revision 不一致时数据仍渲染但明确标注非单一版本）。浏览器 blur→change 先于 click 的标准行为使"编辑后直接点下载"会先应用编辑——摘要与下载参数始终一致，不存在半途状态。登录失效、退出或换账户时组件卸载并清理数据与待完成请求。CSV 由后端实际快照生成，前端解析其说明行 revision，与页面版本不同时明确提示要求重新查询，不声称跨请求同快照。
3. **打印标题与条件摘要**：新增 `.print-header`（打印可见、屏幕隐藏），含标题、排他统计区间、行政区/街道/车型/原因的已应用值、revision、计数单位、缺失/重叠说明、治理独立说明与课程模拟标记。
4. **默认日期范围**：结束日为"含当天"语义，默认 2025-01-01 至 2025-12-31，提交即 [2025-01-01, 2026-01-01)；修正了把 2026-01-02 当边界的断言。
5. **月份上限统一与日期上界安全**：新增 `month_span`（按年月差计算，不逐月构造）供月度趋势与统计 CSV 的月度节共用 120 个月上限校验（超出 422）；`month_sequence` 在 9999-12 安全终止，`month_end_bound` 为 9999-12 返回该月末，临近日期上界不再 500。
6. **纯空白街道**：共享筛选入口对 street 去空白后为空视为无条件，街道字段全 NULL 的事故与无条件同集合；列表、统计、CSV、摘要一致；`%`、`_`、`\` 保持字面匹配。
7. **月度缺失列**：月度响应、前端表格与统计 CSV 月度节补充 `injured_missing_count / killed_missing_count`，说明每月已知伤亡合计的完整程度。
8. **统计报表 CSV 行数政策**：报表为聚合结果（组数受字典大小约束），不设事故 CSV 的 5000 行数据上限；说明行明确声明，事故列表导出上限不变。
9. **无车型/原因筛选时的口径文字**：`collision_scope` 按实际筛选生成"符合当前筛选条件的事故及其全部明细"，不再恒称"涉及所选车型"。

修正验证见[M6记录](../milestones/M6.md)修正轮一节与 [evidence/M6/fix1](../evidence/M6/fix1/)。

## 后果与边界

- 明细"先选事故、再统计全部明细"的口径已在页面与 CSV 中文字说明；使用者不能把 `vehicle_records` 误读为"仅该车型车辆数"（车型分组表中另给出分组维度记录数）。
- 声明范围不当作逐月完整证据，月度补零在获得逐日覆盖证据前不会引入；P1 若引入更强覆盖证据，可扩展 coverage 状态。
- 统一报表 CSV 含人员节因此对 VIEWER 403；如需 VIEWER 可导出的精简报表，需另立不含人员节的入口（未实现）。
- 构建产物包含 ECharts 全量引入（chunk 体积警告），属既有依赖的观察项，未更换依赖版本。
