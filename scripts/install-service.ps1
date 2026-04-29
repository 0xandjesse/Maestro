param()

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\transport-service.mjs"
$logPath = Join-Path $repoRoot ".maestro\transport-service.log"
$taskName = "MaestroTransportService"

$logDir = Split-Path $logPath
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$nodePath = (Get-Command node -ErrorAction Stop).Source
Write-Host "Node: $nodePath"
Write-Host "Script: $scriptPath"
Write-Host "Log: $logPath"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed existing task"
}

$cmdArgs = '/c "' + $nodePath + '" "' + $scriptPath + '" >> "' + $logPath + '" 2>&1'
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Maestro Protocol transport service"

Write-Host "Task registered: $taskName"
Write-Host "Starting now..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
$info = Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo
Write-Host "Last run result: $($info.LastTaskResult)"
