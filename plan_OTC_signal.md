# OTC 스프레드 시그널 계획

## 목표

기존 `장외거래 대표수익률` 탭의 스프레드 테이블 **위에**,
과거 5년 데이터 기반 통계적 이상 시그널을 시각적으로 표시

| 조건 | 시그널 |
|---|---|
| `\|spread - 5Y mean\| > 1.5σ` | ⚡ Caution (주의) |
| `\|spread - 5Y mean\| > 2.0σ` | 🚨 Warning (경고) |
| 그 외 | 정상 |

---

## 시그널 계산 로직

### 입력 데이터
- `_bond_df`: KOFIA 최종호가수익률
- `_otc_df`: KOFIA 장외거래대표수익률
- 공통 컬럼(종목) 기준으로 스프레드 시계열 계산

### 계산 순서

```python
# 스프레드 시계열 (bp 단위)
spread_ts = (_bond_df[common_cols] - _otc_df[common_cols]) * 100

# 5년(=1260 영업일) 롤링 통계 → 실제로는 전체 기간 사용 (최대 5년)
mean_5y = spread_ts.mean()   # 단순 전체 평균 (데이터가 이미 5년치)
std_5y  = spread_ts.std()

# 오늘 스프레드
today_spread = spread_ts.loc[spread_ts.index <= pd.Timestamp(TODAY)].iloc[-1]

# Z-score
z_score = (today_spread - mean_5y) / std_5y

# 시그널 판정
def _signal(z):
    if abs(z) >= 2.0: return "Warning"
    if abs(z) >= 1.5: return "Caution"
    return "Normal"
```

---

## UI 표시 형식

### 제안 A — 요약 배너 + 컴팩트 테이블 (권장)

```
┌─────────────────────────────────────────────────────────────┐
│  🚨 Warning  2종목    ⚡ Caution  3종목    ✅ 정상  13종목   │
└─────────────────────────────────────────────────────────────┘

시그널 종목 상세
┌──────────────────┬──────────┬──────────┬─────────┬──────────┐
│ 종목             │현재(bp)  │5Y평균(bp)│  Z-score│  시그널  │
├──────────────────┼──────────┼──────────┼─────────┼──────────┤
│ 회사채BBB-(3년)  │  +82.3   │  +45.1   │  +2.34  │ 🚨Warning│  ← 빨강
│ 회사채AA-(3년)   │  +28.7   │  +12.4   │  +1.95  │ 🚨Warning│  ← 빨강
│ 한전채(3년)      │  +15.2   │   +6.8   │  +1.63  │ ⚡Caution│  ← 주황
│ CD(91일)         │   -3.1   │   +0.2   │  -1.55  │ ⚡Caution│  ← 주황
└──────────────────┴──────────┴──────────┴─────────┴──────────┘
```

구현:
- 상단: `st.columns(3)` 으로 Warning/Caution/정상 카운트를 `st.metric()`으로 표시
- 하단: 시그널 종목만 필터링한 DataFrame, `df.style.apply()`로 행 단위 배경색 적용
- Warning 행: `background-color: rgba(255, 75, 75, 0.15)`
- Caution 행: `background-color: rgba(255, 165, 0, 0.15)`

---

### 제안 B — st.expander 안에 숨기기

```
[정상 외 시그널 5건 ▼ 펼치기]  ← st.expander
  (펼치면 제안 A의 상세 테이블 표시)
```

- 시그널이 없으면 expander 자체를 숨김
- 깔끔하지만 한눈에 안 보임

---

### 제안 C — st.warning / st.error 배너

```python
st.error("🚨 Warning: 회사채BBB-(3년) +82.3bp (Z=+2.34), 회사채AA-(3년) +28.7bp (Z=+1.95)")
st.warning("⚡ Caution: 한전채(3년) +15.2bp (Z=+1.63), CD(91일) -3.1bp (Z=-1.55)")
```

- 구현 간단하지만, 종목이 많으면 텍스트가 길어짐

---

## 최종 권장: 제안 A

**이유:**
- 한눈에 전체 현황 파악 (Warning N건 / Caution N건)
- 시그널 종목만 따로 보여줘 노이즈 최소화
- 기존 상세 스프레드 테이블은 그대로 아래에 유지
- Z-score 수치까지 보여줘 심각도 직관적 파악 가능

---

## 구현 위치

`main.py` 내 `elif domestic_sub == "장외거래 대표수익률":` 블록:

```python
# ── 현재 위치 ─────────────────────────────────────
# 기존 otc_cmp_df 생성/표시 코드 (변경 없음)

# ── 추가할 위치 (테이블 위) ─────────────────────────
# 1. spread_ts = (_bond_df[common_cols] - _otc_df[common_cols]) * 100
# 2. 통계 계산 (mean, std, z-score, signal)
# 3. st.columns(3) → Warning/Caution/정상 카운트 metric
# 4. 시그널 종목 상세 테이블
# 5. st.divider()
# 6. 기존 상세 스프레드 테이블 (그대로)
```

---

## 신규 파일

없음. `main.py`만 수정.

---

## 작업 범위 요약

| 항목 | 내용 |
|---|---|
| 변경 파일 | `main.py` |
| 추가 데이터 | 없음 (기존 `_bond_df`, `_otc_df` 재사용) |
| 라이브러리 추가 | 없음 (`pandas` std/mean으로 충분) |
| UI 위치 | 기존 스프레드 테이블 **위** |
| 시그널 기준 | 5Y 전체 평균·표준편차 기준 Z-score |
