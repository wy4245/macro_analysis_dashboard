"""
데이터 수집 스크립트 — 로컬에서 실행 후 git push

기존 CSV를 읽어 마지막 날짜 이후분만 증분 수집 후 병합 저장합니다.
수집 실패 시 기존 데이터는 그대로 보존됩니다.

저장 경로:
  data/global_treasury.csv   — investing.com 글로벌 국채 (5년치)
  data/bond_summary.csv      — KOFIA 전종목 최종호가수익률 (5년치)

사용법:
    python collect_data.py

완료 후 git push:
    git add data/
    git commit -m "데이터 업데이트 YYYYMMDD"
    git push
"""

import sys
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

from modules.collector.kofia import BondSummary
from modules.collector.investing import GlobalTreasury
from modules.calculator.kofia import KofiaCalc

RAW_DIR = _root / "data"
RAW_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_TREASURY_CSV = RAW_DIR / "global_treasury.csv"
BOND_SUMMARY_CSV    = RAW_DIR / "bond_summary.csv"

# ─── 기준일 ────────────────────────────────────────────────────────────────────

end_date   = date.today() - timedelta(days=1)
end_str    = end_date.strftime("%Y-%m-%d")
target_str = end_date.strftime("%Y%m%d")

print(f"[기준일] {end_str}")
print()


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> pd.DataFrame | None:
    """기존 CSV를 DatetimeIndex DataFrame으로 로드합니다."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col="Date", parse_dates=True)
        return df
    except Exception as e:
        print(f"  [읽기 오류] {path.name}: {e}")
        return None


def _last_date(df: pd.DataFrame | None) -> date | None:
    """DataFrame의 마지막 날짜를 반환합니다."""
    if df is None or df.empty:
        return None
    return df.index.max().date()


def _merge_save(existing: pd.DataFrame | None, new_df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """
    기존 DataFrame과 새 데이터를 병합하여 CSV로 저장합니다.
    중복 날짜는 새 데이터를 우선합니다.
    """
    if existing is not None and not existing.empty:
        merged = pd.concat([existing, new_df])
        merged = merged[~merged.index.duplicated(keep="last")]
        merged.sort_index(inplace=True)
    else:
        merged = new_df.sort_index()
    merged.to_csv(path)
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# 1. KOFIA BondSummary
# ══════════════════════════════════════════════════════════════════════════════

print("=" * 60)
print("1. KOFIA BondSummary")
print("=" * 60)

bs_existing = _load_csv(BOND_SUMMARY_CSV)
bs_last     = _last_date(bs_existing)

if bs_last:
    bs_start_dt = bs_last + timedelta(days=1)
else:
    try:
        bs_start_dt = end_date.replace(year=end_date.year - 5)
    except ValueError:
        bs_start_dt = end_date - timedelta(days=365 * 5)

bs_start_str = bs_start_dt.strftime("%Y-%m-%d")
print(f"  기간: {bs_start_str} ~ {end_str}")
print("  " + "-" * 40)

if bs_start_dt > end_date:
    print("  [완료] 이미 최신 데이터")
else:
    bs = BondSummary()
    df_bond = bs.collect(start_date=bs_start_str, end_date=end_str)
    if df_bond is not None:
        try:
            df_std = KofiaCalc.standardize_bond(df_bond)
            merged = _merge_save(bs_existing, df_std, BOND_SUMMARY_CSV)
            print(f"  [저장] → {BOND_SUMMARY_CSV}  ({len(merged)}행 {len(merged.columns)}열)")
            print(merged.tail(3).to_string())
        except Exception as e:
            print(f"  [표준화 오류] {e}")
    else:
        print("  [실패] 기존 데이터 유지")

print()

# ══════════════════════════════════════════════════════════════════════════════
# 2. investing.com GlobalTreasury
# ══════════════════════════════════════════════════════════════════════════════

print("=" * 60)
print("2. investing.com GlobalTreasury")
print("=" * 60)

gt_existing = _load_csv(GLOBAL_TREASURY_CSV)
gt_last     = _last_date(gt_existing)

if gt_last:
    gt_start_dt = gt_last + timedelta(days=1)
else:
    try:
        gt_start_dt = end_date.replace(year=end_date.year - 5)
    except ValueError:
        gt_start_dt = end_date - timedelta(days=365 * 5)

gt_start_str = gt_start_dt.strftime("%Y-%m-%d")
print(f"  기간: {gt_start_str} ~ {end_str}")
print("  " + "-" * 40)

if gt_start_dt > end_date:
    print("  [완료] 이미 최신 데이터")
else:
    gt = GlobalTreasury()
    df_g = gt.collect(start_date=gt_start_str, end_date=end_str)
    if df_g is not None:
        merged = _merge_save(gt_existing, df_g, GLOBAL_TREASURY_CSV)
        print(f"  [저장] → {GLOBAL_TREASURY_CSV}  ({len(merged)}행 {len(merged.columns)}열)")
        print(merged.tail(3).to_string())
    else:
        print("  [실패] 기존 데이터 유지")

print()

# ─── 완료 안내 ────────────────────────────────────────────────────────────────
print("=" * 60)
print("수집 완료. 아래 명령어로 GitHub에 push하세요:")
print()
print(f'  git add data/')
print(f'  git commit -m "데이터 업데이트 {target_str}"')
print(f'  git push')
print("=" * 60)
