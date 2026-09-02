<#
.SYNOPSIS
    一键启动全部服务 + 跑本机 CI 等价检查
.DESCRIPTION
    启动: 监控端后端(3002) + 前端(3001) + 发布端(5409) + 整合层看板(7000)
    然后等待服务就绪, 跑 ci_check.ps1 (= run_all.py --skip-real), 生成 ci_report.txt
    用法: powershell -ExecutionPolicy Bypass -File start_and_ci.ps1
#>

$ErrorActionPreference = "Continue"
$root      = $PSScriptRoot
$monitor   = Join-Path $root "packages\geo-monitor"
$publisher = Join-Path $root "packages\geo-publisher"
$core      = Join-Path $root "apps\geo-core"

function Start-Background($name, $path, $exe, $argList) {
    Write-Host "▶ 启动 $name ..."
    Start-Process -NoNewWindow -FilePath $exe -ArgumentList $argList -WorkingDirectory $path `
        -RedirectStandardOutput "$path\$name.out.log" -RedirectStandardError "$path\$name.err.log"
}

function Start-If-Free($name, $port, $path, $exe, $argList) {
    try {
        $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
        if ($r.TcpTestSucceeded) {
            Write-Host "  ⊘ $name ($port) 已在运行, 跳过启动(避免多实例冲突)"
            return
        }
    } catch {}
    Start-Background $name $path $exe $argList
}

function Wait-Port($port, $svc, $timeout = 60) {
    $t = 0
    while ($t -lt $timeout) {
        try {
            $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
            if ($r.TcpTestSucceeded) { Write-Host "  ✓ $svc ($port) 就绪"; return $true }
        } catch {}
        Start-Sleep -Seconds 2; $t += 2
    }
    Write-Host "  ✗ $svc ($port) 在 ${timeout}s 内未就绪, CI 可能失败"
    return $false
}

# 1. 监控端后端
Start-If-Free "monitor-backend" 3002 "$monitor\backend" "node" "app.js"
# 2. 监控端前端
Start-If-Free "monitor-frontend" 3001 "$monitor\nextjs-frontend" "node" "node_modules/next/dist/bin/next dev -p 3001"
# 3. 发布端(单实例, 必须跳过已占用)
$env:PYTHONPATH = "$publisher\sau_backend"
Start-If-Free "publisher" 5409 "$publisher\sau_backend" "$publisher\venv\Scripts\python.exe" "sau_backend.py"
# 4. 整合层看板
Start-If-Free "geo-core" 7000 "$core" "$core\venv\Scripts\python.exe" "dashboard_api.py"

Write-Host "`n等待服务启动..."
Wait-Port 3002 "监控端后端"
Wait-Port 3001 "监控端前端"
Wait-Port 5409 "发布端"
Wait-Port 7000 "整合层看板"

Write-Host "`n========================================================"
Write-Host " 开始本机 CI 等价检查 (run_all.py --skip-real)"
Write-Host "========================================================"

# 检查 LLM Key(F14/F17 需要)
if (-not $env:AGNES_API_KEY) {
    Write-Host "⚠ 注意: 环境变量 AGNES_API_KEY 未设置, F14/F17 可能失败。如需设置请先: `$env:AGNES_API_KEY='你的Key'"
} else {
    Write-Host "✓ AGNES_API_KEY 已设置"
}

# 等待更稳一点再跑 CI
Start-Sleep -Seconds 3

# 运行 CI 等价脚本(内部已含退出码透传)
& "$root\ci_check.ps1"
$ciExit = $LASTEXITCODE

Write-Host "`n========================================================"
if ($ciExit -eq 0) {
    Write-Host " 本机 CI: PASS ✓ (详见 ci_report.txt)"
} else {
    Write-Host " 本机 CI: FAIL ✗ (exit=$ciExit, 详见 ci_report.txt)"
}
Write-Host "========================================================"

exit $ciExit
