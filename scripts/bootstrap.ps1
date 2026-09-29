# 初始化只创建本项目隔离依赖与随机配置；已有文件不会被覆盖。
param()
. (Join-Path $PSScriptRoot 'common.ps1')

$version = & py -3.12 --version
if ($LASTEXITCODE -ne 0 -or $version -ne 'Python 3.12.4') { throw '当前验证基线需要py -3.12对应Python 3.12.4；升级请单独重验。' }
$nodeVersion = & node --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -ne 'v24.14.1') { throw '请使用已锁定Node24.14.1。' }
$npmVersion = & npm.cmd --version
if ($LASTEXITCODE -ne 0 -or $npmVersion -ne '11.11.0') { throw '请使用已锁定npm11.11.0。' }

$envPath = Join-Path $script:ProjectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $password = [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
    $dsn = "postgresql+psycopg://postgres:${password}@127.0.0.1:55433/vision_zero_dev"
    $lines = @(
        'VISION_ZERO_WORKSPACE_ID=' + (Get-WorkspaceId)
        'VISION_ZERO_DB_IMAGE=' + $script:Lock.local_image_id
        'VISION_ZERO_DB_PORT=55433'
        'VISION_ZERO_DATABASE_NAME=vision_zero_dev'
        'POSTGRES_PASSWORD=' + $password
        'VISION_ZERO_DATABASE_URL=' + $dsn
        'VISION_ZERO_MIGRATION_DATABASE_URL=' + $dsn
    )
    [IO.File]::WriteAllText($envPath,($lines -join "`n") + "`n",(New-Object Text.UTF8Encoding($false)))
    Write-Host '已生成被忽略的.env及随机数据库凭据。'
}
$null = Get-LocalConfig
$venvPath = Join-Path $script:ProjectRoot '.venv'
if (Test-Path -LiteralPath $venvPath) {
    $venv = Get-Item -LiteralPath $venvPath
    if ($venv.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '不使用指向工作区外的虚拟环境。' }
    if (-not (Test-Path -LiteralPath $script:PythonPath)) { throw '已有.venv不完整，不会覆盖。' }
} else {
    Invoke-Checked -Tool 'py' -Arguments @('-3.12','-X','utf8','-m','venv',$venvPath)
}
Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','pip','install','--require-hashes','-r',(Join-Path $script:ProjectRoot 'backend\requirements-win-py312.lock'))
Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','pip','check')
Push-Location (Join-Path $script:ProjectRoot 'frontend')
try { Invoke-Checked -Tool 'npm.cmd' -Arguments @('ci','--engine-strict','--no-audit','--no-fund') }
finally { Pop-Location }
Write-Host '初始化完成；下一步依次运行DatabaseStart、ProvisionRoles、Migrate、InitAdmin。'
