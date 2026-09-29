# 只验证脚本拒绝边界；模拟Docker输出，不创建或修改容器。
. (Join-Path $PSScriptRoot '..\..\scripts\common.ps1')
$script:TestConfig = Get-LocalConfig
$script:Passed = 0

function Assert-Rejected {
    param([scriptblock]$Operation, [string]$Name)
    $rejected = $false
    try { & $Operation | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw "拒绝边界未生效：$Name" }
    $script:Passed++
    Write-Output "PASS $Name"
}

foreach ($key in @('VISION_ZERO_DB_IMAGE','VISION_ZERO_DB_PORT','POSTGRES_PASSWORD')) {
    $previous = [Environment]::GetEnvironmentVariable($key, 'Process')
    try {
        [Environment]::SetEnvironmentVariable($key, 'conflicting-test-value', 'Process')
        Assert-Rejected -Operation { Get-LocalConfig } -Name "inherited-$key"
    } finally { [Environment]::SetEnvironmentVariable($key, $previous, 'Process') }
}

function docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    $global:LASTEXITCODE = 0
    $joined = $Arguments -join ' '
    if ($joined -eq 'context show') { return 'desktop-linux' }
    if ($joined -like 'context inspect *') {
        if ($script:Scenario -eq 'remote-engine') { return 'ssh://remote.example' }
        return 'npipe:////./pipe/dockerDesktopLinuxEngine'
    }
    if ($joined -like 'version *') { return '29.7.2' }
    if ($joined -like 'image inspect *') { return $script:Lock.local_image_id }
    if ($joined -like 'ps *') { return 'mock-project-container' }
    if ($joined -like 'volume ls *') { return 'vision-zero-dev-postgis-data' }
    if ($joined -like '*json .Config.Labels*' -or $joined -like '*json .Labels*') {
        return (@{'vision-zero.scope'='development';'vision-zero.workspace'=$script:TestConfig.VISION_ZERO_WORKSPACE_ID} | ConvertTo-Json -Compress)
    }
    if ($joined -like '*{{.Image}}*') { return $script:Lock.local_image_id }
    if ($joined -like '*{{.State.Running}}*') {
        if ($script:Scenario -eq 'stopped-container') { return 'false' }
        return 'true'
    }
    if ($joined -like '*json .HostConfig.PortBindings*') {
        return (@{'5432/tcp'=@(@{HostIp='127.0.0.1';HostPort=$script:TestConfig.VISION_ZERO_DB_PORT})} | ConvertTo-Json -Compress -Depth 4)
    }
    if ($joined -like '*json .Mounts*') {
        if ($script:Scenario -eq 'missing-mount') { return '[]' }
        $mount = @{Type='volume';Name='vision-zero-dev-postgis-data';Destination='/var/lib/postgresql/data';RW=$true}
        if ($script:Scenario -eq 'wrong-volume') { $mount.Name='unrelated-data' }
        if ($script:Scenario -eq 'bind-mount') { $mount.Type='bind' }
        return ConvertTo-Json -InputObject @($mount) -Compress
    }
    if ($joined -like '*json .Config.Env*') {
        $database = $script:TestConfig.VISION_ZERO_DATABASE_NAME
        if ($script:Scenario -eq 'wrong-database') { $database='unrelated' }
        return ConvertTo-Json -InputObject @('POSTGRES_USER=postgres',"POSTGRES_DB=$database","POSTGRES_PASSWORD=$($script:TestConfig.POSTGRES_PASSWORD)") -Compress
    }
    throw '测试模拟遇到未声明的Docker调用。'
}

$script:Scenario = 'valid'
if (-not (Assert-DatabaseResources -Config $script:TestConfig)) { throw '符合预期的模拟资源应通过。' }
$script:Passed++
Write-Output 'PASS matching-resources'
foreach ($scenario in @('wrong-volume','bind-mount','missing-mount','wrong-database','remote-engine')) {
    $script:Scenario = $scenario
    Assert-Rejected -Operation { Assert-DatabaseResources -Config $script:TestConfig } -Name $scenario
}
$script:Scenario = 'stopped-container'
Assert-Rejected -Operation { Assert-DatabaseResources -Config $script:TestConfig -RequireRunning } -Name 'migration-on-stopped-container'
$previousHost = [Environment]::GetEnvironmentVariable('DOCKER_HOST', 'Process')
try {
    [Environment]::SetEnvironmentVariable('DOCKER_HOST', 'tcp://remote.example:2376', 'Process')
    Assert-Rejected -Operation { Assert-DatabaseResources -Config $script:TestConfig } -Name 'inherited-DOCKER_HOST'
} finally { [Environment]::SetEnvironmentVariable('DOCKER_HOST', $previousHost, 'Process') }
Write-Output "Windows guard checks: $script:Passed passed; Docker calls were mocked."
