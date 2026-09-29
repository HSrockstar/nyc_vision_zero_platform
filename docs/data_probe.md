# M0 NYC 碰撞数据探测

探测日期：2026-09-28；各 HTTP 请求 UTC 起止时间、完整 URL、状态、错误、响应文件名及 SHA-256 保存在各目录的 `requests.json`。使用标准公开 HTTPS 接口，无私有凭据，未绕过访问控制。结果是本轮访问时的快照，不表示此后的固定规模。

## 1. 入口与证据

| 来源 | 官方页面 / ID | 元数据 | 样本及范围查询 |
|---|---|---|---|
| Crashes | [h9gi-nx95](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95) | `/api/views/h9gi-nx95.json`，200 | `/resource/h9gi-nx95.json`，200 |
| Person | [f55k-p6yu](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Person/f55k-p6yu) | `/api/views/f55k-p6yu.json`，200 | `/resource/f55k-p6yu.json`，200 |
| Vehicles | [bm4k-52h4](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Vehicles/bm4k-52h4) | `/api/views/bm4k-52h4.json`，200 | `/resource/bm4k-52h4.json`，200 |

主机均为 `https://data.cityofnewyork.us`。元数据与 10 行限定样本见 [主探测目录](evidence/M0/data-probe-20260928/requests.json)，独立边界查询见 [日期目录](evidence/M0/date-bounds-20260928/requests.json)，键检查和 CSV 两行小样见 [质量目录](evidence/M0/quality-20260928/requests.json)。字段清单分别保存在 `*-fields.json`，完整原始元数据为 `*-metadata.response.txt`。

探测脚本 [m0_probe_data.py](../scripts/m0_probe_data.py) 设置单次 20 秒超时和响应大小上限，不执行全量下载或正式导入。样本只选择关联与必要字段，不读取年龄、性别等额外个人明细。原始证据保持本地，未来公开前检查。

## 2. 数量、日期与固定开发范围

| 来源 | 当前全表 count(*) | 最小事故日期 | 最大事故日期 | 2025 年 1 月行数 | 2025 全年行数 |
|---|---:|---|---|---:|---:|
| Crashes | 2,269,187 | 2012-07-01 | 2026-06-11 | 6,482 | 85,546 |
| Person | 5,984,110 | 2012-07-01 | 2026-06-11 | 22,165 | 292,070 |
| Vehicles | 4,551,002 | 2012-07-01 | 2026-06-11 | 12,830 | 170,015 |

日期边界通过 `crash_date IS NOT NULL`、日期升/降序、`$limit=1` 独立取得；计数通过 `count(*)`。全表“计数+最小最大日期+键去重”合并查询超时，未从失败结果填数。三类请求是独立读取，不能宣称跨表一致快照。

月份区间为 `[2025-01-01, 2025-02-01)`，年度为 `[2025-01-01, 2026-01-01)`。网页更新时间不等于事件截止日期；当前事件最大日期只到 2026-06-11，不能写“数据更新到本轮当天”。最小/最大日期与行数不证明中间覆盖完整，特别是旧年份的明细粒度仍需首次导入核验。

保留计划的首个真实开发范围：**2025 年 1 月按 `(crash_date, collision_id)` 稳定排序取前 500 起事故，并按其事故 ID 补齐所有人员、车辆明细**；这是后续 M2 导入目标，本轮仅取 10 起父样本，不称为 500 起已下载。业务开发再扩大到 2025 全年，只有完整获取与 manifest 核对后才称为年度完整集。性能按需要扩展到 2024—2025，本轮未下载。

## 3. 主键与关联契约

| 原字段 | 官方类型 | 正式目标 | 实测与约定 |
|---|---|---|---|
| Crashes `collision_id` | number | `collision.collision_id BIGINT` | 当前 Crashes 没有 `unique_id` 字段 |
| Person `unique_id` | number | `person.person_id BIGINT` | 人员记录键 |
| Person `person_id` | text | `person.source_person_id TEXT` | 源业务代码；不能当作已核验的人员身份 |
| Vehicles `unique_id` | number | `vehicle.vehicle_id BIGINT` | 车辆记录键 |
| Vehicles `vehicle_id` | text | `vehicle.source_vehicle_id TEXT` | 源车辆代码，保留文本 |
| 两个子表 `collision_id` | number | FK 到 `collision.collision_id` | 按父事故关联 |
| Person `vehicle_id` | text | `person.source_vehicle_id TEXT` | P0 原样保留，不设直接车辆 FK |

元数据对子表 `collision_id` 的文字说明仍写匹配 Crash 的 `unique_id`，与实际父表字段不一致。以当前父表 `collision_id` 字段和真实样本关联为依据，不创建不存在的父表 `unique_id` 映射。

2025 年内的 API 聚合结果：

