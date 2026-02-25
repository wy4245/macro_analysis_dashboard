"""
investing.com 데이터 수집기

GlobalTreasury : 글로벌 주요국 국채 금리 (curl_cffi Cloudflare 우회)
  collect(start_date, end_date) -> pd.DataFrame | None

수집 국가: US / DE / GB / JP / CN  |  만기: 2/3/5/10/20/30년
컬럼 형식: {CC}_{n}Y  (예: US_10Y, DE_2Y)

구현 방식:
  1. curl_cffi Session(impersonate="chrome120") → Cloudflare 쿠키 획득
  2. __NEXT_DATA__ > state.bondStore.instrumentId 에서 pair_id 추출
  3. POST /instruments/HistoricalDataAjax → HTML 테이블 반환 → pd.read_html 파싱

※ SSL workaround: _ensure_ascii_ssl_cert() — 한글 경로 환경의 certifi 경로 문제 회피.
   모듈 import 시 자동 실행되므로 제거하지 마세요.
"""

import os
import re
import sys
import json
import time
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from datetime import datetime

import pandas as pd
from curl_cffi import requests as cffi_requests

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _ensure_ascii_ssl_cert() -> None:
    """
    Windows 환경에서 프로젝트 경로에 한글이 포함된 경우
    libcurl이 certifi CA 번들 경로를 읽지 못하는 문제를 회피합니다.
    ASCII 경로의 임시 디렉터리에 번들을 복사합니다.
    """
    try:
        import certifi
        src = certifi.where()
        try:
            src.encode("ascii")
            return
        except UnicodeEncodeError:
            pass
        dst_dir = os.path.join(tempfile.gettempdir(), "mat_certs")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "cacert.pem")
        if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
            shutil.copy(src, dst)
        for var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            os.environ[var] = dst
    except Exception:
        pass


_ensure_ascii_ssl_cert()

from modules.calculator.global_treasury import TreasuryCalc  # noqa: E402


