@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "JARVIS_SELFTEST="
set "CONDA_ENV=llama3"
set "PY_EXE="
set "PIP_EXE="

REM 1. If already inside an activated conda environment, use CONDA_PREFIX directly
if defined CONDA_PREFIX (
    if exist "%CONDA_PREFIX%\python.exe" (
        set "PY_EXE=%CONDA_PREFIX%\python.exe"
        set "PIP_EXE=%CONDA_PREFIX%\Scripts\pip.exe"
        set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\Library\mingw-w64\bin;%CONDA_PREFIX%\Library\usr\bin;%CONDA_PREFIX%\Library\bin;%CONDA_PREFIX%\Scripts;%CONDA_PREFIX%\bin;%PATH%"
        goto :found_env
    )
)

REM 2. Check common Anaconda / Miniconda paths
for %%P in (
    "%USERPROFILE%\anaconda3\envs\%CONDA_ENV%"
    "%USERPROFILE%\miniconda3\envs\%CONDA_ENV%"
    "%LOCALAPPDATA%\anaconda3\envs\%CONDA_ENV%"
    "%LOCALAPPDATA%\miniconda3\envs\%CONDA_ENV%"
    "C:\ProgramData\anaconda3\envs\%CONDA_ENV%"
    "C:\ProgramData\miniconda3\envs\%CONDA_ENV%"
    "C:\anaconda3\envs\%CONDA_ENV%"
    "C:\miniconda3\envs\%CONDA_ENV%"
) do (
    if exist "%%~P\python.exe" (
        set "PY_EXE=%%~P\python.exe"
        set "PIP_EXE=%%~P\Scripts\pip.exe"
        set "PATH=%%~P;%%~P\Library\mingw-w64\bin;%%~P\Library\usr\bin;%%~P\Library\bin;%%~P\Scripts;%%~P\bin;%PATH%"
        goto :found_env
    )
)

REM 3. Query conda info --envs to locate custom Conda installation path
where conda >nul 2>nul
if %ERRORLEVEL%==0 (
    for /f "tokens=1,2,3" %%A in ('conda info --envs 2^>nul') do (
        if "%%A"=="%CONDA_ENV%" (
            if exist "%%C\python.exe" (
                set "PY_EXE=%%C\python.exe"
                set "PIP_EXE=%%C\Scripts\pip.exe"
                set "PATH=%%C;%%C\Library\mingw-w64\bin;%%C\Library\usr\bin;%%C\Library\bin;%%C\Scripts;%%C\bin;%PATH%"
                goto :found_env
            )
            if exist "%%B\python.exe" (
                set "PY_EXE=%%B\python.exe"
                set "PIP_EXE=%%B\Scripts\pip.exe"
                set "PATH=%%B;%%B\Library\mingw-w64\bin;%%B\Library\usr\bin;%%B\Library\bin;%%B\Scripts;%%B\bin;%PATH%"
                goto :found_env
            )
        )
    )
)

REM Fallback to conda run if conda is in PATH
where conda >nul 2>nul
if %ERRORLEVEL%==0 (
    if "%~1"=="--install" (
        conda run --no-capture-output -n %CONDA_ENV% pip install -r requirements.txt
        exit /b %ERRORLEVEL%
    )
    if "%~1"=="--selftest" (
        if not exist "logs" mkdir logs
        del /q "logs\selftest.log" 2>nul
        set JARVIS_SELFTEST=1
        conda run --no-capture-output -n %CONDA_ENV% python jarvis.py --selftest
        exit /b %ERRORLEVEL%
    )
    conda run --no-capture-output -n %CONDA_ENV% python jarvis.py %*
    exit /b %ERRORLEVEL%
)

echo [Error] Could not find conda environment "%CONDA_ENV%".
exit /b 1

:found_env
if "%~1"=="--install" (
    echo [Jarvis] Installing dependencies into conda env "%CONDA_ENV%" ...
    "%PIP_EXE%" install -r requirements.txt
    exit /b %ERRORLEVEL%
)

"%PY_EXE%" -c "import sounddevice, edge_tts, webview, pystray, uiautomation, faster_whisper" 2>nul
if errorlevel 1 (
    echo [Jarvis] Installing required packages into conda env "%CONDA_ENV%" ...
    "%PIP_EXE%" install -r requirements.txt
)

if "%~1"=="--selftest" (
    if not exist "logs" mkdir logs
    del /q "logs\selftest.log" 2>nul
    "%PY_EXE%" jarvis.py --selftest
    exit /b %ERRORLEVEL%
)

"%PY_EXE%" jarvis.py %*
