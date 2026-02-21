import os
import sys
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

# standalone 실행 시 프로젝트 루트를 sys.path에 추가
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from modules.utils import standardize_kofia  # noqa: E402
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


class KofiaBondCollector:
    """
    KOFIA (Korea Financial Investment Association) Bond Data Collector.
    로컬 환경에서 Selenium으로 KOFIA 사이트를 자동화하여 국채 금리를 수집합니다.
    수집 후 data/raw/YYYYMMDD/kofia_bond_yield.xlsx 에 저장합니다.
    """

    def __init__(self, download_dir=None):
        self.url = "https://www.kofiabond.or.kr/index.html"
        if download_dir is None:
            self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "raw"))
        else:
            self.download_dir = os.path.abspath(download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

    def _get_selenium_options(self, headless=True, download_path=None):
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")

        target_dir = download_path if download_path else self.download_dir
        prefs = {
            "download.default_directory": target_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)
        return options

    def Treasury_Collector_Selenium(self, target_date=None, headless=True):
        """
        지정한 날짜를 기준으로 최근 1년간의 국채 금리를 조회하여 xlsx로 저장합니다.

        Args:
            target_date: "YYYYMMDD" 문자열 또는 datetime 객체 (없으면 오늘)
            headless   : True이면 브라우저 창 없이 실행

        Returns:
            True on success, False on failure.
        """
        from datetime import timedelta
        if not target_date:
            target_date = datetime.now()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y%m%d")

        end_date_str = target_date.strftime("%Y-%m-%d")
        try:
            start_date = target_date.replace(year=target_date.year - 1)
        except ValueError:  # 2월 29일인 경우
            start_date = target_date - timedelta(days=365)
        start_date_str = start_date.strftime("%Y-%m-%d")

        date_str = target_date.strftime("%Y%m%d")
        daily_save_dir = os.path.join(self.download_dir, date_str)
        os.makedirs(daily_save_dir, exist_ok=True)

        options = self._get_selenium_options(headless=headless, download_path=daily_save_dir)
        service = Service(ChromeDriverManager().install())
        driver  = webdriver.Chrome(service=service, options=options)
        wait    = WebDriverWait(driver, 30)

        def safe_click(by, value):
            element = wait.until(EC.presence_of_element_located((by, value)))
            driver.execute_script("arguments[0].click();", element)

        try:
            driver.get(self.url)
            time.sleep(5)  # 웹스퀘어 초기 엔진 로딩 대기

            driver.switch_to.frame("fraAMAKMain")
            safe_click(By.ID, "genLv1_0_imgLv1")
            time.sleep(1)
            safe_click(By.ID, "genLv1_0_genLv2_0_txtLv2")
            time.sleep(3)

            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "maincontent")))
            safe_click(By.ID, "tabContents1_tab_tabs2")
            time.sleep(3)

            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "tabContents1_contents_tabs2_body")))

            start_input = wait.until(EC.presence_of_element_located((By.ID, "startDtDD_input")))
            end_input   = wait.until(EC.presence_of_element_located((By.ID, "endDtDD_input")))
            driver.execute_script("arguments[0].value = '';", start_input)
            start_input.send_keys(start_date_str)
            driver.execute_script("arguments[0].value = '';", end_input)
            end_input.send_keys(end_date_str)
            time.sleep(1)

            # Uncheck: TongAn(1,2yr), CorpBond, CD(91d)
            for cid in ["chkAnnItm_input_10", "chkAnnItm_input_11", "chkAnnItm_input_14", "chkAnnItm_input_16"]:
                try:
                    cb = driver.find_element(By.ID, cid)
                    if cb.is_selected():
                        driver.execute_script("arguments[0].click();", cb)
                except: pass

            # Check: KTB 2/3/10/20/30yr
            for cid in ["chkAnnItm_input_1", "chkAnnItm_input_2", "chkAnnItm_input_4", "chkAnnItm_input_5", "chkAnnItm_input_6"]:
                try:
                    cb = driver.find_element(By.ID, cid)
                    if not cb.is_selected():
                        driver.execute_script("arguments[0].click();", cb)
                except: pass
            time.sleep(1)

            safe_click(By.ID, "image4")
            time.sleep(5)
            safe_click(By.ID, "imgExcel")
            time.sleep(5)

            # 다운로드 파일 탐색
            target_filename = "최종호가 수익률.xls"
            downloaded_file = None
            for _ in range(30):
                for p in [
                    os.path.join(daily_save_dir, target_filename),
                    os.path.join(os.getcwd(), target_filename),
                    os.path.join(os.getcwd(), "data", "raw", target_filename),
                ]:
                    if os.path.exists(p):
                        downloaded_file = p
                        break
                if downloaded_file:
                    break
                time.sleep(1)

            if not downloaded_file:
                print("Error: Downloaded file not found.")
                return False

            final_path = os.path.join(daily_save_dir, "kofia_bond_yield.xlsx")
            if os.path.exists(final_path):
                os.remove(final_path)

            try:
                try:
                    dfs = pd.read_html(downloaded_file, flavor="lxml")
                    df  = dfs[0]
                except Exception:
                    df = pd.read_excel(downloaded_file)

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ["_".join(str(c) for c in col).strip() for col in df.columns]

                date_col = next((c for c in df.columns if "일자" in str(c) or "Date" in str(c)), None)

                if date_col:
                    df = df[~df[date_col].astype(str).str.contains("최고|최저|Average|Max|Min", na=False)]
                    df[date_col] = pd.to_datetime(
                        df[date_col].astype(str).str.replace(r"[^0-9-]", "", regex=True), errors="coerce"
                    )
                    df = df.dropna(subset=[date_col])
                    df[date_col] = df[date_col].dt.date
                    df = df.sort_values(date_col, ascending=True)
                    df.to_excel(final_path, index=False, engine="openpyxl")
                    print(f"  - 정렬 완료: {date_col} 기준 오름차순")
                    if os.path.exists(downloaded_file):
                        os.remove(downloaded_file)
                else:
                    os.rename(downloaded_file, os.path.join(daily_save_dir, "kofia_bond_yield.xls"))
                    print("  - [경고] 날짜 컬럼 미발견 — 파일명만 변경")

            except Exception as e:
                print(f"  - 처리 오류: {e}")
                try:
                    os.rename(downloaded_file, os.path.join(daily_save_dir, "kofia_bond_yield_error.xls"))
                except: pass

            print(f"[완료] 기간: {start_date_str} ~ {end_date_str}  파일: {final_path}")
            return True

        except Exception as e:
            print(f"Selenium Error: {e}")
            try:
                debug_path = os.path.join(self.download_dir, "selenium_error_step.html")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"Error source saved to: {debug_path}")
            except: pass
            return False
        finally:
            driver.quit()
            for f in os.listdir(os.getcwd()):
                if f.startswith("debug_") and f.endswith(".html"):
                    try: os.remove(f)
                    except: pass

    def load_excel(self, target_date) -> pd.DataFrame | None:
        """
        저장된 KOFIA xlsx 파일을 읽어 DataFrame으로 반환합니다.

        Args:
            target_date: "YYYYMMDD" 문자열 또는 datetime 객체

        Returns:
            표준화된 pd.DataFrame (KR_2Y … KR_30Y), 실패 시 None.
        """
        date_str  = target_date.strftime("%Y%m%d") if isinstance(target_date, datetime) else str(target_date)
        file_path = os.path.join(self.download_dir, date_str, "kofia_bond_yield.xlsx")

        if not os.path.exists(file_path):
            print(f"[KOFIA] 파일 없음: {file_path}")
            return None
        try:
            df = pd.read_excel(file_path, engine="openpyxl")
            return standardize_kofia(df)
        except Exception as e:
            print(f"[KOFIA] 파일 읽기 오류: {e}")
            return None


if __name__ == "__main__":
    from datetime import date, timedelta

    _target    = date.today() - timedelta(days=1)
    target_str = _target.strftime("%Y%m%d")

    collector = KofiaBondCollector()
    print(f"--- KOFIA Selenium (Headless) | 기준일: {target_str} ---")
    if collector.Treasury_Collector_Selenium(target_date=target_str, headless=True):
        print(f"성공: data/raw/{target_str}/kofia_bond_yield.xlsx")
        df = collector.load_excel(target_str)
        if df is not None:
            print(df.tail())
    else:
        print("실패.")
