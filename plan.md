# MMS HTML 변환 계획

작성일: 2026-02-28
현황: Streamlit(`main.py`) → 정적 HTML 페이지로 전환

---

## 1. 핵심 전제 판단: investing.com 브라우저 직접 크롤링 가능성

### 결론: **불가능** — 두 가지 기술적 장벽이 동시에 존재

| 장벽 | 상세 내용 |
|------|-----------|
| **CORS 정책** | `investing.com`은 `Access-Control-Allow-Origin: *` 헤더를 반환하지 않음. 브라우저에서 `fetch()`로 `https://www.investing.com/instruments/HistoricalDataAjax`에 POST 요청하면 브라우저가 CORS 오류로 차단 |
| **Cloudflare 보호** | investing.com은 Cloudflare JS 챌린지를 사용. 현재 코드(`investing.py`)가 Playwright(실제 헤드리스 Chrome)로 5초 대기하며 챌린지를 통과하는 이유가 이것. 일반 `fetch()`는 쿠키 없이 403/503 반환 |

### 왜 현재 Playwright 방식은 작동하는가

```
로컬 PC
  └─ Python collect_data.py
       └─ Playwright Chromium (headless)
            ├─ page.goto() → Cloudflare 챌린지 해결 (실제 Chrome 엔진)
            ├─ 쿠키 획득 (cf_clearance 등)
            └─ page.evaluate(fetch POST) → 쿠키 자동 포함 → 데이터 수신
```

브라우저 HTML 페이지의 `fetch()`는 다른 Origin(investing.com)으로의 POST를 **브라우저 자체가** 차단한다.
서버리스 프록시(Cloudflare Workers, Vercel Functions 등)를 직접 구현하지 않는 한 우회 불가.

### 대안 고려

| 방법 | 가능 여부 | 이유 |
|------|-----------|------|
| 브라우저 JS fetch | ❌ | CORS + Cloudflare |
| CORS 프록시 서비스 | ❌ | Cloudflare 챌린지 우회 불가 |
| 서버리스 함수(Vercel/CF Worker) | ⚠️ 부분적 | Playwright 실행 불가, Cloudflare 회피 불가 |
| 현재 방식 유지 (로컬 collect_data.py → CSV push) | ✅ | 변경 없이 작동 |

**→ 데이터 수집 방식(로컬 collect_data.py → git push)은 그대로 유지하고, 시각화만 HTML로 전환한다.**

---

## 2. 아키텍처 선택

### 옵션 비교

| 방식 | 서버 필요 | 장점 | 단점 |
|------|-----------|------|------|
| A. Python 빌드 → 데이터 내장 HTML | ❌ | 파일 하나로 완결, 오프라인 동작 | 데이터 갱신마다 재빌드 |
| B. 경량 HTTP 서버 + CSV fetch | 로컬 서버 | CSV 변경 즉시 반영 | 서버 실행 필요 |
| C. GitHub Pages + raw.githubusercontent.com | ❌ | 인터넷 어디서나 접근 | raw GitHub URL CORS 가능하나 캐시 지연 |

### 선택: **옵션 A (Python 빌드 스크립트 → 자립형 HTML)**

- `build_html.py` 실행 → CSV 읽기 → 데이터를 JS JSON으로 내장 → `index.html` 생성
- `collect_data.py`와 `git push` 후 `build_html.py`를 함께 실행하거나, CI/CD에서 자동 실행
- 생성된 `index.html`만 있으면 어떤 브라우저에서든 오프라인 열람 가능

---

## 3. 신규 파일 구조

```
MMS/
  build_html.py          ← 새로 생성: CSV 읽기 → index.html 빌드
  index.html             ← 빌드 결과물 (git tracked)
  data/
    global_treasury.csv
    treasury_summary.csv
    bond_summary.csv
```

`main.py`(Streamlit)와 `index.html`(HTML)은 **병행 유지** — 기존 워크플로우를 깨지 않음.

---

## 4. `build_html.py` 설계

### 역할
1. 세 CSV 파일 로드 (`global_treasury.csv`, `treasury_summary.csv`, `bond_summary.csv`)
2. 기존 `TreasuryCalc` 로직(merge, fill_calendar, build_change_summary, get_ref_value) 재사용
3. 계산 결과를 JSON으로 직렬화
4. HTML 템플릿에 `<script>` 블록으로 주입 → `index.html` 저장

### 출력 JSON 구조

```js
window.MMS_DATA = {
  generated: "2026-02-28",           // 빌드 시각
  target_date: "2026-02-27",         // 기준일 (전일)

  // 주요국 금리 변화 요약 (표 1)
  change_summary: [
    { country: "미국", tenor: "2년물", rate: 4.321, d1: 2.1, d1w: -5.3, mtd: 8.0, ytd: 12.4, yoy: -30.1 },
    ...
  ],

  // 금리 커브 데이터 (국가별 현재/1W/1M)
  yield_curves: {
    "US": { tenors: [2,3,5,10,20,30], now: [...], w1: [...], m1: [...] },
    "KR": { ... },
    ...
  },

  // 국내 채권 금리 동향 (표 2)
  bond_summary: [
    { label: "국고채(10년)", code: "KTB_10Y", rate: 2.814, d1: 1.2, d1w: -3.0, mtd: 5.1, ytd: 8.0, yoy: -25.0 },
    ...
  ],

  // 국고채 커브 (KR 전만기)
  ktb_curve: { tenors: [1,2,3,5,10,20,30,50], now: [...], w1: [...], m1: [...] },

  // Raw 시계열 (Raw Data 탭용 — 최근 1년치만 포함해 파일 크기 절감)
  raw_global: {
    dates: ["2025-02-28", ...],
    series: { "US_10Y": [...], "DE_10Y": [...], ... }
  },
  raw_bond: {
    dates: [...],
    series: { "KTB_10Y": [...], ... }
  }
};
```

