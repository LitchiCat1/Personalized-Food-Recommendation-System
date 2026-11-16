@echo off
setlocal
title Stop NutriLens Server

schtasks /Query /TN "NutriLens Backend" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot access the "NutriLens Backend" scheduled task.
    echo Set up this task on this PC before using this shortcut.
    pause
    exit /b 1
)

schtasks /End /TN "NutriLens Backend"
if errorlevel 1 (
    echo [ERROR] Failed to request server shutdown.
    pause
    exit /b 1
)

echo [OK] Server shutdown requested. SQLite data is retained.
exit /b 0
