# M7 B01—B04 数据库性能实验

状态：**完成**。

数据范围固定为 2025 年（左闭右开），每条件预热 3 次、测量 20 次，A/B 交替。
普通查询耗时包含客户端取回结果的时间；EXPLAIN ANALYZE 执行耗时单独记录。缓存未清理，因此不称为冷缓存。
结果只保存计数和 SHA-256 摘要，不保存事故、人员、车辆或账号记录。

2025 年事故数：85,546；全库事故数：85,546。

## B01

- A（无 crash_date 前导二级索引）：普通查询 median 11.489 ms、P95 16.216 ms；EXPLAIN 执行 median 10.131 ms、P95 17.980 ms；观察到索引：执行计划未显示索引扫描。
- B（crash_date、collision_id 日期复合索引）：普通查询 median 2.720 ms、P95 3.996 ms；EXPLAIN 执行 median 0.126 ms、P95 0.209 ms；观察到索引：ix_collision_date_id。
- A/B 普通查询中位数比：4.2231。这是本次环境的观测值，不外推为普遍加速结论。
- 结果一致：通过；返回行数 100，仅保存摘要哈希。

## B02

- A（location_id 单列索引；共同关闭日期索引）：普通查询 median 2.914 ms、P95 4.588 ms；EXPLAIN 执行 median 0.371 ms、P95 0.704 ms；观察到索引：m7_bench_ix_collision_location。
- B（location_id、crash_date 复合索引；共同关闭日期索引）：普通查询 median 3.128 ms、P95 4.451 ms；EXPLAIN 执行 median 0.596 ms、P95 1.058 ms；观察到索引：ix_collision_location_date。
- A/B 普通查询中位数比：0.9317。这是本次环境的观测值，不外推为普遍加速结论。
- 结果一致：通过；返回行数 137，仅保存摘要哈希。

## B03

- A（无匹配 geography GiST 索引）：普通查询 median 263.813 ms、P95 405.852 ms；EXPLAIN 执行 median 269.250 ms、P95 513.288 ms；观察到索引：ix_collision_location_date, ix_location_geom。
- B（geom::geography GiST 局部索引）：普通查询 median 4.697 ms、P95 10.510 ms；EXPLAIN 执行 median 0.523 ms、P95 0.818 ms；观察到索引：ix_collision_location_date, ix_location_geography。
- A/B 普通查询中位数比：56.1674。这是本次环境的观测值，不外推为普遍加速结论。
- 结果一致：通过；返回行数 5，仅保存摘要哈希。

## B04

- A（EXISTS）：普通查询 median 264.415 ms、P95 493.385 ms；EXPLAIN 执行 median 334.954 ms、P95 535.918 ms；观察到索引：ix_location_borough, ix_vehicle_type_collision。
- B（DISTINCT collision_id 子查询）：普通查询 median 227.835 ms、P95 374.595 ms；EXPLAIN 执行 median 335.880 ms、P95 526.897 ms；观察到索引：ix_location_borough, ix_vehicle_type_collision。
- A/B 普通查询中位数比：1.1606。这是本次环境的观测值，不外推为普遍加速结论。
- 结果一致：通过；返回行数 6，仅保存摘要哈希。

临时索引事务回滚并与初始目录核对：通过。

执行计划保存在 `plans/`，逐次耗时保存在 `timings.csv`；完整环境和数据摘要见 JSON 文件。
