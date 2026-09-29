# M1字段映射契约

版本 `nyc-api-v1`，2026-09-29。依据是M0已取得的三源元数据和样本，见 [数据探测](data_probe.md)。机器可读入口为 [field_mapping_v1.json](../configs/field_mapping_v1.json)；本阶段只定义契约，清洗及正式导入在M2实现。

| 来源字段 | 正式字段 / 语义 | 处理 |
|---|---|---|
| Crashes.collision_id | collision.collision_id | BIGINT来源主键，不自增 |
| Person.unique_id | person.person_id | BIGINT人员记录键；不等于现实人员身份 |
| Person.person_id | person.source_person_id | TEXT原始业务代码，不设唯一约束 |
| Person.vehicle_id | person.source_vehicle_id | TEXT保留；P0不建立车辆直接外键 |
| Vehicles.unique_id | vehicle.vehicle_id | BIGINT车辆记录键 |
| Vehicles.vehicle_id | vehicle.source_vehicle_id | TEXT保留，不替代unique_id |
| 子表collision_id | 正式collision外键 | 无父行必须暂存隔离，不伪造事故 |
| API on_street_name | location.on_street_name | 主街道 |
| API off_street_name（显示CROSS STREET NAME） | location.cross_street_name | 横街 |
| API cross_street_name（显示OFF STREET NAME） | location.off_street_name | 门牌/街道外地址，不用于配对路口 |
| 原始longitude、latitude | location.geom | WGS84 Point，经度在前；正式表只保存这一坐标真值 |
| contributing_factor_vehicle_1…5 | collision_factor.factor_order | 原因槽位1—5，不是Vehicles主键 |
| vehicle_type_code1/2/_3/_4/_5 | raw_record.payload | 保留事故层槽位；正式车型分析采用Vehicles记录 |

CSV适配器须确认表头是API fieldName还是display-name；分别记录实际表头、文件SHA-256、Dataset ID、映射版本和行号。不能对所有CSV无条件交换两个街道字段。完整源字段清单及类型差异保留于数据探测报告§4。

事故日期/时间采用纽约当地 `DATE/TIME`，不推断精确UTC。缺少时间不补零点。系统操作时刻使用UTC `TIMESTAMPTZ`。全部BIGINT API ID使用字符串。

计数 `NULL` 与 `0` 分开；全部伤亡缺失也必须生成casualty_stat行。persons_injured、persons_killed、pedestrians_injured、pedestrians_killed、cyclists_injured、cyclists_killed为六项评分必需字段；不以人员明细代替Crashes汇总，不强制子类别和等于总数。

年龄0—120、车辆年份1886—2100是可见的课程质量检查规则。M2遇到越界或解析失败须保存原值、设正式值NULL并记录数据问题。它们不代表官方有效值范围。空间类型与世界经纬度范围由数据库约束；异常零坐标、研究区异常及候选路口准确性仍属M2/M3核验。

location.key_input保存地点摘要输入，location_key由M2稳定生成；全未知地点输入加入collision_id，防止错误合并。摘要相同还须比较输入，不能把哈希当作内容一致的数学保证。原文件与原始payload保留，不将来源修订覆盖到旧payload。
