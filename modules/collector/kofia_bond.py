import os
import sys
import time
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

# standalone 실행 시 프로젝트 루트를 sys.path에 추가
_root = Path(__file__).resolve().parents[2]
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
    Provides two methods:
    1. Selenium-based: Simulates browser interaction (supports Headless/UI modes).
    2. Requests-based: Direct API calls (no UI, lightweight).
    """
    
    BASE_URL = "https://www.kofiabond.or.kr/webservice/common/baseNet.do"
    
    def __init__(self, download_dir=None):
        self.url = "https://www.kofiabond.or.kr/index.html"
        
        # 기본 다운로드 경로 설정
        if download_dir is None:
            # 1. 로컬 개발 환경: 프로젝트 내 data/raw
            local_path = os.path.abspath(os.path.join(os.getcwd(), "data", "raw"))
            
            # 2. 쓰기 권한 확인 (Streamlit Cloud 대응)
            if os.access(os.getcwd(), os.W_OK):
                self.download_dir = local_path
            else:
                # 쓰기 권한 없으면 임시 디렉토리 사용 (/tmp 등)
                import tempfile
                self.download_dir = os.path.join(tempfile.gettempdir(), "mat_kofia_data")
        else:
            self.download_dir = os.path.abspath(download_dir)
            
        if not os.path.exists(self.download_dir):
            try:
                os.makedirs(self.download_dir, exist_ok=True)
            except OSError:
                # 권한 문제 등으로 실패 시 임시 디렉토리로 우회
                import tempfile
                self.download_dir = os.path.join(tempfile.gettempdir(), "mat_kofia_data")
                os.makedirs(self.download_dir, exist_ok=True)

    def _get_selenium_options(self, headless=True, download_path=None):
        options = Options()
        if headless:
            options.add_argument("--headless")
            options.add_argument("--headless=new")
        # Browser Options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # Cloud/Server 환경에서 필수적인 옵션들 추가
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # 엑셀 다운로드 자동화 설정
        target_dir = download_path if download_path else self.download_dir
        prefs = {
            "download.default_directory": target_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)
        return options

    def Treasury_Collector_Selenium(self, target_date=None, headless=True):
        """
        [方式 1] Selenium을 이용한 UI 조작 방식 (Headless 지원)
        지정한 날짜를 기준으로 최근 1년간의 데이터를 조회하여 엑셀로 다운로드합니다.
        """
        from datetime import timedelta
        if not target_date:
            target_date = datetime.now()
        else:
            if isinstance(target_date, str):
                target_date = datetime.strptime(target_date, "%Y%m%d")
        
        # 날짜 계산 (종료일: target_date, 시작일: 1년 전)
        end_date_str = target_date.strftime("%Y-%m-%d")
        try:
            # 윤년 고려한 1년 전 계산
            start_date = target_date.replace(year=target_date.year - 1)
        except ValueError: # 2월 29일인 경우
            start_date = target_date - timedelta(days=365)
        start_date_str = start_date.strftime("%Y-%m-%d")

        # 날짜별 폴더 생성 (예: data/raw/20260123)
        date_str = target_date.strftime("%Y%m%d")
        daily_save_dir = os.path.join(self.download_dir, date_str)
        if not os.path.exists(daily_save_dir):
            os.makedirs(daily_save_dir)

        options = self._get_selenium_options(headless=headless, download_path=daily_save_dir)
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 30)
        
        def safe_click(by, value):
            """요소를 찾아 대기 후 자바스크립트로 클릭 수행"""
            try:
                element = wait.until(EC.presence_of_element_located((by, value)))
                driver.execute_script("arguments[0].click();", element)
                # print(f"Clicked element: {value}")
            except Exception as e:
                print(f"Failed to click {value}: {e}")
                raise e

        try:
            # print(f"Connecting to {self.url}...")
            driver.get(self.url)
            time.sleep(5) # 웹스퀘어 초기 엔진 로딩 대기
            
            # 1. Switch directly to main frame
            driver.switch_to.frame("fraAMAKMain")
            
            # 2. Navigate to menu
            safe_click(By.ID, "genLv1_0_imgLv1")
            time.sleep(1)
            safe_click(By.ID, "genLv1_0_genLv2_0_txtLv2")
            time.sleep(3)
            
            # 3. Switch to content frame
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "maincontent")))
            
            # 4. Click period tab
            safe_click(By.ID, "tabContents1_tab_tabs2")
            time.sleep(3)
            
            # 5. Switch to data frame
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "tabContents1_contents_tabs2_body")))
            
            # 6. Set Date Range
            start_input = wait.until(EC.presence_of_element_located((By.ID, "startDtDD_input")))
            end_input = wait.until(EC.presence_of_element_located((By.ID, "endDtDD_input")))
            
            driver.execute_script("arguments[0].value = '';", start_input)
            start_input.send_keys(start_date_str)
            driver.execute_script("arguments[0].value = '';", end_input)
            end_input.send_keys(end_date_str)
            time.sleep(1)

            
            # 7. Adjust Checkboxes
            # Uncheck: TongAn(1,2yr), CorpBond, CD(91d)
            uncheck_ids = ["chkAnnItm_input_10", "chkAnnItm_input_11", "chkAnnItm_input_14", "chkAnnItm_input_16"]
            # Check: Treasury(2, 3, 10, 20, 30yr)
            check_ids = ["chkAnnItm_input_1", "chkAnnItm_input_2", "chkAnnItm_input_4", "chkAnnItm_input_5", "chkAnnItm_input_6"]

            for cid in uncheck_ids:
                try:
                    cb = driver.find_element(By.ID, cid)
                    if cb.is_selected():
                        driver.execute_script("arguments[0].click();", cb)
                        # print(f"Unchecked {cid}")
                except: pass
            
            for cid in check_ids:
                try:
                    cb = driver.find_element(By.ID, cid)
                    if not cb.is_selected():
                        driver.execute_script("arguments[0].click();", cb)
                        # print(f"Checked {cid}")
                except: pass
            time.sleep(1)

            # 8. Click Search
            safe_click(By.ID, "image4")
            time.sleep(5) # 데이터 로딩 대기
            
            # 9. Download Excel
            safe_click(By.ID, "imgExcel")
            time.sleep(5) # 다운로드 프로세스 대기
            
            # 10. Wait for download
            target_filename = "최종호가 수익률.xls"
            max_wait = 30
            downloaded_file = None
            
            for _ in range(max_wait):
                # 1. 대상 디렉토리 체크 (daily_save_dir)
                path1 = os.path.join(daily_save_dir, target_filename)
                # 2. 현재 작업 디렉토리 체크
                path2 = os.path.join(os.getcwd(), target_filename)
                # 3. data/raw 디렉토리 체크
                path3 = os.path.join(os.getcwd(), "data", "raw", target_filename)
                
                for p in [path1, path2, path3]:
                    if os.path.exists(p):
                        downloaded_file = p
                        break
                if downloaded_file: break
                time.sleep(1)
            
            if downloaded_file:
                # 최종 위치로 이동 (data/raw/YYYYMMDD/kofia_bond_yield.xlsx)
                # .xls는 엔진 문제와 호환성 문제가 많으므로 .xlsx로 전환
                final_path = os.path.join(daily_save_dir, "kofia_bond_yield.xlsx")
                if os.path.exists(final_path): os.remove(final_path)
                
                # 11. Process and Sort Data
                try:
                    # KOFIA 엑셀(사실상 HTML) 읽기
                    try:
                        # lxml 엔진을 사용하여 HTML 테이블 추출
                        dfs = pd.read_html(downloaded_file, flavor='lxml')
                        df = dfs[0]
                    except Exception:
                        # 실패 시 일반 엑셀(xls) 시도
                        df = pd.read_excel(downloaded_file)
                    
                    # Clean & Format Data
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = ['_'.join([str(c) for c in col]).strip() for col in df.columns.values]
                    
                    # Get Date Column
                    date_col = None
                    for col in df.columns:
                        if '일자' in str(col) or 'Date' in str(col):
                            date_col = col
                            break
                    
                    if date_col:
                        # Filter invalid rows
                        df = df[~df[date_col].astype(str).str.contains('최고|최저|Average|Max|Min', na=False)]
                        
                        # Date Conversion
                        df[date_col] = pd.to_datetime(df[date_col].astype(str).str.replace(r'[^0-9-]', '', regex=True), errors='coerce')
                        df = df.dropna(subset=[date_col])
                        
                        # Sort Data
                        df[date_col] = df[date_col].dt.date
                        df = df.sort_values(by=date_col, ascending=True)
                        
                        # Save as xlsx
                        df.to_excel(final_path, index=False, engine='openpyxl')
                        print(f"  - 데이터 정렬 및 변환 완료: {date_col} 기준 오름차순 (xlsx 저장)")
                        
                        # 정렬 및 저장이 성공했으므로 원본 .xls 파일 삭제
                        if os.path.exists(downloaded_file):
                            os.remove(downloaded_file)
                            # print(f"  - 원본 임시 파일 삭제 완료: {downloaded_file}")
                    else:
                        # 날짜 컬럼을 못 찾은 경우 단순 이동이라도 수행
                        os.rename(downloaded_file, os.path.join(daily_save_dir, "kofia_bond_yield.xls"))
                        print("  - [경고] 날짜 컬럼을 찾지 못해 정렬 없이 파일명만 변경했습니다.")
                        
                except Exception as e:
                    print(f"  - 정렬 작업 중 오류 발생: {e}")
                    # 오류 발생 시 최소한 파일 이동이라도 시도
                    try:
                        temp_final = os.path.join(daily_save_dir, "kofia_bond_yield_error.xls")
                        os.rename(downloaded_file, temp_final)
                    except: pass

                print(f"[수집 및 정렬 완료]")
                print(f"  - 기간: {start_date_str} ~ {end_date_str}")
                print(f"  - 최종 파일: {final_path}")
                return True
            else:
                print("Error: Downloaded file not found.")
                return False
                
        except Exception as e:
            print(f"Selenium Error: {e}")
            debug_path = os.path.join(self.download_dir, "selenium_error_step.html")
            try:
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"Error source saved to: {debug_path}")
            except: pass
            return False
        finally:
            driver.quit()
            # 임시 디버그 파일들 정리
            for f in os.listdir(os.getcwd()):
                if f.startswith("debug_") and f.endswith(".html"):
                    try: os.remove(f)
                    except: pass

 

    def load_excel(self, target_date) -> pd.DataFrame | None:
        """
        Read a previously downloaded KOFIA bond yield Excel file and return as DataFrame.

        Args:
            target_date (str | datetime): "YYYYMMDD" string or datetime object

        Returns:
            pd.DataFrame on success, None if file not found or unreadable.
        """
        if isinstance(target_date, datetime):
            date_str = target_date.strftime("%Y%m%d")
        else:
            date_str = str(target_date)

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
    collector = KofiaBondCollector()
    print("--- 1. Selenium (Headless) 실행 ---")
    if collector.Treasury_Collector_Selenium(target_date="20260218", headless=True):
        print("Selenium 성공: 파일이 data/raw에 저장되었습니다.")
        df = collector.load_excel("20260218")
        if df is not None:
            print(df.tail())
    else:
        print("Selenium 방식 실패 또는 데이터 없음.")