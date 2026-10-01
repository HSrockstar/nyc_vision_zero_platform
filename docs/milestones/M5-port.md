# M5 环境修复：开发数据库端口迁移

日期：2026-09-30。用户明确授权将项目固定开发端口由 55433 改为 15433。

## 原因与实际检查

既有 `scripts/dev.ps1 -Action DatabaseStart` 退出 1，Docker 报告原端口绑定被访问权限拒绝。`Get-NetTCPConnection` 没有发现 55433 的监听进程；Python 直接绑定 `127.0.0.1:55433` 得到 WinError 10013。

`netsh interface ipv4 show excludedportrange protocol=tcp` 和 IPv6 同项检查均包含动态区间 55356—55455，覆盖 55433。该区间无管理员保留 `*`，持久保留列表为空。本机动态 TCP 范围仍为 49152—65535，HNS、WinNAT、虚拟机计算和 WSL 服务正在运行，docker-desktop 为 WSL2 运行实例。

这些事实支持“虚拟网络动态保留区间”的判断，但没有确认具体创建者。读取 HNS 详情被当前 Windows 权限拒绝，WinNAT 操作日志未启用；本轮未提权修改日志或重启系统网络服务。15433 在当时保留区间之外，Python 本机绑定测试成功。

## 变更与回退边界

操作前核对了既有容器的工作区标签、锁定镜像、loopback 端口、环境身份与 `vision-zero-dev-postgis-data` 卷归属。将 `.env` 与 `.m1-work/model/vision_zero_dev-provision.env` 原字节备份到 `.m1-work/model/m5-port-55433-backup`，再同步端口及 app/migrator/worker 三个连接地址；凭据和库名未变。

用户授权后执行：

```powershell
docker compose --project-directory 'E:\数据库课设' --env-file 'E:\数据库课设\.env' -f 'E:\数据库课设\compose.yaml' up -d --wait --wait-timeout 60 db
```

退出 0，专用容器按相同镜像和原卷重建并 Healthy。未删除卷或数据库，没有停止其他项目容器。`.env.example`、Compose 默认值、bootstrap、Settings 默认值及当前入口文档已同步；历史验收证据保留原端口。

要回退时先确认原端口不再被 Windows 保留，停止本项目服务，将上述两份配置恢复为备份并按相同镜像/原卷重建；本轮没有执行回退。原保留区间仍存在时回退会再次启动失败。

## 迁移后核验

维护连接的容器身份校验通过。迁移后仍为 `0006_risk_worker`、revision 98，85,546 起事故、292,070 条人员、170,015 条车辆、95 条画像；run 1 为 SUCCEEDED，工单与历史均为 0，与 M4 记录一致。这里是迁移后的实际计数核对，未声称建立了独立的逐行迁移前数据库快照。

证据：[迁移聚合记录](../evidence/M5/port-migration.json)。配置备份含凭据，只存放于 Git 忽略目录，不纳入公开交付。

依据：[微软动态端口说明](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/tcp-ip-port-exhaustion-troubleshooting)、[netsh 区间命令](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netsh-interface)。
