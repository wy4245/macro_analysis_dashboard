"""
KOFIA 데이터 수집기

TreasurySummary : 주요 만기 국채 금리 (1년치) — 기간별 탭, 5개 시리즈
BondSummary     : 전종목 최종호가수익률 (5년치) — 18개 시리즈, 3배치 수집 후 병합

공통 흐름:
  default_content
    → frame "fraAMAKMain"  (메뉴 클릭)
    → frame "maincontent"  (기간별 탭 클릭)
    → frame "tabContents1_contents_tabs2_body"  (날짜·체크박스 조작)
"""

import os
import sys
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from modules.calculator.kofia import KofiaCalc  # noqa: E402

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ─── 공통 Selenium 헬퍼 ───────────────────────────────────────────────────────

_KOFIA_URL        = "https://www.kofiabond.or.kr/index.html"
_KOFIA_DL_FILE    = "최종호가 수익률.xls"


def _build_options(headless: bool, download_path: str) -> Options:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("prefs", {
        "download.default_directory": download_path,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    return opts


def _navigate_to_period_tab(driver, wait):
    """메뉴 클릭 → 기간별 탭 → 내부 프레임까지 진입."""
    driver.get(_KOFIA_URL)
    time.sleep(5)

    driver.switch_to.frame("fraAMAKMain")
    _safe_click(driver, wait, By.ID, "genLv1_0_imgLv1")
    time.sleep(1)
    _safe_click(driver, wait, By.ID, "genLv1_0_genLv2_0_txtLv2")
    time.sleep(3)

    wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "maincontent")))
    _safe_click(driver, wait, By.ID, "tabContents1_tab_tabs2")
    time.sleep(3)

    wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "tabContents1_contents_tabs2_body")))


def _safe_click(driver, wait, by, value):
    el = wait.until(EC.presence_of_element_located((by, value)))
    driver.execute_script("arguments[0].click();", el)


def _set_checkbox(driver, cid: str, checked: bool):
    try:
        cb = driver.find_element(By.ID, cid)
        if cb.is_selected() != checked:
            driver.execute_script("arguments[0].click();", cb)
    except Exception:
        pass


def _set_date_range(driver, wait, start_str: str, end_str: str):
    s = wait.until(EC.presence_of_element_located((By.ID, "startDtDD_input")))
    e = wait.until(EC.presence_of_element_located((By.ID, "endDtDD_input")))
    driver.execute_script("arguments[0].value = '';", s)
    s.send_keys(start_str)
    driver.execute_script("arguments[0].value = '';", e)
    e.send_keys(end_str)
    time.sleep(1)


def _wait_for_download(save_dir: str, cwd: str, timeout: int = 30) -> str | None:
    for _ in range(timeout):
        for p in [
            os.path.join(save_dir, _KOFIA_DL_FILE),
            os.path.join(cwd, _KOFIA_DL_FILE),
            os.path.join(cwd, "data", "raw", _KOFIA_DL_FILE),
        ]:
            if os.path.exists(p):
                return p
        time.sleep(1)
    return None


