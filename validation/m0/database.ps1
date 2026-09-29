# M0 数据库验证容器管理入口；不会停止、删除或修改其他项目资源。
param(
    [Parameter(Mandatory=$true)][ValidateSet('Start','Stop','Status')][string]$Action
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$lockPath = Join-Path $PSScriptRoot 'database-image.lock.json'
if (-not (Test-Path -LiteralPath $lockPath)) { throw '数据库镜像锁尚未生成，请先完成镜像版本核对。' }
$config = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$containerName = 'vision-zero-m0-postgis'
$volumeName = 'vision-zero-m0-postgis-data'
if ($Action -eq 'Status') {
    docker ps -a --filter "name=^/$containerName$" --format '{{.Names}} | {{.Status}} | {{.Ports}}'
    exit $LASTEXITCODE
}
$existing = docker ps -aq --filter "name=^/$containerName$"
if ($existing) {
    $label = docker inspect --format '{{index .Config.Labels "vision-zero.scope"}}' $containerName
    if ($label -ne 'm0-verification') { throw '同名容器不属于本项目M0，停止操作。' }
    if ($Action -eq 'Stop') { docker stop $containerName; exit $LASTEXITCODE }
    $imageId = docker inspect --format '{{.Image}}' $containerName
    if ($imageId -ne $config.local_image_id) { throw '已有M0容器镜像与锁文件不一致，停止操作。' }
    docker start $containerName
    exit $LASTEXITCODE
}
if ($Action -eq 'Stop') { Write-Output 'M0容器尚不存在。'; exit 0 }
$envPath = Join-Path $projectRoot '.m0-work\m0-db.env'
$credentialsPath = Join-Path $projectRoot '.m0-work\m0-db-credentials.json'
if ((Test-Path -LiteralPath $envPath) -xor (Test-Path -LiteralPath $credentialsPath)) {
    throw '本地凭据文件不完整，请核对已有文件；不会覆盖已有密码。'
}
if (-not (Test-Path -LiteralPath $envPath)) {
    New-Item -ItemType Directory -Path (Split-Path $envPath) -Force | Out-Null
    $randomBytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($randomBytes)
    $rng.Dispose()
    $password = [Convert]::ToBase64String($randomBytes)
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($envPath, "POSTGRES_USER=postgres`nPOSTGRES_DB=vision_zero_m0`nPOSTGRES_PASSWORD=$password`n", $utf8)
    $credentials = @{host='127.0.0.1';port=55432;database='vision_zero_m0';user='postgres';password=$password}
    [IO.File]::WriteAllText($credentialsPath, ($credentials | ConvertTo-Json), $utf8)
}
$listener = Get-NetTCPConnection -LocalPort 55432 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw '55432端口已占用，停止操作；不会改动已有服务。' }
$existingVolume = docker volume ls -q --filter "name=^$volumeName$"
if ($existingVolume) {
    $label = docker volume inspect --format '{{index .Labels "vision-zero.scope"}}' $volumeName
    if ($label -ne 'm0-verification') { throw '同名数据卷不属于本项目M0，停止操作。' }
} else {
    docker volume create --label 'vision-zero.scope=m0-verification' $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '创建M0数据卷失败。' }
}
docker run -d --name $containerName --label 'vision-zero.scope=m0-verification' --platform linux/amd64 `
    --env-file $envPath --publish '127.0.0.1:55432:5432' --mount "type=volume,source=$volumeName,target=/var/lib/postgresql/data" `
    --health-cmd 'pg_isready -U postgres -d vision_zero_m0' --health-interval 5s --health-timeout 3s --health-retries 12 `
    --restart no --memory 1g --cpus 2 $config.local_image_id
exit $LASTEXITCODE
