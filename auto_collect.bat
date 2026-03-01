@echo off
cd /d %~dp0

REM ── 날짜 (PowerShell로 로케일 무관하게 yyyyMMdd 추출) ────────────────────────
for /f %%d in ('powershell -command "Get-Date -Format yyyyMMdd"') do set YYYYMMDD=%%d

echo [%date% %time%] ====== 수집 시작 ====== >> data\collect_log.txt

REM ── venv 활성화 & 수집 실행 ──────────────────────────────────────────────────
call .venv\Scripts\activate.bat
python collect_data.py >> data\collect_log.txt 2>&1

REM ── Git Push (변경 있을 때만) ─────────────────────────────────────────────────
git add data/
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "데이터 업데이트 %YYYYMMDD%"
    git push
    echo [%date% %time%] push 완료 >> data\collect_log.txt
) else (
    echo [%date% %time%] 변경 없음, push 스킵 >> data\collect_log.txt
)

echo [%date% %time%] ====== 완료 ====== >> data\collect_log.txt
