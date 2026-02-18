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
python modules/collector/kofia_bond.py
python modules/collector/global_treasury_rate.py

# Debug KOFIA website frame structure (opens visible browser window)
python modules/debug_frames.py
```

## Architecture

### Data Flow

- `main.py` is a Streamlit app (`streamlit run main.py`); UI controls drive data loading.
- During development, each collector can be run standalone via its `if __name__ == "__main__"` block.
- Dates are hardcoded in each collector's `__main__` block (not passed via CLI).
- KOFIA data is saved to disk (xlsx) then read back; yfinance data is fetched directly into memory and cached via `@st.cache_data(ttl=3600)`.

### Adding a New Data Section

1. Create `modules/collector/<name>.py` with a class exposing a method returning `pd.DataFrame | None`
2. In `main.py`, add a new tab name to the `st.tabs([...])` list
3. Add a `with tab_<name>:` block — follow the pattern of existing tabs

### Module Structure

```
modules/
  collector/
    kofia_bond.py           # KofiaBondCollector — KOFIA domestic bond yields (Selenium)
    global_treasury_rate.py # GlobalTreasuryCollector — global gov bond yields (yfinance)
  debug_frames.py           # iframe inspection utility for KOFIA site
```

### Collectors

**`KofiaBondCollector`** (`kofia_bond.py`)
- Selenium-based; navigates the KOFIA WebSquare site
- `Treasury_Collector_Selenium(target_date, headless=True) -> bool` — downloads Korean Treasury yields (2, 3, 10, 20, 30yr) for a 1-year window ending at `target_date`; returns `True` on success
- `load_excel(target_date) -> pd.DataFrame | None` — reads a previously downloaded file from disk
- KOFIA `.xls` downloads are HTML tables: parse with `pd.read_html(flavor='lxml')`, fall back to `pd.read_excel()`
- Downloaded filename: `최종호가 수익률.xls`; renamed/converted to `kofia_bond_yield.xlsx`
- Output: `data/raw/YYYYMMDD/kofia_bond_yield.xlsx` (ascending date-sorted)

KOFIA iframe navigation sequence:
```
default_content → fraAMAKMain → (menu click) → maincontent → tabContents1_contents_tabs2_body
```
Menu IDs: `genLv1_0_imgLv1` → `genLv1_0_genLv2_0_txtLv2`; period tab: `tabContents1_tab_tabs2`; search: `image4`; download: `imgExcel`

Bond checkbox IDs — uncheck: `chkAnnItm_input_10/11/14/16`; check (KTB 2/3/10/20/30yr): `chkAnnItm_input_1/2/4/5/6`

**`GlobalTreasuryCollector`** (`global_treasury_rate.py`)
- Uses `curl_cffi` (Cloudflare bypass) + investing.com scraping
- Downloads US, DE, GB, JP, CN treasury yields; 29 maturities (US 20Y unavailable on investing.com)
- Wide format, columns: `{CC}_{n}Y` (e.g. `US_10Y`, `DE_2Y`)
- `collect(start_date, end_date) -> pd.DataFrame | None` — returns data directly (no disk write)
- Data is trading-day only; NaN where a market is closed on a given date

investing.com 스크래핑 흐름:
1. `curl_cffi.Session(impersonate="chrome120")` → Cloudflare 쿠키 획득
2. `__NEXT_DATA__ > state.bondStore.instrumentId`(str)에서 pair_id 추출 — `int()` 변환 필수 (str로 저장됨)
3. `POST /instruments/HistoricalDataAjax` (날짜 형식: `MM/DD/YYYY`) → HTML 테이블 반환 → `pd.read_html`로 파싱

GB 슬러그: `uk-{n}-year-bond-yield` (u.k. 형식 아님); US 20Y 슬러그: `us-20-year-bond-yield` (u.s. 형식 아님)

- **SSL workaround**: `_ensure_ascii_ssl_cert()` runs at module import time — copies the certifi CA bundle to an ASCII-safe temp path (`%TEMP%/mat_certs/cacert.pem`) and sets `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE`. Required because this project lives under a Korean-character path; do not remove.

### Output Structure

```
data/raw/
  YYYYMMDD/
    kofia_bond_yield.xlsx    # KOFIA domestic bond yields (Selenium download → saved to disk)
    # global treasury data lives only in memory (fetched fresh via yfinance)
```

### Notes

- `webdriver-manager` auto-downloads ChromeDriver; Chrome must be installed
- On Selenium error, page source is saved to `data/raw/selenium_error_step.html`
- `debug_frames.py` runs with a visible browser window (headless line intentionally commented out)