| 来源 | count(*) | 记录键 count | 记录键 count(distinct) | collision_id count |
|---|---:|---:|---:|---:|
| Crashes | 85,546 | 85,546 | 85,546 | 85,546 |
| Person | 292,070 | 292,070 | 292,070 | 292,070 |
| Vehicles | 170,015 | 170,015 | 170,015 | 170,015 |

所选年度键缺失与重复均为 0。**全表主键质量尚未完成**：对应复杂全表聚合超时；年度结果不能外推到全历史。实际 CSV 仍须逐行检查整数、范围、缺失和重复内容冲突。

10 起父事故样本均来自 2025-01-01 的稳定排序结果，不是随机样本：

| 检查 | Person | Vehicles |
|---|---:|---:|
| 按父 ID 获取的子记录 | 40 | 20 |
| 有子记录的父事故 | 10/10 | 10/10 |
| 子记录键缺失 / 重复 | 0 / 0 | 0 / 0 |
| 子日期与父日期冲突 | 0 | 0 |
| `unique_id` 等于源 person_id / vehicle_id | 0/40 | 0/20 |

子查询上限 1000，实际未触及；因此这 10 起事故的返回没有上限截断证据。其他 10 行独立子样本的键也没有缺失/重复。[父子摘要](evidence/M0/data-probe-20260928/person-link-summary.json)、[车辆摘要](evidence/M0/data-probe-20260928/vehicles-link-summary.json)、[附加检查](evidence/M0/sample-quality-summary.json)

进一步发现：40 条人员中 39 条有 `vehicle_id`，在同一事故内 **39/39 匹配车辆 `unique_id` 的文本表示，0/39 匹配车辆源 `vehicle_id`**。这证明不能仅因列同名就连接 Person.vehicle_id 与 Vehicles.vehicle_id。该小样本不足以宣布全表外键成立；P0 继续按事故分别展示，P1 若增加直接连接，需检查全范围缺失、重复、事故一致性和数值解析，并保存验证证据。

## 4. 完整字段清单与重要类型差异

以下是元数据 fieldName，语义应同时对照 display name / description，不能单凭名字猜测。

```text
Crashes (29):
crash_date, crash_time, borough, zip_code, latitude, longitude, location,
on_street_name, off_street_name, cross_street_name,
number_of_persons_injured, number_of_persons_killed,
number_of_pedestrians_injured, number_of_pedestrians_killed,
number_of_cyclist_injured, number_of_cyclist_killed,
number_of_motorist_injured, number_of_motorist_killed,
contributing_factor_vehicle_1 ... contributing_factor_vehicle_5,
collision_id, vehicle_type_code1, vehicle_type_code2,
vehicle_type_code_3, vehicle_type_code_4, vehicle_type_code_5

Person (21):
unique_id, collision_id, crash_date, crash_time, person_id, person_type,
person_injury, vehicle_id, person_age, ejection, emotional_status,
bodily_injury, position_in_vehicle, safety_equipment, ped_location,
ped_action, complaint, ped_role, contributing_factor_1,
contributing_factor_2, person_sex

Vehicles (25):
unique_id, collision_id, crash_date, crash_time, vehicle_id,
state_registration, vehicle_type, vehicle_make, vehicle_model,
vehicle_year, travel_direction, vehicle_occupants, driver_sex,
driver_license_status, driver_license_jurisdiction, pre_crash,
point_of_impact, vehicle_damage, vehicle_damage_1, vehicle_damage_2,
vehicle_damage_3, public_property_damage, public_property_damage_type,
contributing_factor_1, contributing_factor_2
```

`crash_date` 为 calendar_date / floating timestamp，`crash_time` 为文本，`vehicle_year` 也为文本。日期使用纽约当地 DATE，时间解析为 TIME/NULL；不推断精确 UTC。人员类别元数据包含 Bicyclist / Motor Vehicle Occupant / Pedestrian；本轮没有完整枚举审计，不能由 person_type 猜驾驶员/乘客。车型字段 1、2 与 3—5 的下划线模式不同，必须显式映射。原因槽位不是车辆记录键。

## 5. 地点缺失与街道字段冲突

2025 全年 latitude/longitude 各有 84,618 条非空，**任一坐标缺失的联合条件查询为 928 条（约 1.08%）**。2025 年 1 月两列各有 6,403 条非空；本轮未对月份查询缺失联合条件，不能仅凭各列计数认定相同缺失集合。非空坐标不等于有效：零值、反转、越界、研究范围异常和几何匹配质量仍待逐行导入核验。

当前元数据与样本存在必须显式处理的语义：

| API fieldName | 官方 display name / description | M0 建议语义 |
|---|---|---|
| `on_street_name` | ON STREET NAME / 事发街道 | 观察地点主街道 |
| `off_street_name` | CROSS STREET NAME / 最近横街 | 交叉街道来源 |
| `cross_street_name` | OFF STREET NAME / 已知街道地址 | 门牌地址来源 |

