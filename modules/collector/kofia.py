"""
KOFIA 데이터 수집기

TreasurySummary : 주요 만기 국채 금리 — 기간별 탭, 5개 시리즈
BondSummary     : 전종목 최종호가수익률 — 18개 시리즈, 3배치 수집 후 병합

공통 흐름:
  default_content
    → frame "fraAMAKMain"  (메뉴 클릭)
    → frame "maincontent"  (기간별 탭 클릭)
    → frame "tabContents1_contents_tabs2_body"  (날짜·체크박스 조작)

collect() 는 파일을 저장하지 않고 DataFrame을 반환합니다.
저장·병합은 collect_data.py 에서 처리합니다.
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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ─── 공통 Selenium 헬퍼 ───────────────────────────────────────────────────────

_KOFIA_URL     = "https://www.kofiabond.or.kr/index.html"
_KOFIA_DL_FILE = "최종호가 수익률.xls"


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


def _force_click_checkbox(driver, cid: str):
    """is_selected() 없이 체크박스를 직접 클릭합니다.
    WebSquare 커스텀 체크박스는 is_selected()가 항상 False를 반환하므로
    상태 조회 없이 caller가 상태를 추적하여 호출해야 합니다."""
    try:
        cb = driver.find_element(By.ID, cid)
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
            os.path.join(cwd, "data", _KOFIA_DL_FILE),
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
    KOFIA 주요 만기 국채 금리 수집.

    수집 대상: 국고채 2/3/10/20/30년
    반환: Date 컬럼 + 금리 컬럼들의 DataFrame (저장은 collect_data.py 에서 처리)
    """

    _UNCHECK = ["chkAnnItm_input_10", "chkAnnItm_input_11",
                "chkAnnItm_input_14", "chkAnnItm_input_16"]
    _CHECK   = ["chkAnnItm_input_1", "chkAnnItm_input_2",
                "chkAnnItm_input_4", "chkAnnItm_input_5", "chkAnnItm_input_6"]

    def __init__(self, download_dir: str | None = None):
        if download_dir is None:
            self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "data"))
        else:
            self.download_dir = os.path.abspath(download_dir)
        self._tmp_dir = os.path.join(self.download_dir, "tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)

    def collect(self, start_date: str, end_date: str, headless: bool = True) -> pd.DataFrame | None:
        """
        Selenium으로 KOFIA 기간별 탭을 조작하여 국채 금리 데이터를 수집합니다.

        Args:
            start_date: "YYYY-MM-DD"
            end_date  : "YYYY-MM-DD"
            headless  : True이면 브라우저 창 없이 실행

        Returns:
            Date 컬럼을 포함한 DataFrame. 실패 시 None.
        """
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=_build_options(headless, self._tmp_dir),
        )
        wait = WebDriverWait(driver, 30)

        try:
            _navigate_to_period_tab(driver, wait)
            _set_date_range(driver, wait, start_date, end_date)

            # 기본 체크 해제: 페이지 기본값으로 체크된 항목을 직접 클릭해서 해제
            for cid in self._UNCHECK:
                _force_click_checkbox(driver, cid)
            # 수집 대상 체크: 현재 모두 해제된 상태이므로 직접 클릭해서 체크
            for cid in self._CHECK:
                _force_click_checkbox(driver, cid)
            time.sleep(1)

            _safe_click(driver, wait, By.ID, "image4")
            time.sleep(5)
            _safe_click(driver, wait, By.ID, "imgExcel")
            time.sleep(5)

            dl = _wait_for_download(self._tmp_dir, os.getcwd())
            if not dl:
                print("  [오류] 다운로드 파일 미발견")
                return None

            df = _parse_kofia_xls(dl)
            try:
                os.remove(dl)
            except Exception:
                pass

            if df is None or "Date" not in df.columns:
                print("  [경고] 날짜 컬럼 미발견")
                return None

            df = df.sort_values("Date", ascending=True).reset_index(drop=True)
            print(f"  [완료] {len(df)}행")
            return df

        except Exception as e:
            print(f"  [Selenium 오류] {e}")
            try:
                with open(os.path.join(self.download_dir, "selenium_error_treasury.html"), "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except Exception:
                pass
            return None
        finally:
            driver.quit()


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

# 페이지 기본 체크 항목 (TreasurySummary._UNCHECK 와 동일)
# 국고채권(3년)/item_2 는 기본 미체크 상태이므로 여기 포함하지 않음
_BOND_SUMMARY_INIT_UNCHECK = [
    "chkAnnItm_input_10",  # 통안증권(1년)
    "chkAnnItm_input_11",  # 통안증권(2년)
    "chkAnnItm_input_14",  # 회사채(무보증3년)AA-
    "chkAnnItm_input_16",  # CD수익률(91일)
]


class BondSummary:
    """
    KOFIA 최종호가수익률 전종목 수집.

    18개 시리즈를 6개씩 3배치로 나눠 수집 후 Date 기준 merge.
    배치: A(국고채 1~20년) / B(국고채 30·50년 + 통안증권) / C(한전채·산금채·회사채·CD·CP)
    반환: Date 컬럼 + 18개 시리즈 컬럼들의 DataFrame (저장은 collect_data.py 에서 처리)
    """

    def __init__(self, download_dir: str | None = None):
        if download_dir is None:
            self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "data"))
        else:
            self.download_dir = os.path.abspath(download_dir)
        self._tmp_dir = os.path.join(self.download_dir, "tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)

    def collect(self, start_date: str, end_date: str, headless: bool = True) -> pd.DataFrame | None:
        """
        배치(A/B/C)마다 독립 Chrome 세션으로 수집 후 병합하여 반환합니다.

        배치당 독립 세션을 사용하는 이유:
          - 엑셀 다운로드 후 WebSquare가 내부 상태를 리셋할 수 있어,
            단일 세션에서 배치 간 체크박스 상태가 오염될 수 있음
          - 독립 세션은 항상 알려진 초기 상태(기본 체크 항목 고정)에서 시작

        Args:
            start_date: "YYYY-MM-DD"
            end_date  : "YYYY-MM-DD"
            headless  : True이면 브라우저 창 없이 실행

        Returns:
            Date 컬럼을 포함한 병합 DataFrame. 실패 시 None.
        """
        print(f"  기간: {start_date} ~ {end_date}")

        chromedriver_path = ChromeDriverManager().install()
        batch_files: list[tuple[str, str]] = []

        for batch in _BOND_SUMMARY_BATCHES:
            bname = batch["name"]
            bids  = batch["ids"]
            print(f"  [배치 {bname}] 수집 시작...")

            driver = webdriver.Chrome(
                service=Service(chromedriver_path),
                options=_build_options(headless, self._tmp_dir),
            )
            wait = WebDriverWait(driver, 30)

            try:
                _navigate_to_period_tab(driver, wait)
                _set_date_range(driver, wait, start_date, end_date)

                # 페이지 기본 체크 항목 해제 (신규 세션이므로 항상 알려진 초기 상태)
                for cid in _BOND_SUMMARY_INIT_UNCHECK:
                    _force_click_checkbox(driver, cid)
                time.sleep(0.3)

                # 이 배치만 체크
                for cid in bids:
                    _force_click_checkbox(driver, cid)
                time.sleep(0.5)

                _safe_click(driver, wait, By.ID, "image4")
                time.sleep(5)
                _safe_click(driver, wait, By.ID, "imgExcel")
                time.sleep(5)

                dl = _wait_for_download(self._tmp_dir, os.getcwd())
                if dl:
                    dest = os.path.join(self._tmp_dir, f"bond_summary_{bname}.xls")
                    if os.path.exists(dest):
                        os.remove(dest)
                    os.rename(dl, dest)
                    batch_files.append((bname, dest))
                    print(f"  [배치 {bname}] 완료 → {os.path.basename(dest)}")
                else:
                    print(f"  [배치 {bname}] 다운로드 실패 — 건너뜀")

            except Exception as e:
                print(f"  [배치 {bname}] Selenium 오류: {e}")
                try:
                    with open(
                        os.path.join(self.download_dir, f"selenium_error_bond_{bname}.html"),
                        "w", encoding="utf-8",
                    ) as f:
                        f.write(driver.page_source)
                except Exception:
                    pass
            finally:
                driver.quit()

        if not batch_files:
            print("  [실패] 다운로드된 파일 없음")
            return None

        dfs: list[pd.DataFrame] = []
        for bname, path in batch_files:
            df = _parse_kofia_xls(path)
            if df is not None:
                dfs.append(df)
                print(f"  [배치 {bname}] {len(df)}행, {len(df.columns) - 1}열 파싱 완료")

        for _, path in batch_files:
            try:
                os.remove(path)
            except Exception:
                pass

        if not dfs:
            print("  [실패] 파싱 가능한 파일 없음")
            return None

        # Date를 인덱스로 설정 후 axis=1 방향으로 concat (outer join → 날짜 범위 통일)
        dfs_indexed = [df.set_index("Date") for df in dfs]
        merged_idx = pd.concat(dfs_indexed, axis=1)

        # 동일 컬럼명이 여러 배치에 중복된 경우(KOFIA XLS가 전종목 헤더를 포함할 때)
        # → 각 컬럼별 첫 번째 non-NaN 값으로 결합
        if merged_idx.columns.duplicated().any():
            unique_cols = list(dict.fromkeys(merged_idx.columns))
            deduped: dict[str, pd.Series] = {}
            for col in unique_cols:
                sub = merged_idx.loc[:, merged_idx.columns == col]
                if sub.shape[1] > 1:
                    combined = sub.iloc[:, 0]
                    for i in range(1, sub.shape[1]):
                        combined = combined.combine_first(sub.iloc[:, i])
                    deduped[col] = combined
                else:
                    deduped[col] = sub.iloc[:, 0]
            merged_idx = pd.DataFrame(deduped, index=merged_idx.index)

        merged = merged_idx.reset_index()
        merged = merged.sort_values("Date", ascending=True).reset_index(drop=True)
        print(f"  [완료] 병합 완료  ({len(merged)}행, {len(merged.columns)}열)")
        return merged


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import date, timedelta
    from modules.calculator.kofia import KofiaCalc

    _end = date.today() - timedelta(days=1)
    try:
        _start_1y = _end.replace(year=_end.year - 1)
    except ValueError:
        _start_1y = _end - timedelta(days=365)
    try:
        _start_5y = _end.replace(year=_end.year - 5)
    except ValueError:
        _start_5y = _end - timedelta(days=365 * 5)

    print(f"=== TreasurySummary | {_start_1y} ~ {_end} ===")
    ts = TreasurySummary()
    df = ts.collect(start_date=str(_start_1y), end_date=str(_end))
    if df is not None:
        print(KofiaCalc.standardize(df).tail())

    print()
    print(f"=== BondSummary | {_start_5y} ~ {_end} ===")
    bs = BondSummary()
    df = bs.collect(start_date=str(_start_5y), end_date=str(_end))
    if df is not None:
        print(df.tail())
        print(f"컬럼: {df.columns.tolist()}")
