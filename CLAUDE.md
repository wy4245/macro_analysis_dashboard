# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean macro financial data automation tool (MAT). Collects bond yield data from multiple sources, saves as dated Excel files, and visualises them in a Streamlit dashboard for use with Excel macros.

## Environment Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## Running the Tool

```bash
# Launch the Streamlit dashboard
streamlit run main.py

# Run individual collectors standalone (each has its own __main__ block for development)
python modules/collector/kofia.py
python modules/collector/investing.py

# Collect data that cannot run on the server (investing.com) and push to git
python collect_data.py

# Debug KOFIA website frame structure (opens visible browser window)
python modules/debug_frames.py
```

## Architecture

### Data Flow

- **모든 데이터는 로컬에서 `collect_data.py`로 수집** → git push → Streamlit 서버 자동 반영
- `main.py`는 저장된 파일만 읽어서 표시 (수집 기능 없음)
- During development, each collector can be run standalone via its `if __name__ == "__main__"` block.
- Dates are hardcoded in each collector's `__main__` block (not passed via CLI).

### Adding a New Data Source

1. Determine if the source can run on the server or requires local execution:
   - **Server-runnable** (requests, Selenium with system chromium): Add a collection button to the `st.sidebar` in `main.py`
   - **Local-only** (Cloudflare bypass, Playwright): Add to `collect_data.py`
2. Create `modules/collector/<source_name>/<data_name>.py` with a class exposing a method returning `pd.DataFrame | None`
3. In `main.py`, add a new tab name to the `st.tabs([...])` list and a `with tab_<name>:` block

### Module Structure

```
modules/
  collector/
    kofia.py      # TreasurySummary, BondSummary — KOFIA 국채 (Selenium)
    investing.py  # GlobalTreasury — 글로벌 국채 (Playwright)
  calculator/
    kofia.py           # KofiaCalc — standardize(), fill_calendar()
    global_treasury.py # TreasuryCalc — fill_calendar(), merge(), build_change_summary()
  debug_frames.py  # iframe 구조 확인용 (headless 비활성 상태로 실행)
```

### Collectors

**`TreasurySummary`** (`modules/collector/kofia.py`)
- Selenium-based; navigates the KOFIA WebSquare site
- `collect(start_date, end_date, headless=True) -> pd.DataFrame | None` — Date 컬럼 포함 raw DataFrame 반환
- 파일 저장 없음; 저장·병합은 `collect_data.py` 에서 처리
- `KofiaCalc.standardize()` 적용 후 `data/treasury_summary.csv` 에 증분 저장됨
- KOFIA `.xls` downloads are HTML tables: parse with `pd.read_html(flavor='lxml')`, fall back to `pd.read_excel()`
- Selenium 임시 다운로드 위치: `data/tmp/` (자동 정리)

**`BondSummary`** (`modules/collector/kofia.py`)
- 18개 시리즈를 6개씩 3배치(A/B/C)로 수집 후 Date 기준 merge
- `collect(start_date, end_date, headless=True) -> pd.DataFrame | None`
- `data/bond_summary.csv` 에 증분 저장됨

KOFIA iframe navigation sequence:
```
default_content → fraAMAKMain → (menu click) → maincontent → tabContents1_contents_tabs2_body
```
Menu IDs: `genLv1_0_imgLv1` → `genLv1_0_genLv2_0_txtLv2`; period tab: `tabContents1_tab_tabs2`; search: `image4`; download: `imgExcel`

Bond checkbox IDs — uncheck: `chkAnnItm_input_10/11/14/16`; check (KTB 2/3/10/20/30yr): `chkAnnItm_input_1/2/4/5/6`

**`GlobalTreasury`** (`modules/collector/investing.py`)
- Uses `playwright` Chromium headless (Cloudflare bypass) + investing.com scraping
- Downloads US, DE, GB, JP, CN treasury yields; 30 maturities
- Wide format, columns: `{CC}_{n}Y` (e.g. `US_10Y`, `DE_2Y`)
- `collect(start_date, end_date) -> pd.DataFrame | None` — returns data directly (no disk write)
- `data/global_treasury.csv` 에 증분 저장됨
- 첫 실행 전 Chromium 설치 필요: `playwright install chromium`

investing.com 스크래핑 흐름:
1. `sync_playwright()` → Chromium headless 실행 → `page.goto()` 로 채권 페이지 탐색 (Cloudflare 쿠키 자동 획득)
2. `page.content()` HTML에서 `__NEXT_DATA__ > props.pageProps.state.bondStore.instrumentId` 로 pair_id 추출 — `int()` 변환 필수 (str로 저장됨)
3. `page.evaluate()` 내 `fetch POST /instruments/HistoricalDataAjax` (날짜 형식: `MM/DD/YYYY`) → HTML 테이블 반환 → `pd.read_html`로 파싱

GB 슬러그: `uk-{n}-year-bond-yield` (u.k. 형식 아님); US 20Y 슬러그: `us-20-year-bond-yield` (u.s. 형식 아님)

### 증분 업데이트 로직 (`collect_data.py`)

각 데이터셋에 대해:
1. 기존 CSV 로드 → 마지막 날짜 확인
2. 기존 데이터 없으면 최초 수집 (TreasurySummary: 1년, BondSummary: 5년, GlobalTreasury: 1년)
3. 기존 데이터 있으면 `last_date + 1` 부터 수집
4. `pd.concat` + `drop_duplicates(keep='last')` 로 병합 후 저장
5. 수집 실패 시 기존 데이터 보존 (덮어쓰기 없음)

### Output Structure

```
data/
  global_treasury.csv   # 글로벌 국채 (investing.com) — collect_data.py → git push
  treasury_summary.csv  # KOFIA 주요 만기 국채 (KR_nY 형식) — collect_data.py → git push
  bond_summary.csv      # KOFIA 전종목 최종호가수익률 — collect_data.py → git push
  tmp/                  # Selenium 임시 다운로드 (자동 정리)
```

### Notes

- `webdriver-manager` auto-downloads ChromeDriver; Chrome must be installed
- On Selenium error, page source is saved to `data/selenium_error_treasury.html` / `selenium_error_bond_A.html` 등
- `debug_frames.py` runs with a visible browser window (headless line intentionally commented out)
