# M0 数据库环境补验记录

日期：2026-09-29。用户已启动 Docker Desktop，并提供本机 HTTP 代理端口7890。只补齐M0的数据库与Linux依赖验证；未开始业务工程、23表迁移、认证、数据导入或工单实现。

## 实测结果

| 检查 | 结果 / 证据 |
|---|---|
| Docker | Engine29.7.2、Desktop4.90.0、Compose5.5.1，linux/amd64，containerd镜像存储可用 |
| PostgreSQL / PostGIS | 真实SQL：17.11 / 3.6.4，server_version_num=170011 |
| 官方镜像完整性 | OCI index、amd64 manifest、config和全部层的SHA-256及字节数通过；[下载记录](../evidence/M0/database-20260929/image-download.json) / [归档记录](../evidence/M0/database-20260929/image-verified.json) |
| Windows数据库客户端 | 已锁定的psycopg3.3.6、SQLAlchemy2.0.54、GeoAlchemy2 0.20.0，11项检查通过；[SQL结果](../evidence/M0/database-20260929/database-smoke-windows.json) |
| Linux依赖 | 官方Python3.12.4 slim-bookworm，glibc2.36/amd64，38包实际安装、pip check、基础调用通过；[结果](../evidence/M0/database-20260929/linux-python/result.json) |
| Linux哈希重放 | 第二个干净venv实际按--require-hashes安装成功，再次pip check及11项真实SQL通过；[安装日志](../evidence/M0/database-20260929/linux-python/pip-hash-replay-linux.log) / [SQL结果](../evidence/M0/database-20260929/linux-python/database-smoke-linux.json) |
| 持久卷复启 | 原有本项目容器重新启动，日志显示Skipping initialization，版本/扩展保留，永久M0表为0；[结果](../evidence/M0/database-20260929/volume-reopen.json) |
| 独立只读复核 | test_verifier再次核对版本、镜像/端口/卷、无非扩展业务关系和空间SQL；[记录](../evidence/M0/database-20260929/independent-verification.json) |
| 复启后的Windows连接 | 经127.0.0.1:55432实际psycopg连接及版本查询通过；[记录](../evidence/M0/database-20260929/windows-connection-after-reopen.json) |

11项检查覆盖：主键/唯一键拒绝重复（23505）、外键拒绝缺父（23503）、CHECK非负（23514）、NOT NULL（23502）、错误SRID拒绝（22023）、4326及经纬顺序、geography米制距离、失败事务整体回滚、SQLAlchemy/GeoAlchemy2空间往返及SQLAlchemy显式回滚。点为经度-73.9857、纬度40.7484；东移0.001度后距离84.45430624米，ST_DWithin(100)为真、ST_DWithin(50)为假。仅创建会话临时表，连接关闭后消失。

镜像初始化默认启用了postgis、postgis_topology、postgis_tiger_geocoder，均3.6.4，并含各扩展自带对象。这些是镜像默认内容，不计为项目业务表；M1只按实际需求使用扩展，不宣称已实现拓扑或地理编码业务。

## 版本锁与本机资源

数据库完整远端引用：

```text
postgis/postgis:17-3.6-alpine@sha256:a8ffa9afeea4ad6eada171fa2afdb57cd3eb90f92ce20156aa2cb8411d70e0cd
platform: linux/amd64
```

平台manifest和本机containerd镜像ID：`sha256:7ce143dbc804dc08a8f1dcf9067724f9b6e4ded48711e9d884487967acb442b3`。config摘要：`sha256:4a4879b11890effb1e19fd924b96b174ada07dbf69ad0ad4fd003845148a425a`。本机按不可变镜像ID启动；OCI归档导入未提供远端RepoDigest，因此分别记录来源index、平台manifest和本机ID，未伪造锁定结果。见 [数据库锁](../../validation/m0/database-image.lock.json)。

Python远端index：`python:3.12.4-slim-bookworm@sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85`；本机平台manifest：`sha256:a074fac67aa01841fee592d00bae14d25dcaf98ef6e12a683ecceb7e0147e2d1`。见 [Python镜像锁](../../validation/m0/python-image.lock.json) 和 [Linux依赖锁](../../validation/m0/requirements-linux-py312.lock)。Windows40包与Linux38包版本一致，colorama/tzdata是Windows额外依赖；平台轮子哈希分别记录。Linux锁只验glibc，不能当作Alpine/musl锁。

