# 开发入口前台运行后端/前端；Ctrl+C结束该终端中的进程。
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('DatabaseStart','DatabaseStop','Status','Migrate','MigrationStatus','Backend','Frontend','Worker','Check')]
    [string]$Action,
    [ValidateRange(1024,65535)][int]$Port = 0
)
. (Join-Path $PSScriptRoot 'common.ps1')
$config = Get-LocalConfig

if ($Action -in @('DatabaseStart','DatabaseStop','Status')) {
    $exists = Assert-DatabaseResources -Config $config
    switch ($Action) {
        'DatabaseStart' {
            if (-not $exists) { Assert-PortFree -Port ([int]$config.VISION_ZERO_DB_PORT) }
            Invoke-DatabaseCompose -ComposeArguments @('config','--quiet')
            Invoke-DatabaseCompose -ComposeArguments @('up','-d','--wait','--wait-timeout','60','db')
        }
        'DatabaseStop' { if ($exists) { Invoke-DatabaseCompose -ComposeArguments @('stop','db') } }
        'Status' { Invoke-DatabaseCompose -ComposeArguments @('ps','-a') }
    }
    exit 0
}
if (-not (Test-Path -LiteralPath $script:PythonPath)) { throw '请先运行scripts/bootstrap.ps1建立.venv。' }
if ($Action -in @('Migrate','MigrationStatus')) {
    if (-not (Assert-DatabaseResources -Config $config -RequireRunning)) { throw '开发数据库尚未创建，请先运行DatabaseStart。' }
}
if ($Action -eq 'Frontend') {
    if ($Port -eq 0) { $Port = 5173 }
    Assert-PortFree -Port $Port
    Push-Location (Join-Path $script:ProjectRoot 'frontend')
    try { Invoke-Checked -Tool 'npm.cmd' -Arguments @('run','dev','--','--port',"$Port") }
    finally { Pop-Location }
    exit 0
}
Push-Location (Join-Path $script:ProjectRoot 'backend')
try {
    switch ($Action) {
        'Backend' {
            if ($Port -eq 0) { $Port = 8000 }
            Assert-PortFree -Port $Port
            Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$Port")
        }
        'Migrate' { Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','alembic','-c','alembic.ini','upgrade','head') }
        'MigrationStatus' { Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','alembic','-c','alembic.ini','current') }
        'Worker' { Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','app.worker') }
        'Check' {
            Invoke-Checked -Tool $script:PythonPath -Arguments @('-X','utf8','-m','pytest','-q')
            Push-Location (Join-Path $script:ProjectRoot 'frontend')
            try {
                Invoke-Checked -Tool 'npm.cmd' -Arguments @('run','check')
                Invoke-Checked -Tool 'npm.cmd' -Arguments @('run','build')
            } finally { Pop-Location }
        }
    }
} finally { Pop-Location }
