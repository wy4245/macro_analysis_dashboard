"""
BondSummary_OTC 디버그 테스트

브라우저 창을 띄운 채로 OTC 페이지 크롤링 과정을 확인합니다.
배치 A 하나만 실행하여 다운로드 파일명을 확인하는 것이 주목적입니다.

실행:
    python test_OTC.py
"""

import os
import sys
import glob
import time
from pathlib import Path
from datetime import date, timedelta

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─── 설정 ─────────────────────────────────────────────────────────────────────

# 테스트 기간 (짧게)
END_DATE   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
START_DATE = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

# 배치 A만 테스트 (국고채권 2~30년)
TEST_BATCH_IDS = [
    "chkAnnItm_input_0",   # 국고채권(2년)
    "chkAnnItm_input_1",   # 국고채권(3년)
    "chkAnnItm_input_2",   # 국고채권(5년)
    "chkAnnItm_input_3",   # 국고채권(10년)
    "chkAnnItm_input_4",   # 국고채권(20년)
    "chkAnnItm_input_5",   # 국고채권(30년)
]

# 페이지 기본 체크 해제 대상
INIT_UNCHECK = [
    "chkAnnItm_input_1",
    "chkAnnItm_input_2",
    "chkAnnItm_input_3",
    "chkAnnItm_input_12",
    "chkAnnItm_input_13",
    "chkAnnItm_input_16",
]

DOWNLOAD_DIR = str(_root / "data" / "tmp")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

KOFIA_URL = "https://www.kofiabond.or.kr/index.html"


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _safe_click(driver, wait, by, value):
    el = wait.until(EC.presence_of_element_located((by, value)))
    driver.execute_script("arguments[0].click();", el)
    print(f"  클릭: {value}")


def _force_click_checkbox(driver, cid: str):
    try:
        cb = driver.find_element(By.ID, cid)
        driver.execute_script("arguments[0].click();", cb)
    except Exception as e:
        print(f"  [체크박스 오류] {cid}: {e}")


def _scan_downloads(directory: str) -> list[str]:
    """디렉토리 내 모든 파일 목록 반환."""
    return [
        os.path.basename(f)
        for f in glob.glob(os.path.join(directory, "*"))
        if os.path.isfile(f) and not f.endswith(".crdownload")
    ]


def _wait_and_find_new_file(directory: str, before: set, timeout: int = 60) -> str | None:
    """다운로드 전후 파일 목록을 비교하여 새로 생긴 파일을 반환."""
    for i in range(timeout):
        current = set(_scan_downloads(directory))
        new_files = current - before
        # .crdownload 중간 파일 제외
        complete = [f for f in new_files if not f.endswith(".crdownload")]
        if complete:
            return complete[0]
        if i % 5 == 0:
            print(f"  다운로드 대기 중... ({i}초)")
        time.sleep(1)
    return None