| 本机资源 | 配置 |
|---|---|
| 数据库容器 | vision-zero-m0-postgis，scope标签m0-verification；1GiB、2CPU、restart=no |
| 数据卷 | vision-zero-m0-postgis-data，挂载/var/lib/postgresql/data，保留 |
| 数据库 / 端口 | vision_zero_m0 / 127.0.0.1:55432 → 5432 |
| Linux验证容器 | vision-zero-m0-python；512MiB、2CPU；完成后退出0，保留容器和记录 |
| 凭据 | .m0-work/m0-db.env、m0-db-credentials.json；48字节加密随机源生成，不输出、不提交 |
| 镜像归档 | .m0-work/postgis-17-3.6-amd64.oci.tar（189388800字节）、python-3.12.4-amd64.oci.tar（48916480字节），保留SHA记录 |

验证以专用库的postgres管理账号运行，不等同应用最小权限验收。后续迁移/应用/worker账号、PUBLIC权限与函数权限须在M1另做。

验证结束后两个M0容器均已停止，镜像、卷和归档均保留，可由database.ps1再次启动。最终资源状态见 [resource-final.json](../evidence/M0/database-20260929/resource-final.json)。原有14个其他项目容器标识和状态前后相同，未新增非M0容器。没有停止、重启或删除其他项目资源。

## 实际命令与失败

| 实际动作/命令 | 结果 |
|---|---|
| docker version / docker compose version / docker info安全字段 | 引擎可用；没有打印完整配置或环境变量 |
| docker pull postgis/postgis:17-3.6-alpine | 1，registry-1.docker.io的manifest HEAD返回EOF；[原错误](../evidence/M0/database-20260929/postgis-pull.log) |
| curl.exe --proxy http://127.0.0.1:7890 -I --max-time20 https://registry-1.docker.io/v2/ | CONNECT200后Schannel握手失败，35 |
| urllib经代理GET官方auth/registry-1 | 根端点401（匿名拉取需token）；auth200；manifest SSL EOF，见[记录](../evidence/M0/database-20260929/proxy-python-probe.json) |
| urllib经代理GET官方registry.hub.docker.com/v2/与manifest | 根端点401及官方Bearer挑战，取得匿名token后manifest200；SHA与官方Hub标签元数据一致 |
| py -3.12 -X utf8 validation/m0/fetch_official_image.py … | PostGIS/Python各对象哈希和字节数通过，生成OCI归档；不关闭TLS，不使用第三方镜像 |
| docker load --input .m0-work/postgis-17-3.6-amd64.oci.tar | 0，Loaded image；初按config ID或未规范化名称inspect失败，改按实证的平台manifest ID成功 |
| docker load --input .m0-work/python-3.12.4-amd64.oci.tar | 0，Loaded image |
| & validation/m0/database.ps1 -Action Start | 0，创建专用有标签卷/容器，随机凭据、localhost端口；后续再次Start复用现有容器/卷 |
| .m0-work/python-env/Scripts/python.exe -X utf8 validation/m0/database_smoke.py --credentials .m0-work/m0-db-credentials.json --output docs/evidence/M0/database-20260929/database-smoke-windows.json | 0，11项检查通过 |
| docker run（下方完整命令） | Linux容器退出码0；真实安装与第二环境哈希重放、11项SQL通过；中断后依据容器退出状态和完整结果文件确认完成，未把终端会话丢失当作失败或成功日志 |
| docker exec … psql只读复启查询；docker logs过滤初始化记录 | 0，版本与扩展持久化，M0永久表0 |
| & validation/m0/database.ps1 -Action Stop | 0，验证完成后停止本项目容器，保留卷和镜像 |

首次Python镜像auth请求还有一次TLS握手超时，有限重试成功；上述失败及OCI导入名称/ID差异保存在 [诊断记录](../evidence/M0/database-20260929/diagnostics.json)。后续下载脚本使用完整docker.io名称注解。本次直接pull的网络问题未修复，使用了官方替代端点；不把失败改写为成功，也未修改Docker全局代理或重启Docker引擎。

