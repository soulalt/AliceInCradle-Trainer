@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ============================================================
rem  爱丽丝的摇篮 修改器 —— 启动器
rem  依次在常见位置寻找「带 tkinter 的 Python」，找到就用 pythonw 静默启动。
rem ============================================================

set "PYDIR="

call :try "%LOCALAPPDATA%\Microsoft\WindowsApps"
call :try "%LOCALAPPDATA%\Programs\Python\Python314"
call :try "%LOCALAPPDATA%\Programs\Python\Python313"
call :try "%LOCALAPPDATA%\Programs\Python\Python312"
call :try "%LOCALAPPDATA%\Programs\Python\Python311"
call :try "C:\Python314"
call :try "C:\Python313"
call :try "C:\Python312"
call :try "C:\Python311"
call :try "C:\Program Files\Python313"
call :try "C:\Program Files\Python312"

if not defined PYDIR goto :nofound

echo 使用解释器：%PYDIR%
start "" "%PYDIR%" "%~dp0aic_trainer.pyw"
exit /b 0

rem ------------------------------------------------------------
:try
if defined PYDIR exit /b 0
if not exist "%~1\python.exe" exit /b 0
"%~1\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 exit /b 0
if exist "%~1\pythonw.exe" (set "PYDIR=%~1\pythonw.exe") else (set "PYDIR=%~1\python.exe")
exit /b 0

rem ------------------------------------------------------------
:nofound
echo.
echo  [错误] 没有找到可用的 Python（需要 3.10 以上，并且自带 tkinter）。
echo.
echo  你可以：
echo    1^) 安装官方 Python 后重新双击本文件；
echo    2^) 直接双击 aic_trainer.pyw；
echo    3^) 或在命令行里运行：python "%~dp0aic_trainer.pyw"
echo.
pause
exit /b 1
