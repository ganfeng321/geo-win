<#
.SYNOPSIS
    注册 Windows 定时任务: 每日自动启动服务 + 跑本机 CI 门禁
.DESCRIPTION
    创建任务 GEO-DailyCI:
      - 每日 09:00 触发(当前用户登录时运行, 无需密码)
      - 运行 start_and_ci.ps1 (启动三端+整合层+跑 ci_check + 生成 ci_report.txt)
    服务已在跑时脚本会跳过启动, 仅跑门禁, 故每天重复运行安全幂等。
    用法: powershell -ExecutionPolicy Bypass -File install_ci_task.ps1
#>

$ErrorActionPreference = "Stop"
$root  = $PSScriptRoot
$ps1   = Join-Path $root "start_and_ci.ps1"
$task  = "GEO-DailyCI"

# 删除同名旧任务(若存在)
try { Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue } catch {}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$ps1`""

$trigger = New-ScheduledTaskTrigger -Daily -At "09:00"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1

Register-ScheduledTask `
    -TaskName $task `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "GEO 每日自动启动服务并跑本机 CI 门禁" `
    -Force

Write-Host "`n>>> 已注册任务详情:"
Get-ScheduledTask -TaskName $task | Format-List TaskName, State, Description