def _parse_kofia_xls(file_path: str) -> pd.DataFrame | None:
    """KOFIA .xls(HTML 테이블) 파일 → Date 컬럼 표준화된 DataFrame."""
    try:
        try:
            dfs = pd.read_html(file_path, flavor="lxml")
            df  = dfs[0]
        except Exception:
            df = pd.read_excel(file_path)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col).strip() for col in df.columns]

        date_col = next((c for c in df.columns if "일자" in str(c) or "Date" in str(c)), None)
        if not date_col:
            return None

        df = df[~df[date_col].astype(str).str.contains("최고|최저|Average|Max|Min", na=False)]
        df[date_col] = pd.to_datetime(
            df[date_col].astype(str).str.replace(r"[^0-9-]", "", regex=True), errors="coerce"
        )
        df = df.dropna(subset=[date_col])
        df = df.rename(columns={date_col: "Date"})
        df["Date"] = df["Date"].dt.date
        return df
    except Exception as e:
        print(f"  [파싱 오류] {file_path}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: TreasurySummary
# ══════════════════════════════════════════════════════════════════════════════

class TreasurySummary:
    """
    KOFIA 주요 만기 국채 금리 수집 (1년치).

    수집 대상: 국고채 2/3/10/20/30년
    출력 파일: data/raw/YYYYMMDD/treasury_summary.xlsx
    """

    # 기본 체크 해제 (페이지 로드 시 기본 선택됨)
    _UNCHECK = ["chkAnnItm_input_10", "chkAnnItm_input_11",
                "chkAnnItm_input_14", "chkAnnItm_input_16"]
    # 수집 대상 체크 (KTB 2/3/10/20/30yr)
    _CHECK   = ["chkAnnItm_input_1", "chkAnnItm_input_2",
                "chkAnnItm_input_4", "chkAnnItm_input_5", "chkAnnItm_input_6"]

    def __init__(self, download_dir: str | None = None):
        if download_dir is None:
            self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "raw"))
        else:
            self.download_dir = os.path.abspath(download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

    def collect(self, target_date=None, headless: bool = True) -> bool:
        """
        Selenium으로 KOFIA 기간별 탭을 조작하여 국채 금리 xlsx를 수집합니다.

        Args:
            target_date: "YYYYMMDD" 문자열 또는 datetime (없으면 오늘)
            headless   : True이면 브라우저 창 없이 실행

        Returns:
            True on success, False on failure.
        """
        from datetime import timedelta

        if not target_date:
            target_date = datetime.now()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y%m%d")

        end_str = target_date.strftime("%Y-%m-%d")
        try:
            start_dt = target_date.replace(year=target_date.year - 1)
        except ValueError:
            start_dt = target_date - timedelta(days=365)
        start_str = start_dt.strftime("%Y-%m-%d")

        date_str       = target_date.strftime("%Y%m%d")
        daily_save_dir = os.path.join(self.download_dir, date_str)
        os.makedirs(daily_save_dir, exist_ok=True)

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=_build_options(headless, daily_save_dir),
        )
        wait = WebDriverWait(driver, 30)

        try:
            _navigate_to_period_tab(driver, wait)
            _set_date_range(driver, wait, start_str, end_str)

            for cid in self._UNCHECK:
                _set_checkbox(driver, cid, False)
            for cid in self._CHECK:
                _set_checkbox(driver, cid, True)
            time.sleep(1)

            _safe_click(driver, wait, By.ID, "image4")
            time.sleep(5)
            _safe_click(driver, wait, By.ID, "imgExcel")
            time.sleep(5)

            dl = _wait_for_download(daily_save_dir, os.getcwd())
            if not dl:
                print("  [오류] 다운로드 파일 미발견")
                return False

            final = os.path.join(daily_save_dir, "treasury_summary.xlsx")
            if os.path.exists(final):
                os.remove(final)

            df = _parse_kofia_xls(dl)
            if df is not None and "Date" in df.columns:
                df = df.sort_values("Date", ascending=True)
                df.to_excel(final, index=False, engine="openpyxl")
                if os.path.exists(dl):
                    os.remove(dl)
                print(f"  [완료] {final}  ({len(df)}행)")
            else:
                os.rename(dl, os.path.join(daily_save_dir, "treasury_summary.xls"))
                print("  [경고] 날짜 컬럼 미발견 — 파일명만 변경")

            return True

        except Exception as e:
            print(f"  [Selenium 오류] {e}")
            try:
                with open(os.path.join(self.download_dir, "selenium_error_treasury.html"), "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except Exception:
                pass
            return False
        finally:
            driver.quit()

    def load(self, target_date) -> pd.DataFrame | None:
        """
        저장된 treasury_summary.xlsx 를 읽어 표준화된 DataFrame으로 반환.

        Returns:
            Date 인덱스, KR_{n}Y 컬럼 형식의 DataFrame. 실패 시 None.
        """
        date_str  = target_date.strftime("%Y%m%d") if isinstance(target_date, datetime) else str(target_date)
        file_path = os.path.join(self.download_dir, date_str, "treasury_summary.xlsx")

        if not os.path.exists(file_path):
            print(f"  [파일 없음] {file_path}")
            return None
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
            return KofiaCalc.standardize(df)
        except Exception as e:
            print(f"  [읽기 오류] {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: BondSummary
# ══════════════════════════════════════════════════════════════════════════════

_BOND_SUMMARY_BATCHES = [
    {
        "name": "A",
        "ids": [
            "chkAnnItm_input_0",   # 국고채권(1년)
            "chkAnnItm_input_1",   # 국고채권(2년)
            "chkAnnItm_input_2",   # 국고채권(3년)
            "chkAnnItm_input_3",   # 국고채권(5년)
            "chkAnnItm_input_4",   # 국고채권(10년)
            "chkAnnItm_input_5",   # 국고채권(20년)
        ],
    },
    {
        "name": "B",
        "ids": [
            "chkAnnItm_input_6",   # 국고채권(30년)
            "chkAnnItm_input_7",   # 국고채권(50년)
            "chkAnnItm_input_8",   # 국민주택1종(5년)
            "chkAnnItm_input_9",   # 통안증권(91일)
            "chkAnnItm_input_10",  # 통안증권(1년)
            "chkAnnItm_input_11",  # 통안증권(2년)
        ],
    },
    {
        "name": "C",
        "ids": [
            "chkAnnItm_input_12",  # 한전채(3년)
            "chkAnnItm_input_13",  # 산금채(1년)
            "chkAnnItm_input_14",  # 회사채(무보증3년)AA-
            "chkAnnItm_input_15",  # 회사채(무보증3년)BBB-
            "chkAnnItm_input_16",  # CD수익률(91일)
            "chkAnnItm_input_17",  # CP(91일)
        ],
    },
]

_BOND_SUMMARY_INIT_UNCHECK = [
    "chkAnnItm_input_16",  # CD수익률(91일)
    "chkAnnItm_input_14",  # 회사채(무보증3년)AA-
    "chkAnnItm_input_10",  # 통안증권(1년)
    "chkAnnItm_input_11",  # 통안증권(2년)
    "chkAnnItm_input_2",   # 국고채권(3년)
]


class BondSummary:
    """
    KOFIA 최종호가수익률 전종목 수집 (5년치).

    18개 시리즈를 6개씩 3배치로 나눠 수집 후 Date 기준 merge.
    배치: A(국고채 1~20년) / B(국고채 30·50년 + 통안증권) / C(한전채·산금채·회사채·CD·CP)
    출력 파일: data/raw/YYYYMMDD/bond_summary.xlsx
              (임시: bond_summary_A/B/C.xls → 병합 후 삭제)
    """

    def __init__(self, download_dir: str | None = None):
        if download_dir is None:
            self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "raw"))
        else:
            self.download_dir = os.path.abspath(download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

    def collect(self, target_date=None, headless: bool = True) -> bool:
        """
        3배치 수집 후 병합하여 bond_summary.xlsx 저장.

        Args:
            target_date: "YYYYMMDD" 문자열 또는 datetime (없으면 오늘)
            headless   : True이면 브라우저 창 없이 실행

        Returns:
            True on success, False on failure.
        """
        from datetime import timedelta

        if not target_date:
            target_date = datetime.now()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y%m%d")

        end_str = target_date.strftime("%Y-%m-%d")
        try:
            start_dt = target_date.replace(year=target_date.year - 5)
        except ValueError:
            start_dt = target_date - timedelta(days=365 * 5)
        start_str = start_dt.strftime("%Y-%m-%d")
        print(f"  기간: {start_str} ~ {end_str}")

        date_str       = target_date.strftime("%Y%m%d")
        daily_save_dir = os.path.join(self.download_dir, date_str)
        os.makedirs(daily_save_dir, exist_ok=True)

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=_build_options(headless, daily_save_dir),
        )
        wait = WebDriverWait(driver, 30)

        try:
            _navigate_to_period_tab(driver, wait)
            _set_date_range(driver, wait, start_str, end_str)

            # 초기 해제
            for cid in _BOND_SUMMARY_INIT_UNCHECK:
                _set_checkbox(driver, cid, False)
            time.sleep(0.5)

            batch_files: list[tuple[str, str]] = []

            for batch in _BOND_SUMMARY_BATCHES:
                bname = batch["name"]
                bids  = batch["ids"]
                print(f"  [배치 {bname}] 수집 시작...")

                for cid in bids:
                    _set_checkbox(driver, cid, True)
                time.sleep(0.5)

                _safe_click(driver, wait, By.ID, "image4")
                time.sleep(5)
                _safe_click(driver, wait, By.ID, "imgExcel")
                time.sleep(5)

                dl = _wait_for_download(daily_save_dir, os.getcwd())
                if dl:
                    dest = os.path.join(daily_save_dir, f"bond_summary_{bname}.xls")
                    if os.path.exists(dest):
                        os.remove(dest)
                    os.rename(dl, dest)
                    batch_files.append((bname, dest))
                    print(f"  [배치 {bname}] 완료 → {os.path.basename(dest)}")
                else:
                    print(f"  [배치 {bname}] 다운로드 실패 — 건너뜀")

                for cid in bids:
                    _set_checkbox(driver, cid, False)
                time.sleep(0.5)

            if not batch_files:
                print("  [실패] 다운로드된 파일 없음")
                return False

            # 병합
            dfs: list[pd.DataFrame] = []
            for bname, path in batch_files:
                df = _parse_kofia_xls(path)
                if df is not None:
                    dfs.append(df)
                    print(f"  [배치 {bname}] {len(df)}행, {len(df.columns) - 1}열 파싱 완료")

            if not dfs:
                print("  [실패] 파싱 가능한 파일 없음")
                return False

            merged = dfs[0]
            for df in dfs[1:]:
                merged = merged.merge(df, on="Date", how="outer")
            merged = merged.sort_values("Date", ascending=True).reset_index(drop=True)

            final = os.path.join(daily_save_dir, "bond_summary.xlsx")
            if os.path.exists(final):
                os.remove(final)
            merged.to_excel(final, index=False, engine="openpyxl")
            print(f"  [완료] 병합 완료: {final}  ({len(merged)}행, {len(merged.columns)}열)")

            for _, path in batch_files:
                try:
                    os.remove(path)
                except Exception:
                    pass

            return True

        except Exception as e:
            print(f"  [Selenium 오류] {e}")
            try:
                with open(os.path.join(self.download_dir, "selenium_error_bond_summary.html"), "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except Exception:
                pass
            return False
        finally:
            driver.quit()

    def load(self, target_date) -> pd.DataFrame | None:
        """
        저장된 bond_summary.xlsx 를 읽어 DataFrame으로 반환.

        Returns:
            pd.DataFrame, 실패 시 None.
        """
        date_str  = target_date.strftime("%Y%m%d") if isinstance(target_date, datetime) else str(target_date)
        file_path = os.path.join(self.download_dir, date_str, "bond_summary.xlsx")

        if not os.path.exists(file_path):
            print(f"  [파일 없음] {file_path}")
            return None
        try:
            return pd.read_excel(file_path, engine="openpyxl")
        except Exception as e:
            print(f"  [읽기 오류] {e}")
            return None


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date, timedelta

    _target    = date.today() - timedelta(days=1)
    target_str = _target.strftime("%Y%m%d")

    print(f"=== TreasurySummary | 기준일: {target_str} ===")
    ts = TreasurySummary()
    if ts.collect(target_date=target_str, headless=True):
        df = ts.load(target_str)
        if df is not None:
            print(df.tail())

    print()
    print(f"=== BondSummary | 기준일: {target_str} ===")
    bs = BondSummary()
    if bs.collect(target_date=target_str, headless=True):
        df = bs.load(target_str)
        if df is not None:
            print(df.tail())
            print(f"컬럼: {df.columns.tolist()}")
