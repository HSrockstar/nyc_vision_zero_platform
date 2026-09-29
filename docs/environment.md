# 环境与依赖核对（M0基线与M1入口）

首次核对：2026-09-28；数据库补验及M1基础入口：2026-09-29，Windows 11 / amd64。下文§1—5保留M0历史基线；当时未建立应用工程、业务表或导入正式数据。M1当前状态见§6。首次命令输出见 [environment-commands.json](evidence/M0/environment-commands.json)，补验见 [M0 数据库记录](milestones/M0-database.md)。

## 1. 本机基础条件

| 项目 | 实际结果 | 影响 |
|---|---|---|
| 系统 | Windows 11 家庭版，10.0.26200 | 提供 PowerShell 路径与 UTF-8 用法 |
| CPU / 内存 | Ryzen 7 7840H，8 核 / 16 线程；约 15.19 GiB 可见内存 | 性能数字仍需 M7 实测 |
| E 盘剩余 | 首次探测约 213.42 GiB | 全量原文件、暂存、索引、快照与备份容量尚未测量 |
| 默认 Python | `E:\miniconda\python.exe`，3.9.1 | 不用于本项目，不修改全局 PATH 或 Conda 环境 |
| 目标 Python | `py -3.12`，3.12.4，`D:\python软件\python.exe` | 已在 `.m0-work/python-env` 创建隔离环境 |
| pip | 全局 3.12 的 pip 26.1.1；新 venv 自带 pip 24.0 | 实际验证使用 venv 的 24.0 |
| Node / npm | 24.14.1 / 11.11.0 | 实测固定这一组合，不安装新全局运行时 |
| Docker / Compose | CLI/Engine 29.7.2；Desktop 4.90.0；Compose 5.5.1 | 9月28日引擎未运行；9月29日用户启动后实测 linux/amd64、containerd 镜像存储可用 |
| PostgreSQL 客户端 | Windows PATH 中未发现 `psql` / `pg_config` | 已用本项目容器内 psql 和 Windows psycopg 完成真实 SQL 验证 |
| Git | 可执行，但目录无 `.git` | 无 HEAD、远端或差异基线；用原文件 SHA-256 验证保留 |

初始登录 shell 出现 `Invoke-Expression: 参数列表中缺少参数。`，后续命令使用 `login:false` 排除 profile 包装影响。该提示与 Git 明确的“非仓库”错误分开记录。

## 2. PostgreSQL/PostGIS：已实测并锁定

