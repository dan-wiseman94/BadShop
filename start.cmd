@echo off
setlocal EnableExtensions DisableDelayedExpansion
if /i "%~1"=="--help" goto help
if not "%~1"=="" goto usage
pushd "%~dp0" || exit /b 1

set "missing="
for %%T in (uv.exe node.exe npm.cmd cargo.exe) do (
    where /q %%T || (
        echo Missing %%T
        set "missing=1"
    )
)
set "manager="
where /q pnpm && (
    call pnpm --version 2>nul | findstr /b /l /c:"10." >nul && set "manager=pnpm"
)
if not defined manager (
    where /q corepack && set "manager=corepack pnpm@10"
)
if not defined manager (
    echo Missing pnpm 10 or Corepack
    set "missing=1"
)
if defined missing (
    echo See the Windows source setup in docs\windows.md, then open start.cmd again.
    goto failed
)

echo Preparing the image tools. The first run downloads dependencies.
uv sync --project core --locked
if errorlevel 1 goto failed
echo Preparing the desktop app...
call %manager% --dir app install --frozen-lockfile
if errorlevel 1 goto failed
echo Starting badshop. The first build can take several minutes. Keep this window open.
call %manager% --dir app exec tauri dev --config src-tauri/tauri.source.conf.json
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo badshop could not start. Read the message above for the step that failed.
popd
pause
exit /b 1

:usage
echo Usage: start.cmd [--help]
exit /b 2

:help
echo Double-click start.cmd to prepare locked dependencies and open badshop from source.
echo For the Windows installer and source setup instructions, see docs\windows.md.
exit /b 0
