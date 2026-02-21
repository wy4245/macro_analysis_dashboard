"""
데이터 수집 스크립트 — 서버에서 크롤링이 불가능한 소스만 수집합니다.
현재: investing.com (Cloudflare 우회 필요 → 로컬 실행 후 git push)

서버에서 직접 수집 가능한 소스(KOFIA 등)는 Streamlit 앱 내 버튼으로 수집합니다.

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

from modules.collector.investing.global_treasury_rate import GlobalTreasuryCollector

# ─── 날짜 설정: 전일 기준, 1년치 ───────────────────────────────────────────────
end_date   = date.today() - timedelta(days=1)
try:
    start_date = end_date.replace(year=end_date.year - 1)
except ValueError:  # 2월 29일인 경우
    start_date = end_date - timedelta(days=365)

end_str   = end_date.strftime("%Y-%m-%d")
start_str = start_date.strftime("%Y-%m-%d")

print(f"[수집 기간] {start_str} ~ {end_str}")
print()

# ─── 글로벌 국채 금리 (investing.com) ─────────────────────────────────────────
print("=" * 50)
print("[1/1] 글로벌 국채 금리 수집 (investing.com)")
print("      ※ Cloudflare 우회 필요 — 로컬 환경에서만 실행")
print("=" * 50)

collector = GlobalTreasuryCollector()
df = collector.collect(start_date=start_str, end_date=end_str)

if df is not None:
    save_path = _root / "data" / "global_treasury.csv"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(save_path)
    print(f"\n[완료] → {save_path}")
    print(df.tail(3))
else:
    print("\n[실패] 글로벌 국채 데이터 수집 실패")

# ─── 완료 안내 ────────────────────────────────────────────────────────────────
target_str = end_date.strftime("%Y%m%d")
print()
print("=" * 50)
print("수집 완료. 아래 명령어로 GitHub에 push하세요:")
print()
print(f'  git add data/')
print(f'  git commit -m "데이터 업데이트 {target_str}"')
print(f'  git push')
print("=" * 50)
