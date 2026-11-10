# 电商客服 Agent 一键启动脚本（Windows PowerShell）
# 用法：右键「使用 PowerShell 运行」，或在项目目录执行 .\start.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== 电商客服 Agent ===" -ForegroundColor Cyan
Write-Host "项目目录：$PSScriptRoot"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[1/3] 未发现虚拟环境，正在查找 Python 3.10+ ..." -ForegroundColor Yellow

    $candidates = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    if ($env:LOCALAPPDATA) {
        $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName }
    }
    $candidates = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

    $pythonExe = $null
    foreach ($candidate in $candidates) {
        & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $candidate
            break
        }
    }

    if (-not $pythonExe) {
        Write-Host "未找到 Python 3.10+。请先安装 Python 并勾选 Add to PATH。" -ForegroundColor Red
        Write-Host "下载地址：https://www.python.org/downloads/windows/"
        exit 1
    }

    Write-Host "使用 Python：$pythonExe"
    & $pythonExe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
}

Write-Host "[2/3] 检查依赖 ..." -ForegroundColor Yellow
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败，请检查网络后重试" }

if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") (Join-Path $PSScriptRoot ".env")
    Write-Host "已从 .env.example 生成 .env（默认无 Key，走本地演示模式）" -ForegroundColor DarkGray
}

Write-Host "[3/3] 启动服务 ..." -ForegroundColor Yellow
Write-Host "启动后浏览器访问控制台输出里的地址（默认 http://127.0.0.1:8000）"
Write-Host "按 Ctrl+C 停止服务。" -ForegroundColor DarkGray
Write-Host ""

& $venvPython -m app.main