class GlobalTreasury:
    """
    investing.com에서 글로벌 국채 금리 데이터를 수집합니다.

    국가  : US(미국), DE(독일), GB(영국), JP(일본), CN(중국)
    만기  : 2 / 3 / 5 / 10 / 20 / 30년 (국가별로 없는 만기는 자동 건너뜀)
    단위  : % (수익률)
    빈도  : 일별 (거래일 기준, 주말·공휴일은 ffill로 채움)
    """

    # investing.com URL 슬러그 맵
    BOND_SLUGS: dict[str, dict[int, str]] = {
        "US": {
            2:  "u.s.-2-year-bond-yield",
            3:  "u.s.-3-year-bond-yield",
            5:  "u.s.-5-year-bond-yield",
            10: "u.s.-10-year-bond-yield",
            20: "us-20-year-bond-yield",
            30: "u.s.-30-year-bond-yield",
        },
        "DE": {
            2:  "germany-2-year-bond-yield",
            3:  "germany-3-year-bond-yield",
            5:  "germany-5-year-bond-yield",
            10: "germany-10-year-bond-yield",
            20: "germany-20-year-bond-yield",
            30: "germany-30-year-bond-yield",
        },
        "GB": {
            2:  "uk-2-year-bond-yield",
            3:  "uk-3-year-bond-yield",
            5:  "uk-5-year-bond-yield",
            10: "uk-10-year-bond-yield",
            20: "uk-20-year-bond-yield",
            30: "uk-30-year-bond-yield",
        },
        "JP": {
            2:  "japan-2-year-bond-yield",
            3:  "japan-3-year-bond-yield",
            5:  "japan-5-year-bond-yield",
            10: "japan-10-year-bond-yield",
            20: "japan-20-year-bond-yield",
            30: "japan-30-year-bond-yield",
        },
        "CN": {
            2:  "china-2-year-bond-yield",
            3:  "china-3-year-bond-yield",
            5:  "china-5-year-bond-yield",
            10: "china-10-year-bond-yield",
            20: "china-20-year-bond-yield",
            30: "china-30-year-bond-yield",
        },
    }

    INVESTING_BASE = "https://www.investing.com/rates-bonds"
    HIST_AJAX_URL  = "https://www.investing.com/instruments/HistoricalDataAjax"

    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self) -> None:
        self._session        = cffi_requests.Session(impersonate="chrome120")
        self._pair_id_cache: dict[str, int] = {}

    # ── pair_id 조회 ──────────────────────────────────────────────────────────

    def _get_pair_id(self, slug: str) -> int | None:
        if slug in self._pair_id_cache:
            return self._pair_id_cache[slug]

        url = f"{self.INVESTING_BASE}/{slug}-historical-data"
        try:
            resp = self._session.get(
                url,
                headers={**self._BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                timeout=30,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except Exception as e:
            print(f"    [경고] 페이지 접근 실패 ({slug}): {e}")
            return None

        pair_id = self._extract_pair_id(resp.text)
        if pair_id:
            self._pair_id_cache[slug] = pair_id
        else:
            print(f"    [경고] pair_id 미발견 ({slug})")
        return pair_id

    @staticmethod
    def _extract_pair_id(html: str) -> int | None:
        m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                nd    = json.loads(m.group(1))
                state = nd.get("props", {}).get("pageProps", {}).get("state", {})
                instrument_id = state.get("bondStore", {}).get("instrumentId")
                if instrument_id is not None:
                    v = int(instrument_id)
                    if v > 0:
                        return v
                found = GlobalTreasury._search_in_json(nd)
                if found:
                    return found
            except Exception:
                pass

        for pat in [
            r'"pair_id"\s*:\s*(\d{4,})',
            r"'pair_id'\s*:\s*(\d{4,})",
            r'data-pair-id=["\'](\d{4,})["\']',
            r'var\s+pair_id\s*=\s*(\d{4,})',
        ]:
            m2 = re.search(pat, html)
            if m2:
                return int(m2.group(1))
        return None

    @staticmethod
    def _search_in_json(obj: object, _depth: int = 0) -> int | None:
        if _depth > 12:
            return None
        if isinstance(obj, dict):
            for key in ("instrumentId", "pairId", "pair_id"):
                val = obj.get(key)
                if val is not None:
                    try:
                        v = int(val)
                        if v > 1000:
                            return v
                    except (ValueError, TypeError):
                        pass
            for v in obj.values():
                r = GlobalTreasury._search_in_json(v, _depth + 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj[:30]:
                r = GlobalTreasury._search_in_json(item, _depth + 1)
                if r:
                    return r
        return None

    # ── 시계열 조회 ───────────────────────────────────────────────────────────

    def _fetch_history(self, pair_id: int, slug: str, start_date: str, end_date: str) -> pd.Series | None:
        st = datetime.strptime(start_date, "%Y-%m-%d").strftime("%m/%d/%Y")
        en = datetime.strptime(end_date,   "%Y-%m-%d").strftime("%m/%d/%Y")

        headers = {
            **self._BROWSER_HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "Accept":           "text/plain, */*; q=0.01",
            "Content-Type":     "application/x-www-form-urlencoded",
            "Referer":          f"{self.INVESTING_BASE}/{slug}-historical-data",
        }
        form_data = {
            "curr_id": str(pair_id), "smlID": "",
            "st_date": st, "end_date": en,
            "interval_sec": "Daily", "sort_col": "date", "sort_ord": "ASC",
            "action": "historical_data",
        }
        try:
            resp = self._session.post(self.HIST_AJAX_URL, data=form_data, headers=headers, timeout=30)
            resp.raise_for_status()
            dfs = pd.read_html(StringIO(resp.text))
            if not dfs:
                return None
            df = dfs[0]
            if "Date" not in df.columns or "Price" not in df.columns:
                return None
            df["Date"]  = pd.to_datetime(df["Date"])
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
            df = df.dropna(subset=["Date", "Price"]).sort_values("Date", ascending=True)
            return pd.Series(df["Price"].values, index=df["Date"].dt.date, dtype=float)
        except Exception as e:
            print(f"    [경고] 데이터 조회 오류 (pair_id={pair_id}): {e}")
            return None

    # ── 공개 인터페이스 ───────────────────────────────────────────────────────

    def collect(self, start_date: str, end_date: str) -> pd.DataFrame | None:
        """
        investing.com에서 글로벌 국채 금리 데이터를 수집합니다.

        Args:
            start_date: "YYYY-MM-DD" (포함)
            end_date  : "YYYY-MM-DD" (포함)

        Returns:
            Date 인덱스, 컬럼명 "{CC}_{n}Y" 의 pd.DataFrame. 실패 시 None.
        """
        all_series: dict[str, pd.Series] = {}
        total = sum(len(m) for m in self.BOND_SLUGS.values())
        done  = 0

        for country, maturities in self.BOND_SLUGS.items():
            for tenor, slug in maturities.items():
                done += 1
                col = f"{country}_{tenor}Y"
                print(f"  [{done}/{total}] {col} 수집 중...", flush=True)

                pair_id = self._get_pair_id(slug)
                if pair_id is None:
                    print(f"    → 건너뜀 (pair_id 없음)")
                    time.sleep(0.3)
                    continue

                time.sleep(0.5)
                series = self._fetch_history(pair_id, slug, start_date, end_date)
                if series is not None and not series.empty:
                    all_series[col] = series
                    print(f"    → {len(series)}행 수집 완료")
                else:
                    print(f"    → 데이터 없음")
                time.sleep(0.5)

        if not all_series:
            print("  [오류] 수집된 데이터 없음")
            return None

        df = pd.DataFrame(all_series)
        df.index.name = "Date"
        df = df.sort_index()

        missing = [c for c in df.columns if df[c].isna().all()]
        if missing:
            print(f"  [경고] 전체 NaN 컬럼 (미지원): {missing}")

        print(f"  기간: {start_date} ~ {end_date}  |  {len(df)}행 {len(df.columns)}열")
        return TreasuryCalc.fill_calendar(df)


if __name__ == "__main__":
    from datetime import date, timedelta

    _end   = date.today() - timedelta(days=1)
    _start = _end - timedelta(days=365)

    print(f"=== GlobalTreasury | {_start} ~ {_end} ===")
    collector = GlobalTreasury()
    df = collector.collect(start_date=str(_start), end_date=str(_end))

    if df is not None:
        save_path = _root / "data" / "global_treasury.csv"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(save_path)
        print(f"\n[저장] → {save_path}")
        print(df.tail())
    else:
        print("[실패]")
