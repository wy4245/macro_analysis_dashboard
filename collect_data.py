"""
데이터 수집 스크립트 — 매일 한 번 로컬에서 실행하여 GitHub에 push합니다.

사용법:
    python collect_data.py

완료 후 git push:
    git add data/
    git commit -m "데이터 업데이트 YYYYMMDD"
    git push
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

from modules.collector.global_treasury_rate import GlobalTreasuryCollector
from modules.collector.kofia_bond import KofiaBondCollector

# ─── 날짜 설정: 전일 기준, 1년치 ───────────────────────────────────────────────
end_date   = date.today() - timedelta(days=1)
try:
    start_date = end_date.replace(year=end_date.year - 1)
except ValueError:  # 2월 29일인 경우
    start_date = end_date - timedelta(days=365)

end_str    = end_date.strftime("%Y-%m-%d")
start_str  = start_date.strftime("%Y-%m-%d")
target_str = end_date.strftime("%Y%m%d")

print(f"[수집 기간] {start_str} ~ {end_str}")
print()

# ─── 1. 글로벌 국채 금리 (investing.com) ──────────────────────────────────────
print("=" * 50)
print("[1/2] 글로벌 국채 금리 수집 (investing.com)")
print("=" * 50)

collector_g = GlobalTreasuryCollector()
df_g = collector_g.collect(start_date=start_str, end_date=end_str)

if df_g is not None:
    save_path = _root / "data" / "global_treasury.csv"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    df_g.to_csv(save_path)
    print(f"\n[완료] → {save_path}")
    print(df_g.tail(3))
else:
    print("\n[실패] 글로벌 국채 데이터 수집 실패")

print()

# ─── 2. KOFIA 국채 금리 (한국) ────────────────────────────────────────────────
print("=" * 50)
print(f"[2/2] KOFIA 국채 금리 수집 (기준일: {target_str})")
print("=" * 50)

collector_k = KofiaBondCollector()
ok = collector_k.Treasury_Collector_Selenium(target_date=target_str, headless=True)

if ok:
    print(f"[완료] → data/raw/{target_str}/kofia_bond_yield.xlsx")
    df_k = collector_k.load_excel(target_str)
    if df_k is not None:
        print(df_k.tail(3))
else:
    print("[실패] KOFIA 데이터 수집 실패")

# ─── 완료 안내 ────────────────────────────────────────────────────────────────
print()
print("=" * 50)
print("수집 완료. 아래 명령어로 GitHub에 push하세요:")
print()
print(f'  git add data/')
print(f'  git commit -m "데이터 업데이트 {target_str}"')
print(f'  git push')
print("=" * 50)
