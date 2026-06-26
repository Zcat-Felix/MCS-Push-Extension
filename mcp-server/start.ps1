<#
.SYNOPSIS
  MCP Task Server launcher
  Auto-detect Node.js 18+ and Python 3.8+, download if missing
.DESCRIPTION
  1. Check system PATH for node >= 18, else download to _runtime\node\
  2. Check system PATH for python >= 3.8, else download to _runtime\python\
  3. Set PYTHON_CMD env var for server.mjs
  4. Launch server.mjs
#>

$ServerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir  = Join-Path $ServerDir "_runtime"
$NodeDir     = Join-Path $RuntimeDir "node"
$NodeExe     = Join-Path $NodeDir "node.exe"
$PythonDir   = Join-Path $RuntimeDir "python"
$PythonExe   = Join-Path $PythonDir "python.exe"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  MCP Task Server - Environment Setup" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# ========== Node.js check / download ==========
$foundNode = $null
try {
    $v = & node --version 2>$null
    if ($v -match "^v(\d+)") {
        $major = [int]$Matches[1]
        if ($major -ge 18) {
            $foundNode = "node"
            Write-Host "[OK] Node.js $v (system)" -ForegroundColor Green
        } else { Write-Host "[WARN] Node.js $v too old" -ForegroundColor Yellow }
    }
} catch { Write-Host "[INFO] Node.js not found in PATH" -ForegroundColor Yellow }

if (-not $foundNode -and (Test-Path $NodeExe)) {
    try {
        $v = & $NodeExe --version 2>$null
        if ($v -match "^v(\d+)" -and [int]$Matches[1] -ge 18) {
            $foundNode = $NodeExe
            Write-Host "[OK] Node.js $v (local runtime)" -ForegroundColor Green
        }
    } catch {}
}

if (-not $foundNode) {
    Write-Host "[..] Downloading Node.js v18.20.4 ..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $zipUrl = "https://nodejs.org/dist/v18.20.4/node-v18.20.4-win-x64.zip"
        $zipFile = Join-Path $RuntimeDir "node-dl.zip"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
        Expand-Archive -Path $zipFile -DestinationPath $RuntimeDir -Force
        $extracted = Join-Path $RuntimeDir "node-v18.20.4-win-x64"
        if (Test-Path $extracted) {
            Move-Item "$extracted\*" $NodeDir -Force
            Remove-Item -Recurse -Force $extracted -ErrorAction SilentlyContinue
        }
        Remove-Item $zipFile -Force -ErrorAction SilentlyContinue
        if (Test-Path $NodeExe) {
            $foundNode = $NodeExe
            Write-Host "[OK] Node.js downloaded!" -ForegroundColor Green
        } else { throw "node.exe not found after extraction" }
    } catch {
        Write-Host "[FAIL] Node.js download error: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "[HINT] Install Node.js 18+ manually: https://nodejs.org" -ForegroundColor Yellow
        pause; exit 1
    }
}

# ========== Python check / download ==========
$foundPython = $null

function Test-PythonExe($exe) {
    try {
        $v = & $exe --version 2>&1
        if ($v -match "(\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and ($major -gt 3 -or $minor -ge 8)) {
                return "$major.$minor"
            }
        }
    } catch {}
    return $null
}

$pyVer = Test-PythonExe "python"
if ($pyVer) {
    $foundPython = "python"
    Write-Host "[OK] Python $pyVer (system)" -ForegroundColor Green
} else {
    $pyVer = Test-PythonExe "python3"
    if ($pyVer) {
        $foundPython = "python3"
        Write-Host "[OK] Python $pyVer (system)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Python 3.8+ not found in PATH" -ForegroundColor Yellow
    }
}

if (-not $foundPython -and (Test-Path $PythonExe)) {
    $pyVer = Test-PythonExe $PythonExe
    if ($pyVer) {
        $foundPython = $PythonExe
        Write-Host "[OK] Python $pyVer (local runtime)" -ForegroundColor Green
    } else {
        Remove-Item -Recurse -Force $PythonDir -ErrorAction SilentlyContinue
    }
}

if (-not $foundPython) {
    Write-Host "[..] Downloading Python 3.12.8 (embeddable) ..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $pyUrl  = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
        $zipFile = Join-Path $RuntimeDir "python-dl.zip"
        Invoke-WebRequest -Uri $pyUrl -OutFile $zipFile -UseBasicParsing
        Expand-Archive -Path $zipFile -DestinationPath $PythonDir -Force
        Remove-Item $zipFile -Force -ErrorAction SilentlyContinue

        # Enable import site in python3*._pth so scripts find local modules
        $pthFile = Get-ChildItem $PythonDir -Filter "python3*._pth" | Select-Object -First 1 -ExpandProperty FullName
        if ($pthFile) {
            (Get-Content $pthFile) -replace "^#import site", "import site" | Set-Content $pthFile
            Write-Host "[OK] python import site enabled" -ForegroundColor Green
        }

        if (Test-Path $PythonExe) {
            $foundPython = $PythonExe
            Write-Host "[OK] Python downloaded!" -ForegroundColor Green
        } else { throw "python.exe not found after extraction" }
    } catch {
        Write-Host "[FAIL] Python download error: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "[HINT] Install Python 3.8+ manually: https://python.org" -ForegroundColor Yellow
        pause; exit 1
    }
}

# ========== Launch server ==========
Write-Host "-------------------------------------" -ForegroundColor Cyan
Write-Host "Starting MCP Task Server on port 5200" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host "-------------------------------------" -ForegroundColor Cyan
Write-Host ""

Set-Location $ServerDir

# Set PYTHON_CMD for server.mjs
$env:PYTHON_CMD = $foundPython

if ($foundNode -eq "node") {
    & node server.mjs
} else {
    & $foundNode server.mjs
}

if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Server exited with code $LASTEXITCODE" -ForegroundColor Red
    pause
}