独立复核使用只读SQL，没有重新创建TEMP表：它动态验证版本/空间查询/对象归属，并审阅已有两平台的11项记录及实现。它的两条关系盘点诊断SQL曾因内部char拼接及跨语句CTE引用失败，修正后成功；这属于诊断语句错误，不是数据库故障，记录中已区分。PowerShell profile包装提示也与实际退出码分别记录。

镜像下载实际命令：

```powershell
py -3.12 -X utf8 validation/m0/fetch_official_image.py --repository postgis/postgis --tag 17-3.6-alpine --index-digest sha256:a8ffa9afeea4ad6eada171fa2afdb57cd3eb90f92ce20156aa2cb8411d70e0cd --proxy http://127.0.0.1:7890 --archive .m0-work/postgis-17-3.6-amd64.oci.tar --evidence docs/evidence/M0/database-20260929
py -3.12 -X utf8 validation/m0/fetch_official_image.py --repository library/python --tag 3.12.4-slim-bookworm --index-digest sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85 --proxy http://127.0.0.1:7890 --archive .m0-work/python-3.12.4-amd64.oci.tar --evidence docs/evidence/M0/database-20260929/linux-python
```

Linux验证实际命令（工作目录E:\数据库课设）：

```powershell
docker run --name vision-zero-m0-python --label vision-zero.scope=m0-verification --platform linux/amd64 --network container:vision-zero-m0-postgis --memory 512m --cpus 2 --mount 'type=bind,source=E:\数据库课设\validation\m0,target=/validation,readonly' --mount 'type=bind,source=E:\数据库课设\docs\evidence\M0\database-20260929\linux-python,target=/evidence' --mount 'type=bind,source=E:\数据库课设\.m0-work\m0-db-credentials.json,target=/run/m0/credentials.json,readonly' sha256:a074fac67aa01841fee592d00bae14d25dcaf98ef6e12a683ecceb7e0147e2d1 python -u /validation/linux_smoke.py
```

这是执行记录，已有同名容器时不要原样重复创建。需要重验时保留已有证据，使用新的容器名和证据目录；主库可由database.ps1启动。跨机器应先核对OCI归档SHA、导入并查实际镜像ID；本机ID为containerd平台manifest，其他镜像存储可能使用config ID，不能静默套用。原文件、大层缓存、卷均未删除。

## 当前限制与M1范围

原生Registry端点的EOF仍存在，但校验归档和本机镜像可用。Python3.12.4只作为兼容验证基线，M1评估3.12补丁更新后重验。httpx弃用提示仍保留，浏览器内核/业务测试、完整年度数据、权限和业务迁移未通过本次验证。

交付检查：五份原文件SHA-256不变，14个其他项目容器状态不变；官方归档SHA再次核对、Linux锁与实际分发报告一致、43个JSON解析及文档链接通过，凭据未出现在交付目录；Python语法与PowerShell解析通过。`git status --short --branch`仍返回128（无.git），所以git diff --check不适用，未初始化Git。见 [最终检查](../evidence/M0/database-20260929/artifact-final-check.json)。README/environment/ADR和阶段清单均已更新为补验后的状态，9月28日失败记录保留。

上述原文件哈希检查发生在资料归并之前。其后按用户要求将三份旧材料归并到 [前期资料摘要](../references/prior_work_summary.md)，删除原文件并更新计划1.1；原环境证据与数据库资源保留。本记录不将授权资料整理视为原文件异常丢失。

随后按用户授权将秋季指南归并为 [课程要求S1](../references/course_requirements.md)，校验备份并删除原PDF，计划更新1.2；本次仅更新资料及引用，未重新操作数据库或改变验证结果。

M1范围：复用环境建立最小backend/frontend/Compose、完成23表迁移和约束、迁移/应用/worker数据库角色、三类用户认证、健康检查、E-R/数据字典/3NF及真实权限失败路径验收。街道字段映射、UNKNOWN建单、在办任务角色变更、幂等摘要需先明确契约。导入、风险与工单完整流程分别留M2/M4/M5；本轮不继续实现。
