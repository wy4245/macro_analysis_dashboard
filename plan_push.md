# 자동 수집 & Git Push 계획

## 현황 및 제약

현재 `collect_data.py`는 두 가지 기술을 사용한다:

| 수집 대상 | 기술 | 제약 |
|---|---|---|
| KOFIA 채권 금리 (BondSummary, BondSummary_OTC) | Selenium + Chrome | Chrome 설치 필요 |
| 글로벌 국채 (GlobalTreasury) | Playwright + Cloudflare 우회 | 실제 브라우저 환경 필요 |

→ **GitHub Actions 등 클라우드 CI는 사용 불가** (Cloudflare가 CI IP를 차단, KOFIA WebSquare도 headless 감지 위험)
→ **로컬 PC(또는 상시 켜둔 Windows 서버)에서 스케줄 자동화**가 현실적인 유일한 방법


---

## 권장 방식: Windows 작업 스케줄러 + BAT 스크립트

### 개요

```
[작업 스케줄러] → auto_collect.bat 실행
                     ├─ venv 활성화
                     ├─ python collect_data.py
                     └─ git add / commit / push
```

- 평일 장 마감 후(예: 17:00) 자동 실행
- 수집 결과 로그 파일(`data/collect_log.txt`)에 저장
- 수집 실패 시 기존 데이터 보존(기존 `collect_data.py` 동작 그대로)

---

## 구현 계획

### Step 1 — `auto_collect.bat` 작성

프로젝트 루트에 `auto_collect.bat` 신규 생성:

```bat
@echo off
cd /d %~dp0

REM ── 날짜 포맷 ──────────────────────────────────────
set YYYYMMDD=%date:~0,4%%date:~5,2%%date:~8,2%

REM ── 로그 초기화 ────────────────────────────────────
echo [%date% %time%] 수집 시작 >> data\collect_log.txt

REM ── venv 활성화 & 수집 실행 ────────────────────────
call .venv\Scripts\activate.bat
python collect_data.py >> data\collect_log.txt 2>&1

REM ── Git Push ────────────────────────────────────────
git add data/
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "데이터 업데이트 %YYYYMMDD%"
    git push
    echo [%date% %time%] push 완료 >> data\collect_log.txt
) else (
    echo [%date% %time%] 변경 없음, push 스킵 >> data\collect_log.txt
)
```

**포인트:**
- `git diff --cached --quiet`: 변경 없으면 commit/push 스킵 (불필요한 empty commit 방지)
- 모든 출력이 `data/collect_log.txt`에 누적 기록

---

### Step 2 — 작업 스케줄러 등록

PowerShell에서 아래 명령 실행 (1회):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\user\Desktop\KAIST_MFE\Macro_Analysis\MMS\auto_collect.bat"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 17:00

Register-ScheduledTask `
    -TaskName   "MMS_AutoCollect" `
    -Action     $action `
    -Trigger    $trigger `
    -RunLevel   Highest `
    -Description "MMS 데이터 수집 및 Git Push 자동화"
```

또는 GUI로 등록:
1. `Win + R` → `taskschd.msc`
2. 기본 작업 만들기 → 매주 월~금 17:00
3. 프로그램 시작 → `auto_collect.bat` 경로 입력

---

### Step 3 — `data/collect_log.txt`를 `.gitignore`에 추가

로그 파일이 매일 commit되지 않도록:

```
# .gitignore에 추가
data/collect_log.txt
data/tmp/
```

---

## 추가 고려 사항

### PC가 꺼져 있을 경우
- 작업 스케줄러 설정에서 **"놓친 작업 즉시 실행"** 체크
- 다음 날 PC 켜는 순간 자동 실행됨
- 단, 2일 이상 꺼져 있었으면 마지막 날짜부터 증분 수집으로 자동 복구 (기존 로직)

### Git Push 인증
- SSH 키 또는 자격 증명 관리자(Windows Credential Manager)에 GitHub 계정이 저장되어 있어야 함
- 최초 1회 `git push` 수동 실행으로 인증 저장 확인 필요

### 수집 실패 모니터링
- `data/collect_log.txt` 주기적 확인
- 또는 BAT 파일에 메일/알림 발송 로직 추가 가능 (PowerShell Send-MailMessage 등)

---

## 대안: Python `schedule` 라이브러리 (항상 켜둔 PC/서버 환경)

PC를 24시간 켜두거나 별도 서버가 있다면 Python 데몬 방식도 가능:

```python
# scheduler.py
import schedule, time, subprocess

def job():
    subprocess.run(["python", "collect_data.py"])
    subprocess.run(["git", "add", "data/"])
    subprocess.run(["git", "commit", "-m", f"자동 업데이트"])
    subprocess.run(["git", "push"])

schedule.every().monday.at("17:00").do(job)
schedule.every().tuesday.at("17:00").do(job)
# ... 화/수/목/금 반복

while True:
    schedule.run_pending()
    time.sleep(60)
```

실행: `python scheduler.py` (백그라운드 프로세스로 유지)

→ **단순성 면에서 작업 스케줄러 방식이 더 권장됨**

---

## 요약

| 항목 | 내용 |
|---|---|
| 방식 | Windows 작업 스케줄러 + `auto_collect.bat` |
| 실행 시간 | 평일 17:00 (한국 장 마감 후) |
| 신규 파일 | `auto_collect.bat` (프로젝트 루트) |
| 변경 파일 | `.gitignore` (로그 파일 추가) |
| 기존 코드 변경 | 없음 (`collect_data.py` 그대로 사용) |
