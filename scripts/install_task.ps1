[CmdletBinding()]
param(
    [string]$TaskName = "Private Daily Newsletter",
    [string]$DailyAt = "06:30"
)

$ErrorActionPreference = "Stop"
$runScript = Join-Path $PSScriptRoot "run_daily.ps1"
$time = [DateTime]::ParseExact($DailyAt, "HH:mm", $null)
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description "Generate the private daily news brief" -Force | Out-Null
Write-Host "Scheduled task '$TaskName' installed for $DailyAt each day."