# ─── 메인 테스트 ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("BondSummary_OTC 디버그 테스트")
    print(f"기간: {START_DATE} ~ {END_DATE}")
    print(f"다운로드 경로: {DOWNLOAD_DIR}")
    print("=" * 60)

    # Chrome 옵션 — headless=False (창 보임)
    opts = Options()
    # opts.add_argument("--headless=new")  # 주석 처리 → 창 표시
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts,
    )
    wait = WebDriverWait(driver, 30)

    try:
        # ── 1. 다운로드 전 파일 목록 스냅샷
        before_files = set(_scan_downloads(DOWNLOAD_DIR))
        print(f"\n[사전] 다운로드 폴더 파일: {before_files or '(없음)'}")

        # ── 2. KOFIA 접속
        print(f"\n[1] KOFIA 접속: {KOFIA_URL}")
        driver.get(KOFIA_URL)
        print("  5초 대기 (초기 로딩)...")
        time.sleep(5)

        # ── 3. 메뉴 진입
        print("\n[2] 메뉴 진입")
        driver.switch_to.frame("fraAMAKMain")
        _safe_click(driver, wait, By.ID, "genLv1_0_imgLv1")
        time.sleep(1)
        _safe_click(driver, wait, By.ID, "genLv1_0_genLv2_1_txtLv2")  # 장외거래대표수익률
        print("  3초 대기 (페이지 로딩)...")
        time.sleep(3)

        # ── 4. 프레임 진입
        print("\n[3] 프레임 진입")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "maincontent")))
        print("  maincontent 프레임 진입 완료")

        _safe_click(driver, wait, By.ID, "tabContents1_tab_tabs2")
        print("  3초 대기 (기간별 탭 로딩)...")
        time.sleep(3)

        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "tabContents1_contents_tabs2_body")))
        print("  tabContents1_contents_tabs2_body 프레임 진입 완료")

        # ── 5. 날짜 설정
        print(f"\n[4] 날짜 설정: {START_DATE} ~ {END_DATE}")
        s = wait.until(EC.presence_of_element_located((By.ID, "startDtDD_input")))
        e = wait.until(EC.presence_of_element_located((By.ID, "endDtDD_input")))
        driver.execute_script("arguments[0].value = '';", s)
        s.send_keys(START_DATE)
        driver.execute_script("arguments[0].value = '';", e)
        e.send_keys(END_DATE)
        time.sleep(1)
        print("  날짜 입력 완료")

        # ── 6. 체크박스 조작
        print("\n[5] 체크박스 조작")
        print("  기본 체크 해제 중...")
        for cid in INIT_UNCHECK:
            _force_click_checkbox(driver, cid)
        time.sleep(0.3)

        print("  배치 A 체크 중...")
        for cid in TEST_BATCH_IDS:
            _force_click_checkbox(driver, cid)
        time.sleep(0.5)

        # ── 7. 조회 버튼
        print("\n[6] 조회 버튼 클릭 (image8)")
        _safe_click(driver, wait, By.ID, "image8")
        print("  5초 대기 (조회 완료)...")
        time.sleep(5)

        # ── 8. 엑셀 다운로드
        print("\n[7] 엑셀 다운로드 버튼 클릭 (imgExcel)")
        _safe_click(driver, wait, By.ID, "imgExcel")
        print("  다운로드 대기 중...")

        new_file = _wait_and_find_new_file(DOWNLOAD_DIR, before_files, timeout=60)

        # ── 9. 결과 확인
        print("\n" + "=" * 60)
        if new_file:
            print(f"✓ 다운로드 성공!")
            print(f"  실제 파일명: '{new_file}'")
            print(f"  → kofia.py 의 _OTC_DL_FILE 을 이 이름으로 수정하세요.")

            # 파일 파싱 시도
            full_path = os.path.join(DOWNLOAD_DIR, new_file)
            try:
                import pandas as pd
                try:
                    dfs = pd.read_html(full_path, flavor="lxml")
                    df = dfs[0]
                except Exception:
                    df = pd.read_excel(full_path)
                print(f"\n  파싱 결과: {len(df)}행 {len(df.columns)}열")
                print(f"  컬럼: {df.columns.tolist()[:10]}")
                print(df.head(3).to_string())
            except Exception as ex:
                print(f"  [파싱 오류] {ex}")
        else:
            print("✗ 다운로드 실패 — 파일을 찾지 못했습니다.")
            after_files = set(_scan_downloads(DOWNLOAD_DIR))
            print(f"  현재 폴더 파일: {after_files or '(없음)'}")
            print("\n  브라우저 창에서 직접 상태를 확인하세요.")
            print("  Enter 키를 누르면 종료합니다...")
            input()

        print("=" * 60)

    except Exception as e:
        print(f"\n[오류] {type(e).__name__}: {e}")
        print("브라우저 창에서 직접 상태를 확인하세요.")
        print("Enter 키를 누르면 종료합니다...")
        input()
    finally:
        driver.quit()
        print("브라우저 종료.")


if __name__ == "__main__":
    main()
