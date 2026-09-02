# 统一启动脚本(本地自用)
# 启动:监控端后端(3002) + 前端(3001) + 发布端(5409)
# 用法: powershell -ExecutionPolicy Bypass -File start_all.ps1

$root = $PSScriptRoot
$monitor = Join-Path $root "packages\geo-monitor"
$publisher = Join-Path $root "packages\geo-publisher"

function Start-Background($name, $path, $exe, $args) {
    Write-Host "▶ 启动 $name ..."
    Start-Process -NoNewWindow -FilePath $exe -ArgumentList $args -WorkingDirectory $path `
        -RedirectStandardOutput "$path\$name.out.log" -RedirectStandardError "$path\$name.err.log"
}

# 1. 监控端后端
Start-Background "monitor-backend" "$monitor\backend" "node" "app.js"

# 2. 监控端前端
Start-Background "monitor-frontend" "$monitor\nextjs-frontend" "node" "node_modules/next/dist/bin/next dev -p 3001"

# 3. 发布端
$env:PYTHONPATH = "$publisher\sau_backend"
Start-Background "publisher" "$publisher\sau_backend" "$publisher\venv\Scripts\python.exe" "sau_backend.py"

Write-Host "✅ 已启动。访问: 前端 http://localhost:3001 | 发布端 http://localhost:5409"
Start-Sleep -Seconds 4
try { (Invoke-WebRequest -Uri "http://localhost:3002/api/health" -TimeoutSec 4 -UseBasicParsing).Content | Write-Host }
catch { Write-Host "monitor-backend 尚未就绪,稍后检查" }
