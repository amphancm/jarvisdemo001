# Companion launcher for Windows 11 using Conda environment "llama3"
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot

# Always clear JARVIS_SELFTEST from previous runs in the same PowerShell session
Remove-Item Env:\JARVIS_SELFTEST -ErrorAction SilentlyContinue

$CondaEnv = "llama3"
$EnvPath = $null

# 1. If already inside the activated conda env, use CONDA_PREFIX directly
if ($env:CONDA_DEFAULT_ENV -eq $CondaEnv -and $env:CONDA_PREFIX -and (Test-Path "$env:CONDA_PREFIX\python.exe")) {
    $EnvPath = $env:CONDA_PREFIX
}

# 2. Otherwise search common Anaconda / Miniconda paths
if (-not $EnvPath) {
    $Candidates = @(
        "$env:USERPROFILE\anaconda3\envs\$CondaEnv",
        "$env:USERPROFILE\miniconda3\envs\$CondaEnv",
        "$env:LOCALAPPDATA\anaconda3\envs\$CondaEnv",
        "$env:LOCALAPPDATA\miniconda3\envs\$CondaEnv",
        "C:\ProgramData\anaconda3\envs\$CondaEnv",
        "C:\ProgramData\miniconda3\envs\$CondaEnv",
        "C:\anaconda3\envs\$CondaEnv",
        "C:\miniconda3\envs\$CondaEnv"
    )
    foreach ($c in $Candidates) {
        if ($c -and (Test-Path "$c\python.exe")) {
            $EnvPath = $c
            break
        }
    }
}

# 3. Fallback: query conda info --envs
if (-not $EnvPath -and (Get-Command conda -ErrorAction SilentlyContinue)) {
    $info = conda info --envs | Select-String -Pattern "^\s*$CondaEnv\s+"
    if ($info) {
        $parts = ($info.Line -split "\s+") | Where-Object { $_ -ne "" }
        $last = $parts[-1]
        if (Test-Path "$last\python.exe") {
            $EnvPath = $last
        }
    }
}

if ($EnvPath) {
    $PyExe = "$EnvPath\python.exe"
    $PipExe = "$EnvPath\Scripts\pip.exe"
    $env:CONDA_PREFIX = $EnvPath
    $env:CONDA_DEFAULT_ENV = $CondaEnv
    $env:PATH = "$EnvPath;$EnvPath\Library\mingw-w64\bin;$EnvPath\Library\usr\bin;$EnvPath\Library\bin;$EnvPath\Scripts;$EnvPath\bin;$env:PATH"

    if ($args -contains "--install") {
        Write-Host "[Jarvis] Installing dependencies into Conda env '$CondaEnv' ..." -ForegroundColor Cyan
        & $PipExe install -r requirements.txt
        exit $LASTEXITCODE
    }

    $ErrorActionPreference = "Continue"
    & $PyExe -c "import sounddevice, edge_tts, webview, pystray, uiautomation, faster_whisper" 2>$null
    $pkgOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = "Stop"

    if (-not $pkgOk) {
        Write-Host "[Jarvis] Installing required packages into Conda env '$CondaEnv' ..." -ForegroundColor Cyan
        & $PipExe install -r requirements.txt
    }

    if ($args -contains "--selftest") {
        New-Item -ItemType Directory -Force -Path "logs" | Out-Null
        Remove-Item "logs\selftest.log" -ErrorAction SilentlyContinue
        & $PyExe jarvis.py --selftest
        exit $LASTEXITCODE
    }

    & $PyExe jarvis.py @args
    exit $LASTEXITCODE
}

if (Get-Command conda -ErrorAction SilentlyContinue) {
    if ($args -contains "--selftest") {
        New-Item -ItemType Directory -Force -Path "logs" | Out-Null
        Remove-Item "logs\selftest.log" -ErrorAction SilentlyContinue
        conda run --no-capture-output -n $CondaEnv python jarvis.py --selftest
        exit $LASTEXITCODE
    }
    conda run --no-capture-output -n $CondaEnv python jarvis.py @args
    exit $LASTEXITCODE
}

Write-Error "[Error] Could not find Conda environment '$CondaEnv'."
exit 1