---

## 5. `index.html` 구조

### 사용 라이브러리 (CDN, 로컬 파일 없음)

| 라이브러리 | 용도 | CDN |
|-----------|------|-----|
| Plotly.js | 차트 | `cdn.plot.ly/plotly-2.35.2.min.js` |
| (순수 Vanilla JS) | 탭, 테이블, 인터랙션 | — |

Bootstrap이나 외부 CSS 프레임워크는 최소화 (불필요한 의존성 배제).

### 페이지 레이아웃

```
┌─────────────────────────────────────────────────┐
│ MMS — Macro Monitoring System    기준일: 2026-02-27 │
├──────────────┬──────────────────────────────────┤
│ [Analysis]   │ [Raw Data]                        │
├──────────────┴──────────────────────────────────┤
│                                                  │
│  [글로벌 국채 금리] [국내 채권 금리]              │
│                                                  │
│  ▌주요국 금리 동향 표                            │
│    구분 | 2년물 금리 | 1D | 1W | MTD | YTD | YoY│
│         | 10년물 금리| 1D | 1W | MTD | YTD | YoY│
│                                                  │
│  ▌국가별 Yield Curve                            │
│    [국가 선택: 미국 ▼]                          │
│    [Plotly 차트: 현재/1W전/1M전]                │
│    [커브 데이터 표]                             │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 컬러 규칙 (Streamlit 버전과 동일)
- 금리 상승(bp > 0): `#ff4b4b` (빨강)
- 금리 하락(bp < 0): `#0068c9` (파랑)
- NaN: `-`

---

## 6. 구현 단계

### Phase 1: 빌드 스크립트 (`build_html.py`)
1. CSV 로드 및 기존 `TreasuryCalc` 계산 로직 재사용
2. JSON 직렬화 (NaN → null 처리)
3. HTML 템플릿 문자열 작성 (인라인) 또는 `templates/index.template.html` 분리
4. `<script>window.MMS_DATA = {...}</script>` 주입 후 `index.html` 저장

### Phase 2: HTML/JS 구현
1. 탭 전환 (Analysis / Raw Data, 글로벌 / 국내)
2. 금리 변화 요약 테이블 (MultiIndex → HTML table, bp 컬러링)
3. Plotly.js Yield Curve 차트 (국가 선택 드롭다운 연동)
4. 커브 데이터 보조 테이블
5. 국내 채권 금리 동향 테이블
6. 국고채 Yield Curve 차트
7. Raw Data 탭: 시계열 차트 + 전체 데이터 테이블 (컬럼 멀티셀렉트)

### Phase 3: 워크플로우 통합
```bash
# 기존
python collect_data.py
git add data/ && git commit -m "데이터 업데이트 YYYYMMDD" && git push

# 추가
python build_html.py
git add index.html && git commit -m "HTML 빌드 YYYYMMDD" && git push
```

또는 `collect_data.py` 마지막에 `build_html.py` 자동 호출로 통합.

---

## 7. 기술적 고려사항

### 파일 크기 관리
- 1년치 Raw 시계열 × 30컬럼(글로벌) + 18컬럼(국내) ≈ 약 365행 × 48열
- JSON으로 직렬화 시 약 200~400KB — 충분히 허용 범위
- Raw Data 탭의 시계열은 **최근 2년치**만 포함 (필요시 조정)

### NaN 처리
- Python `json.dumps`는 NaN을 직렬화하지 못함 → `float('nan')` → `None`으로 변환 후 JS에서 `null` 처리
- `pd.DataFrame.to_json(orient='records')` 사용 시 자동 처리됨

### 오프라인 Plotly.js
- CDN 사용이 기본이나, 오프라인 환경이 필요하면 `plotly.min.js`를 Base64로 내장하거나 별도 파일로 배포
- 현재는 CDN 방식으로 계획 (인터넷 연결 전제)

### Streamlit 병행 유지
- `main.py`는 삭제하지 않음
- `index.html`은 독립 파일로 git tracked
- 두 방식 중 선호하는 것을 워크플로우에 따라 선택 사용

---

## 8. 미결 결정사항 (구현 전 확인 필요)

| 항목 | 선택지 | 현재 기본값 |
|------|--------|------------|
| HTML 템플릿 분리 여부 | 인라인 문자열 vs `templates/` 파일 분리 | 인라인 (단일 파일 관리 용이) |
| Raw 시계열 포함 기간 | 1년 / 2년 / 전체 | 2년 |
| Plotly.js 로딩 | CDN vs 로컬 파일 | CDN |
| `collect_data.py`에 빌드 통합 | 자동 통합 vs 수동 별도 실행 | 별도 실행 (명시적 제어) |
| 다크모드 지원 | 지원 / 미지원 | 미지원 (시스템 기본) |
