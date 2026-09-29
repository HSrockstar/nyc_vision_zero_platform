# M1字段契约与M2 CSV清洗

版本 `nyc-api-v1`，2026-09-29。依据是官方元数据和实际CSV，见 [数据探测](data_probe.md)。机器可读入口为 [field_mapping_v1.json](../configs/field_mapping_v1.json)；M2清洗版本`nyc-clean-v1`、CSV表头版本[nyc-csv-v1](../configs/csv_headers_v1.json)，支持明确API/display模式及唯一匹配auto，不补猜混合表头。

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

M2具体规则：来源ID按ASCII正整数字符串解析到BIGINT，拒绝小数/科学计数/溢出；日期接受ISO当地日期或显示格式MM/DD/YYYY，时间错误置NULL记录问题。文本字典/街道去首尾空白、合并内部空格并大写；空值为NULL，未映射列原样保留raw。坐标必须成对、有限、世界范围内且非零，否则置NULL；纽约粗研究框外仅警告，不伪称行政区边界验证。

同源键不同payload阻断整个批次；完全重复源行跳过。无父的人员/车辆行隔离，不伪造事故；父事故日期为正式范围依据，子行日期不同保留并记录问题。伤亡异常值置NULL而非补0，五个原因列缺表头时整批拒绝；来源变更按完整槽位替换，旧raw和旧观察地点不改写。人员与车辆来源业务代码仍为TEXT，无直接外键。
