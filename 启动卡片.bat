@echo off
chcp 65001 >nul
rem 无控制台窗口启动 Claude 实时限额卡片
set "PYW=C:\Python314\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0quota_card.py"