样本 `cross_street_name` 出现带门牌号地址；另取 `off_street_name` 的 5 条样本得到 WHITESTONE EXPRESSWAY / 20 AVENUE 等街道对。[街道证据](evidence/M0/street-check-20260928/requests.json)。后一个 5 行样本未限定年度，仅用于字段语义，不计入 2025 统计。2025 年 on/off/cross 非空分别为 59,201 / 50,870 / 26,344；尚未统计两街道同时有效的交集，不能当作可生成候选的数量。

**调整提案：**规范化地点表的 `cross_street_name` 取“横街语义”，通过有版本的输入映射连接当前 API `off_street_name`；规范化 `off_street_name` 取门牌语义，连接当前 API `cross_street_name`。CSV 按实际表头和本次元数据另建显式映射，不对所有来源无条件互换。原始字段、显示名、响应哈希和完整源值始终保留。该重大映射在 M1 数据字典中列明，M2 导入前须完成契约确认；本轮没有改计划或实现清洗。

只纳入确认交叉口及有效归属。50 米是课程默认参数，尚无准确率证据；道路高架、同名街道、多个候选、地址字段和未知行政区都不能强行最近匹配。缺失坐标事故保留在列表与总体统计。

## 6. 失败与限制

- 三次全表复杂聚合：`TimeoutError: The read operation timed out`，响应体为空，见主目录 `requests.json`；随后改用独立日期边界和 count 查询成功，并保留两类证据。
- 年度街道样本的“off_street_name 非空 + collision_id 排序”查询同样超时，见质量目录；后续使用不带排序的 5 行语义样本成功。不能从超时推断字段不存在。
- 本轮数据入口没有遇到 403/429；不编造访问拒绝。将来遇到 403 停止该入口、保留状态与正文，检查官方接口/令牌/网络；429 按 Retry-After 有限退避；5xx/超时有限重试，不轮换身份绕过限制。
- API 日期、计数和质量统计不是数据库导入结果。全量父子覆盖、年龄/车型完整枚举、伤亡字段缺失比例、零坐标及完整文件大小均未验证。

## 7. 官方 CSV 离线入口与导入契约

已经用 `/resource/<id>.csv` 查询取得每类 **2 行**必要字段小样，返回 200。样本是受限 API CSV，不等于下载官方完整年度文件，也不替代全列 CSV 表头核验。

网络故障时，使用上表官方 NYC Open Data 页面，确认 Dataset ID，按需要设置日期筛选，再用网页 Export/Download 选择 CSV。也可使用官方完整导出路径 `/api/views/<id>/rows.csv?accessType=DOWNLOAD`；该完整路径本轮未下载、未确认可用状态。禁止在看见错误 HTML 时按扩展名把它当 CSV。

离线操作约定：

1. 三份来源文件分别存入 `data/raw/<batch>/`，保留下载时间、官方 URL、Dataset ID、原文件名、字节数、编码、实际表头和 SHA-256；本轮没有创建这些完整原文件。
2. 若网页无法可靠按年完整导出，可下载官方完整 CSV 后本地按固定日期筛选，原文件仍保留。年度不是简单取前 N 行；筛选表达式、导出方式、总行数和完整性结论写入 manifest。
3. 明确 CSV 是 display-name 还是 API-field-name 表头。Socrata [CSV 格式说明](https://dev.socrata.com/docs/formats/csv.html) 要求按规范处理引号、逗号、嵌入换行和空值。禁止按每个换行符计记录，禁止用 Excel 改写主键精度或类型。
4. 标识符先按文本读取，严格检查来源数字键后转 BIGINT；文本业务代码仍为 TEXT。必需列缺失/主键冲突阻断发布，异常和原始行保留。
5. 先选定父事故集合，再按 collision_id 筛选全部子记录。子表范围、原始日期及父日期冲突分别报告；找不到父记录时暂存隔离，不关闭 FK，不伪造父事故。
6. 每个来源记录实际行数、最小最大日期、目标范围、范围外行、键缺失/重复、内容冲突、父子覆盖及是否截断。无法证明完整时标记 incomplete；文件最小最大日期不能作为唯一完整性证明。
7. 清洗、暂存、预览和原子发布属于 M2。本轮只确认方案，未执行 `COPY`、UPSERT、批次发布或数据库写入。

## 8. M1/M2 必须继续核验

街道语义映射是最优先的数据契约修正。随后以正式 CSV 和真实数据库核验全量键、父子缺失、坐标质量及评分六类必需伤亡字段。风险事故计数/伤亡以 Crashes 一事故一行口径为准，人员明细不足不等于零伤亡；不要通过车辆/原因的多对多 JOIN 放大汇总。
