"""
데이터 수집 스크립트 — 로컬에서 실행 후 git push

모든 데이터를 수집하여 data/ 에 저장합니다.
push하면 Streamlit 서버에 자동으로 반영됩니다.

사용법:
    python collect_data.py

완료 후 git push:
    git add data/
    git commit -m "데이터 업데이트 YYYYMMDD"
    git push
"""

import sys
from datetime import date, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

from modules.collector.kofia import TreasurySummary, BondSummary
from modules.collector.investing import GlobalTreasury

# ─── 날짜 설정 ────────────────────────────────────────────────────────────────
end_date   = date.today() - timedelta(days=1)
try:
    start_1y = end_date.replace(year=end_date.year - 1)
except ValueError:
    start_1y = end_date - timedelta(days=365)

end_str    = end_date.strftime("%Y-%m-%d")
start_str  = start_1y.strftime("%Y-%m-%d")
target_str = end_date.strftime("%Y%m%d")

print(f"[기준일] {end_str}")
print()


# ══════════════════════════════════════════════════════════════════════════════
# 1. KOFIA  (modules/collector/kofia.py)
# ══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("1. KOFIA")
print("=" * 60)

# ── 1-1. TreasurySummary (1년치, 주요 만기 국채) ─────────────────────────────
print()
print(f"  [1-1] TreasurySummary  (기준일: {target_str}, 1년치)")
print("  " + "-" * 40)

ts = TreasurySummary()
ok = ts.collect(target_date=target_str, headless=True)
if ok:
    df = ts.load(target_str)
    if df is not None:
        print(df.tail(3).to_string())
else:
    print("  [실패] TreasurySummary 수집 실패")

# ── 1-2. BondSummary (5년치, 전종목) ─────────────────────────────────────────
print()
print(f"  [1-2] BondSummary  (기준일: {target_str}, 5년치)")
print("  " + "-" * 40)

bs = BondSummary()
ok = bs.collect(target_date=target_str, headless=True)
if ok:
    df = bs.load(target_str)
    if df is not None:
        print(df.tail(3).to_string())
        print(f"  컬럼 ({len(df.columns)}개): {df.columns.tolist()}")
else:
    print("  [실패] BondSummary 수집 실패")


# ══════════════════════════════════════════════════════════════════════════════
# 2. investing.com  (modules/collector/investing.py)
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("2. investing.com")
print("=" * 60)

# ── 2-1. GlobalTreasury (1년치, 글로벌 국채) ──────────────────────────────────
print()
print(f"  [2-1] GlobalTreasury  ({start_str} ~ {end_str})")
print("  " + "-" * 40)

gt = GlobalTreasury()
df_g = gt.collect(start_date=start_str, end_date=end_str)
if df_g is not None:
    save_path = _root / "data" / "global_treasury.csv"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    df_g.to_csv(save_path)
    print(f"  [완료] → {save_path}")
    print(df_g.tail(3).to_string())
else:
    print("  [실패] GlobalTreasury 수집 실패")


# ─── 완료 안내 ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("수집 완료. 아래 명령어로 GitHub에 push하세요:")
print()
print(f'  git add data/')
print(f'  git commit -m "데이터 업데이트 {target_str}"')
print(f'  git push')
print("=" * 60)
