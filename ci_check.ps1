<#
.SYNOPSIS
    GEO 整合层 本机 CI 等价检查脚本
.DESCRIPTION
    等价于 GitHub Actions 回归流水线：代码提交后自动跑一遍验收脚本，证明无回归。
    因云端 CI（GitHub Actions 被 billing 锁定 / Gitee Go 个人免费仓库不支持）暂不可用，
    此脚本在本机提供同等门禁效果。

    用法：
        powershell -ExecutionPolicy Bypass -File ci_check.ps1
    或在项目根目录双击运行。
#>

$ErrorActionPreference = "Stop"

$ROOT    = Split-Path -Parent $MyInvocation.MyCommand.Path
$CORE    = Join-Path $ROOT "apps\geo-core"
$REPORT  = Join-Path $ROOT "ci_report.txt"
$PY      = $null

# 1) 定位 Python 解释器（优先 venv，回退系统 python）
$venvPy = Join-Path $CORE "venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $PY = $venvPy
} else {
    $sysPy = (Get-Command python -ErrorAction SilentlyContinue)
    if ($sysPy) { $PY = $sysPy.Source } else { $PY = "python" }
}

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$head = @"
========================================================
 GEO 整合层 本机 CI 等价检查
 时间: $ts
 解释器: $PY
 等价云端流水线: .github/workflows/regression.yml (GitHub Actions)
                  （注：GitHub 账号被 billing 锁定，暂未运行云端版）
========================================================
"@

Write-Host $head
Set-Location $CORE

# 2) 运行验收回归（跳过真实发布 F7/F10）
$argsList = @("run_all.py", "--skip-real")
Write-Host ">>> 执行: $PY $($argsList -join ' ')"
Write-Host "--------------------------------------------------------"

try {
    & $PY @argsList
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "执行异常: $_"
    $exitCode = 2
}

Write-Host "--------------------------------------------------------"

if ($exitCode -eq 0) {
    $result = "PASS  ✓  所有验收用例通过，无回归"
} else {
    $result = "FAIL  ✗  验收未通过 (exit=$exitCode)"
}

$foot = @"

结果: $result
报告生成时间: $ts
"@

Write-Host $foot

# 3) 落盘报告
($head + "`n" + $foot) | Out-File -FilePath $REPORT -Encoding utf8

# 4) 退出码透传给调用方（与 CI 一致：0=绿, 非0=红）
exit $exitCode
