@echo off
setlocal
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "127.0.0.1:8787.*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "127.0.0.1:5173.*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1
echo Freya services stopped.
endlocal