官方 [docker-postgis](https://github.com/postgis/docker-postgis) 提供 PostgreSQL 17 与 PostGIS 3.5 / 3.6 组合，17 系列数据卷路径是 `/var/lib/postgresql/data`。当前 [PostgreSQL 版本策略页](https://www.postgresql.org/support/versioning/) 列出的 17 系列补丁版本为 **17.11**，并建议使用当前补丁版。

**实测基线：PostgreSQL 17.11 + PostGIS 3.6.4，linux/amd64。** 官方镜像索引、平台 manifest、config 和全部镜像层均校验 SHA-256；容器 SQL 返回 `server_version_num=170011`、`postgis_lib_version=3.6.4`。锁文件见 [database-image.lock.json](../validation/m0/database-image.lock.json)。

| 锁定对象 | SHA-256 |
|---|---|
| `postgis/postgis:17-3.6-alpine` OCI index | `a8ffa9afeea4ad6eada171fa2afdb57cd3eb90f92ce20156aa2cb8411d70e0cd` |
| linux/amd64 manifest / 本机 containerd 镜像 ID | `7ce143dbc804dc08a8f1dcf9067724f9b6e4ded48711e9d884487967acb442b3` |
| config | `4a4879b11890effb1e19fd924b96b174ada07dbf69ad0ad4fd003845148a425a` |

远端引用为 `postgis/postgis:17-3.6-alpine@sha256:a8ffa9afeea4ad6eada171fa2afdb57cd3eb90f92ce20156aa2cb8411d70e0cd`，同时指定 linux/amd64。本次使用官方 OCI 归档导入；本机 containerd 镜像 ID 是平台 manifest 摘要，不能把 config 摘要当成本机 ID。启动脚本按锁文件的本机不可变 ID 运行，未伪造 RepoDigest。

数据库资源为 `vision-zero-m0-postgis` / `vision-zero-m0-postgis-data` / `vision_zero_m0`，仅绑定 `127.0.0.1:55432`，上限 1 GiB / 2 CPU，restart=no。随机密码保存在被忽略的 `.m0-work/` 中；验证只创建会话临时表。主键、唯一、外键、CHECK、NOT NULL、空间 SRID 错误输入均被拒绝；事务回滚和 SQLAlchemy/GeoAlchemy2 真实往返通过。两点距离 **84.45430624 米**，100米内为真、50米内为假。见 [Windows SQL 结果](evidence/M0/database-20260929/database-smoke-windows.json)。

实际可读取的旧镜像证据如下：

| 项目 | Registry 实际结果 |
|---|---|
| 标签 | `postgis/postgis:17-3.5` |
| OCI index digest | `sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6` |
| linux/amd64 manifest | `sha256:8dfee83d8bd4c2873dc4a233c13ba2799a44f2edb16a0552d58715917fac32ba` |
| config 中 PostgreSQL | `17.5-1.pgdg110+1` |
| config 中 PostGIS | `3.5.2+dfsg-1.pgdg110+1` |
| 本机拉取 / 容器 / SQL | 均未执行 |

旧镜像证明 PG17/PostGIS3 可组合，但 **17.5 镜像仅作为探测证据，不作为 M1 交付推荐**。仅锁 `17-3.5` 标签不能锁住补丁版本，甚至不能假定其中已经更新到 17.11。[镜像记录](evidence/M0/postgis-image-baseline.json)

9月28日对 `17-3.5-alpine`、`17-3.6-alpine` 的 Registry 请求及一次有限重试发生 `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`，见 [首次记录](evidence/M0/postgis-alternatives.json) 和 [重试记录](evidence/M0/postgis-alternatives-retry.json)。9月29日原生 docker pull 和经代理访问 registry-1.docker.io 仍失败，错误保留在 [补验诊断](evidence/M0/database-20260929/diagnostics.json)。

用户提供 HTTP 代理 `127.0.0.1:7890` 后，官方 `registry.hub.docker.com` 端点可访问，匿名公开拉取认证正常。通过 [下载脚本](../validation/m0/fetch_official_image.py) 取得并校验官方对象，生成本地 OCI 归档再 docker load；TLS 校验一直开启，没有绕过访问控制、使用第三方镜像或修改 Docker 全局代理/重启引擎。原生 docker pull 的网络问题仍未解决，但本机已具备经过校验的环境。离线迁移应携带校验归档及锁文件，不能用同名浮动标签替换。

## 3. Python：已安装并锁定的组合

| 依赖 | 固定版本 |
|---|---|
| FastAPI / Uvicorn | 0.141.1 / 0.54.0 |
| SQLAlchemy / psycopg[binary] | 2.0.54 / 3.3.6 |
| Alembic / GeoAlchemy2 | 1.20.0 / 0.20.0 |
| Pydantic / pydantic-settings | 2.13.5 / 2.13.1 |
| PyJWT / pwdlib[argon2] | 2.10.1 / 0.3.0 |
| python-multipart | 0.0.22 |
| pytest / httpx | 9.1.1 / 0.28.1 |
| Starlette（传递依赖） | 1.7.0 |

输入见 [requirements.in](../validation/m0/requirements.in)；全部直接、传递版本及此次分发文件 SHA-256 见 [Windows 锁](../validation/m0/requirements-win-py312.lock) 和 [Linux 锁](../validation/m0/requirements-linux-py312.lock)。使用 `pip --require-hashes` 重放。两个锁分别用于 Windows amd64 和 Linux amd64/glibc / CPython 3.12.4，不能用 Windows 轮子哈希替代 Linux 轮子。

Windows 哈希锁已执行 `pip install --dry-run --ignore-installed --require-hashes`，退出码0，重新解析的40个分发文件通过哈希检查；这是下载/解析重放检查，没有再次建立干净环境安装。[哈希重放日志](evidence/M0/pip-lock-replay.log)

PyPI 官方发行元数据的 Python 与依赖要求已核对，安装实际使用机器既有的清华 PyPI 镜像配置，没有修改全局源。下载 URL、环境、分发文件哈希见 [pip-install-report.json](evidence/M0/pip-install-report.json)。未来更换源也须匹配锁中哈希。

验证结果：隔离安装成功；`pip check` 返回 `No broken requirements found`；[python_smoke.py](../validation/m0/python_smoke.py) 的 FastAPI TestClient、Argon2、JWT 往返和 PostgreSQL 空间表达式编译通过，psycopg 使用 binary 实现。[结果](evidence/M0/python-smoke.json)

最初安装因 pip 按 CP936 读取 UTF-8 中文注释而报 `UnicodeDecodeError`，加入 `-X utf8` 后成功。保留 [首次日志](evidence/M0/pip-install.log) 与 [成功日志](evidence/M0/pip-install-utf8.log)。TestClient 仍有 httpx 弃用提示，见 [原始冒烟日志](evidence/M0/python-smoke.log)；目前功能通过，M1 可评估测试客户端更新，不掩盖提示。

9月29日在官方 `python:3.12.4-slim-bookworm`（Debian glibc 2.36 / amd64）实际安装同版本直接依赖，以 Windows 传递版本作约束，解析出38个 Linux 分发文件。差异为 Windows 专用 colorama/tzdata 无需安装，以及平台轮子哈希不同。随后在第二个干净 venv 中以 Linux 哈希锁实际安装、pip check，并完成11项真实数据库验证。[Linux 结果](evidence/M0/database-20260929/linux-python/result.json) / [SQL 结果](evidence/M0/database-20260929/linux-python/database-smoke-linux.json) / [哈希重放日志](evidence/M0/database-20260929/linux-python/pip-hash-replay-linux.log)。Linux 安装使用官方 PyPI，未改全局源。

Python 镜像远端锁为 `python:3.12.4-slim-bookworm@sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85`，平台 manifest 为 `sha256:a074fac67aa01841fee592d00bae14d25dcaf98ef6e12a683ecceb7e0147e2d1`；镜像及所有层同样校验后导入。[镜像证据](evidence/M0/database-20260929/linux-python/image-verified.json)。Linux 锁只验 glibc 容器，不宣称适用于 Alpine/musl。Python 3.12.4 是复用本机的兼容验证版本，M1 应独立评估升级到当时受维护的3.12补丁版并重验，不能把旧运行时补丁当作安全验收。

9月28日基础冒烟仅验证包组合；9月29日补充了真实 PostgreSQL 连接、基础约束与事务验证。业务迁移、数据库角色权限、鉴权与备份恢复仍属于后续阶段。

## 4. 前端：已严格安装、类型检查及构建

| 依赖 | 固定版本 |
|---|---|
| Vue / Vue Router / Pinia | 3.5.43 / 4.6.4 / 3.0.4 |
| Element Plus / ECharts / Leaflet | 2.14.6 / 5.6.0 / 1.9.4 |
| TypeScript / vue-tsc | 5.9.3 / 3.3.11 |
| Vite / @vitejs/plugin-vue | 7.3.6 / 6.0.9 |
| Vitest / @vue/test-utils | 4.1.11 / 2.4.6 |
| @playwright/test / @types/leaflet | 1.63.0 / 1.9.20 |

Vite 7 要求 Node `^20.19.0 || >=22.12.0`，[官方说明](https://vite.dev/blog/announcing-vite7)；本机 Node24 满足。npm 注册表的 Router、Pinia、Element Plus 和 plugin-vue peer 也覆盖此 Vue/Vite 组合。最终以严格安装结果为依据。

所有直接版本无 `^` / `~`，`package-lock.json` 锁住传递依赖和 integrity，重放用 `npm ci --engine-strict`。[验证工程](../validation/m0/frontend/package.json) / [锁文件](../validation/m0/frontend/package-lock.json)

初选 `@vue/test-utils@2.5.1` 引入 `js-beautify@2.0.3 -> nopt@10.0.1`，后者要求 Node `^22.22.2 || ^24.15.0 || >=26.0.0`，导致 `EBADENGINE`。核对注册表后只将测试工具固定为 2.4.6，其 `js-beautify@1.x -> nopt@7.x` 支持现有 Node。没有用 `--force` 或关闭 engine 检查。[原错误](evidence/M0/npm-install.log) / [依赖路径](evidence/M0/npm-install-debug.log)

后续安装发生一次 `ECONNRESET`，有限重试成功，保留 [网络错误](evidence/M0/npm-install-compatible.log) / [成功日志](evidence/M0/npm-install-retry.log)。安装仍有 `glob@10.5.0` 上游弃用警告；M1 应评估兼容更新，当前不宣称安全审计通过。

实际通过：严格安装、锁文件重放、TypeScript 模块类型检查、Vite 库构建。构建编译了 Vue/Router/Pinia/Element Plus/ECharts/Leaflet 的验证入口，共 2173 个模块，耗时 28.04 秒。这不是业务前端的性能数据。[类型检查](evidence/M0/frontend-typecheck.log) / [构建](evidence/M0/frontend-build.log) / [锁重放](evidence/M0/npm-ci.log)

未运行 Vitest 业务测试、Playwright 浏览器用例，未下载浏览器内核。依赖存在不等于这些测试已通过。

## 5. 后续锁定与升级规则

M1 复用验证输入建立 `backend/` 和 `frontend/`，移植经验证的精确版本与真实锁文件。Linux Python 哈希、数据库镜像 digest 和实际 SQL 版本已形成新的环境验收记录；业务迁移与权限仍需另验。Compose 不使用浮动 `latest`；运行时使用明确 Python/Node 补丁版。

升级须单独修改版本输入、重建锁、运行受影响检查并更新 ADR。数据库补丁升级也保留迁移版本和备份/回滚步骤。M0历史数据库入口位于 validation/m0，仅服务于环境验证；当前M1入口见§6。

## 6. M1最小工程：已实测

本轮复用固定版本，未升级运行时或包。新`.venv`从Windows哈希锁安装40包，pip check通过；frontend严格npm ci安装170包，类型检查与页面构建通过。backend两个平台锁与M0逐字节一致，frontend包解析和integrity保留。当前Windows开发脚本已验证；未新增Linux应用启动验收。

| 入口 | 地址或作用 |
|---|---|
| 开发数据库 | `vision-zero-dev-db` / `vision-zero-dev-postgis-data` / `vision_zero_dev`，`127.0.0.1:55433` |
| 后端 | `127.0.0.1:8000`；`/health/live`和`/health/ready` |
| 前端 | `127.0.0.1:5173`；同源代理健康检查 |
| 迁移 | `0001_environment`，只确认PostGIS并记录版本，无业务表 |
| worker | Windows连接预检后退出，没有业务任务 |

脚本拒绝冲突的继承环境变量、他属资源、错误挂载和配置；Python连接与根目录`.env`批准目标比对，随机测试库须显式启用。迁移用事务内`search_path=public`防止官方镜像tiger/topology扩展表被自动差异误判，alembic check已通过。M0库和卷保留。

当前管理账号仅用于本机环境迁移和健康检查。角色分离、鉴权、正式数据导入、Python补丁升级、完整响应式/业务浏览器验收均未完成。已知TestClient httpx和glob弃用提示保留，没有关闭检查。启动见[README](../README.md)，实际命令/失败/证据见[M1记录](milestones/M1.md)。
