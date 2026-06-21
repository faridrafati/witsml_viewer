@echo off
REM ===========================================================================
REM  WITSML 1.4.1.1 Mudlogging Monitor - one-command launcher (Windows).
REM
REM  Usage:
REM    run.bat            full stack via Docker (recommended)
REM    run.bat docker     same as above
REM    run.bat native     run WITHOUT Docker (Python venv + npm + SQLite)
REM    run.bat down       stop the Docker stack
REM
REM  Docker mode downloads + builds everything (api, web, mock WITSML store,
REM  feed simulator, postgres, redis). Native mode installs Python + Node deps
REM  locally and runs the stack with SQLite + an in-process cache. Runtimes
REM  (Docker / Python 3.11+ / Node 18+) are NOT auto-installed - the script
REM  detects them and prints the install link if missing.
REM ===========================================================================
setlocal enableextensions
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=docker"

if /i "%MODE%"=="docker" goto docker
if /i "%MODE%"=="native" goto native
if /i "%MODE%"=="down"   goto down
if /i "%MODE%"=="stop"   goto down
echo [run] unknown mode "%MODE%" (use: docker ^| native ^| down)
exit /b 1

:ensure_env
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo [run] created .env from .env.example
)
goto :eof

:urls
echo.
echo   WITSML Mudlogging Monitor
echo     Web UI        : http://localhost:5173
echo     API docs      : http://localhost:8000/docs
echo     API health    : http://localhost:8000/health
echo     Default login : admin / admin
echo.
goto :eof

:docker
where docker >nul 2>&1 || (echo [run] Docker is not installed - get it at https://docs.docker.com/get-docker/ & exit /b 1)
docker compose version >nul 2>&1 || (echo [run] Docker Compose v2 not found ^(update Docker Desktop^). & exit /b 1)
docker info >nul 2>&1 || (echo [run] The Docker daemon isn't running - start Docker Desktop and retry. & exit /b 1)
call :ensure_env
call :urls
echo [run] building + starting the stack (first run pulls/builds images - a few minutes)...
docker compose up --build
exit /b %errorlevel%

:down
docker compose down
echo [run] stack stopped
exit /b 0

:native
where python >nul 2>&1 || (echo [run] Python 3.11+ is required for native mode - https://www.python.org/downloads/ & exit /b 1)
where node >nul 2>&1 || (echo [run] Node.js 18+ is required for native mode - https://nodejs.org & exit /b 1)
call :ensure_env

if not exist "backend\.venv" (
  echo [run] creating Python venv...
  python -m venv backend\.venv
)
set "VPY=backend\.venv\Scripts\python.exe"
echo [run] installing backend dependencies...
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -e backend
if not exist "frontend\node_modules" (
  echo [run] installing frontend dependencies ^(npm install^)...
  pushd frontend && call npm install && popd
)

if not exist ".run" mkdir ".run"
set "MOCK_PORT=8090"
set "API_PORT=8000"
set "WITSML_URL=http://127.0.0.1:%MOCK_PORT%/witsml/store"
set "DATABASE_URL=sqlite+aiosqlite:///./witsml_native.db"
set "REDIS_URL="
set "POLL_INTERVAL_SECONDS=5"
set "VITE_API_BASE_URL=http://localhost:%API_PORT%"
set "VITE_WS_BASE_URL=ws://localhost:%API_PORT%"
REM backend on PYTHONPATH for app.*, repo root for the mockstore/simulator packages.
set "PYTHONPATH=backend;."

echo [run] starting mock WITSML store on :%MOCK_PORT% ...
start "WITSML mock store" cmd /c "%VPY% -m uvicorn mockstore.server:app --host 127.0.0.1 --port %MOCK_PORT% --log-level warning"
timeout /t 3 >nul
echo [run] starting feed simulator ...
start "WITSML simulator" cmd /c "%VPY% -m simulator.feed_simulator"
echo [run] starting API on :%API_PORT% ...
start "WITSML API" cmd /c "%VPY% -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%"
call :urls
echo [run] services launched in separate windows. Starting the web dev server here...
echo [run] (close the spawned windows to stop the mock/simulator/API)
pushd frontend && call npm run dev -- --host & popd
exit /b 0
