param()

$scriptPath = "C:\Users\there\Projects\Maestro\concerto\serve.mjs"
$logPath    = "C:\Users\there\Projects\Maestro\concerto\concerto.log"
$taskName   = "MaestroConcertoUI"

$nodePath = (Get-Command node -ErrorAction Stop).Source
Write-Host "Node:   $nodePath"
Write-Host "Script: $scriptPath"
Write-Host "Log:    $logPath"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed existing task"
}

$cmdArgs = '/c "' + $nodePath + '" "' + $scriptPath + '" >> "' + $logPath + '" 2>&1'
$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory "C:\Users\there\Projects\Maestro\concerto"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Maestro Concerto UI server (port 3901)"

Write-Host "Task registered: $taskName"
Write-Host "Starting now..."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
$info = Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo
Write-Host "Last run result: $($info.LastTaskResult)"
