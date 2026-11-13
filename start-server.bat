@echo off
setlocal
title Start NutriLens Server

schtasks /Query /TN "NutriLens Backend" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot access the "NutriLens Backend" scheduled task.
    echo Set up this task on this PC before using this shortcut.
    pause
    exit /b 1
)

schtasks /Run /TN "NutriLens Backend"
if errorlevel 1 (
    echo [ERROR] Failed to request server startup.
    pause
    exit /b 1
)

echo [OK] Server startup requested. SQLite uses this PC's backend configuration.
exit /b 0
