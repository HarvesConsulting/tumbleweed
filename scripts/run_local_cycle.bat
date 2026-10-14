@echo off
chcp 65001 > nul
cd /d C:\Users\lashy\Documents\tumbleweed
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
call .venv\Scripts\activate.bat
echo ========== %date% %time% ========== >> logs\local_cycle.log

echo [PARSE] >> logs\local_cycle.log
python scripts\run_cycle_jobs.py >> logs\local_cycle.log 2>&1

echo [NOTIFY] >> logs\local_cycle.log
python scripts\run_notify.py >> logs\local_cycle.log 2>&1

echo [DONE] Exit code: %ERRORLEVEL% >> logs\local_cycle.log
