# Windows开发脚本的共同边界：精确工作区、原生退出码、资源归属。
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:PythonPath = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
$script:Lock = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'validation\m0\database-image.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json

function Invoke-Checked {
    param([string]$Tool, [string[]]$Arguments)
    & $Tool @Arguments
    if ($LASTEXITCODE -ne 0) { throw "命令 $Tool 失败，退出码 $LASTEXITCODE。" }
}

function Get-WorkspaceId {
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($script:ProjectRoot.ToLowerInvariant()))
        return 'vision-zero-' + ([BitConverter]::ToString($digest).Replace('-','').ToLowerInvariant().Substring(0,16))
    } finally { $hasher.Dispose() }
}

function Get-LocalConfig {
    $path = Join-Path $script:ProjectRoot '.env'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw '请先运行 scripts/bootstrap.ps1。' }
    $values = @{}
    foreach ($line in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ($line -match '^\s*(#|$)') { continue }
        $parts = $line.Split('=',2)
        if ($parts.Count -ne 2) { throw '.env中存在无效行。' }
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    if ($values.VISION_ZERO_WORKSPACE_ID -ne (Get-WorkspaceId)) { throw '.env不属于当前工作区，不会覆盖或操作其资源。' }
    if ($values.VISION_ZERO_DB_IMAGE -ne $script:Lock.local_image_id) { throw '本地数据库镜像必须与M0锁定ID一致。' }
    if ($values.VISION_ZERO_DATABASE_NAME -ne 'vision_zero_dev') { throw '开发入口只允许vision_zero_dev，不操作其他库。' }
    $port = 0
    if (-not [int]::TryParse($values.VISION_ZERO_DB_PORT,[ref]$port) -or $port -lt 1024 -or $port -gt 65535) { throw '本地数据库端口无效。' }
    if (-not $values.POSTGRES_PASSWORD -or $values.POSTGRES_PASSWORD.Length -lt 32) { throw '本地随机数据库凭据缺失或过短。' }
    foreach ($key in $values.Keys) {
        $inherited = [Environment]::GetEnvironmentVariable($key, 'Process')
        if ($null -ne $inherited -and $inherited -cne $values[$key]) {
            throw "进程环境变量 $key 与工作区.env冲突，停止操作；请在当前终端清除该变量。"
        }
    }
    return $values
}

function Assert-PortFree {
    param([int]$Port)
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $Port 已占用；不会停止已有服务或自动换端口。"
    }
}

function Assert-DatabaseResources {
    param([hashtable]$Config, [switch]$RequireRunning)
    foreach ($key in @('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')) {
        if ([Environment]::GetEnvironmentVariable($key, 'Process')) { throw "Docker进程变量 $key 可改变目标引擎，请先在当前终端清除。" }
    }
    $contextName = & docker context show
    if ($LASTEXITCODE -ne 0) { throw '无法核对Docker上下文。' }
    $endpoint = & docker context inspect --format '{{.Endpoints.docker.Host}}' $contextName
    if ($LASTEXITCODE -ne 0 -or $endpoint -notin @('npipe:////./pipe/dockerDesktopLinuxEngine','npipe:////./pipe/docker_engine')) {
        throw '开发入口仅允许本机Docker Desktop命名管道引擎，不操作远程上下文。'
    }
    $engine = & docker version --format '{{.Server.Version}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Docker引擎不可用，请先启动Docker Desktop。' }
    $localImage = & docker image inspect --format '{{.Id}}' $script:Lock.local_image_id 2>$null
    if ($LASTEXITCODE -ne 0 -or $localImage -ne $script:Lock.local_image_id) { throw '缺少锁定数据库镜像；请按M0说明导入校验归档，不会自动拉取其他版本。' }
    $container = & docker ps -aq --filter 'name=^/vision-zero-dev-db$'
    if ($LASTEXITCODE -ne 0) { throw '无法检查开发容器。' }
    if ($container) {
        if ($RequireRunning) {
            $running = & docker inspect --format '{{.State.Running}}' $container
            if ($LASTEXITCODE -ne 0 -or $running -ne 'true') { throw '开发数据库容器尚未运行，请先运行DatabaseStart。' }
        }
        $labels = & docker inspect --format '{{json .Config.Labels}}' $container | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $labels.'vision-zero.scope' -ne 'development' -or $labels.'vision-zero.workspace' -ne $Config.VISION_ZERO_WORKSPACE_ID) {
            throw '同名容器不属于当前工作区，停止操作。'
        }
        $image = & docker inspect --format '{{.Image}}' $container
        if ($LASTEXITCODE -ne 0 -or $image -ne $script:Lock.local_image_id) { throw '开发容器镜像与锁文件不一致。' }
        $bindings = & docker inspect --format '{{json .HostConfig.PortBindings}}' $container | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $bindings.'5432/tcp'.Count -ne 1 -or $bindings.'5432/tcp'[0].HostIp -ne '127.0.0.1' -or $bindings.'5432/tcp'[0].HostPort -ne $Config.VISION_ZERO_DB_PORT) {
            throw '已有容器端口配置不一致，不会重建或更改。'
        }
        $mounts = & docker inspect --format '{{json .Mounts}}' $container | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $mounts.Count -ne 1 -or $mounts[0].Type -ne 'volume' -or $mounts[0].Name -ne 'vision-zero-dev-postgis-data' -or $mounts[0].Destination -ne '/var/lib/postgresql/data' -or -not $mounts[0].RW) {
            throw '已有容器的数据挂载与专用卷不一致，停止操作。'
        }
        $containerEnv = & docker inspect --format '{{json .Config.Env}}' $container | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $containerEnv -cnotcontains 'POSTGRES_USER=postgres' -or $containerEnv -cnotcontains "POSTGRES_DB=$($Config.VISION_ZERO_DATABASE_NAME)" -or $containerEnv -cnotcontains "POSTGRES_PASSWORD=$($Config.POSTGRES_PASSWORD)") {
            throw '已有容器数据库配置与工作区.env不一致，停止操作。'
        }
    }
    $volume = & docker volume ls -q --filter 'name=^vision-zero-dev-postgis-data$'
    if ($LASTEXITCODE -ne 0) { throw '无法检查开发数据卷。' }
    if ($volume) {
        $labels = & docker volume inspect --format '{{json .Labels}}' $volume | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $labels.'vision-zero.scope' -ne 'development' -or $labels.'vision-zero.workspace' -ne $Config.VISION_ZERO_WORKSPACE_ID) {
            throw '同名数据卷不属于当前工作区，停止操作。'
        }
    }
    return [bool]$container
}

function Invoke-DatabaseCompose {
    param([string[]]$ComposeArguments)
    Invoke-Checked -Tool 'docker' -Arguments (@('compose','--project-directory',$script:ProjectRoot,'--env-file',(Join-Path $script:ProjectRoot '.env'),'-f',(Join-Path $script:ProjectRoot 'compose.yaml')) + $ComposeArguments)
}
