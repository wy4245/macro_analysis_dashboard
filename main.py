# python -m streamlit run main.py --server.port 8801


import os
import glob
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta, date

from modules.collector.kofia_bond import KofiaBondCollector
from modules.collector.global_treasury_rate import GlobalTreasuryCollector
from modules.utils import merge_treasury, build_change_summary, get_ref_value


# ─── 기준일 설정 (날짜 변경 시 이 값만 수정) ────────────────────────────────
TARGET_DATE = date(2026, 2, 18)   #!  여기만 수정


# ─── 페이지 기본 설정 ──────────────────────────────────────────────────────────
st.set_page_config(page_title="MAT", layout="wide")
st.title("Macro Analysis")

TODAY     = TARGET_DATE
TODAY_STR = TODAY.strftime("%Y-%m-%d")
try:
    START_DATE = TODAY.replace(year=TODAY.year - 1)
except ValueError:  # 2월 29일인 경우
    START_DATE = TODAY - timedelta(days=365)
START_STR = START_DATE.strftime("%Y-%m-%d")

COUNTRIES = ["KR", "US", "DE", "GB", "JP", "CN"]
TENORS    = [2, 3, 5, 10, 20, 30]


# ─── 데이터 자동 로드 (캐시) ──────────────────────────────────────────────────

@st.cache_data(
    ttl=3600,
    show_spinner="investing.com에서 글로벌 금리 데이터 수집 중... (약 2~3분 소요)",
)
def _load_global(start: str, end: str) -> pd.DataFrame | None:
    return GlobalTreasuryCollector().collect(start_date=start, end_date=end)


def _load_latest_kofia() -> pd.DataFrame | None:
    """data/raw/*/kofia_bond_yield.xlsx 중 가장 최근 파일을 로드합니다."""
    pattern = os.path.join("data", "raw", "*", "kofia_bond_yield.xlsx")
    files   = sorted(glob.glob(pattern))
    if not files:
        return None
    latest   = files[-1]
    date_str = os.path.basename(os.path.dirname(latest))
    return KofiaBondCollector().load_excel(date_str)


# ─── 앱 시작 시 사전 계산 (탭 렌더링 전) ─────────────────────────────────────

_global_df: pd.DataFrame | None = _load_global(START_STR, TODAY_STR)
_kofia_df:  pd.DataFrame | None = _load_latest_kofia()

_merged_df: pd.DataFrame | None = None
if _global_df is not None and _kofia_df is not None:
    _merged_df = merge_treasury(_global_df, _kofia_df)
elif _global_df is not None:
    _merged_df = _global_df
elif _kofia_df is not None:
    _merged_df = _kofia_df


# ─── 헬퍼: 특정 날짜의 금리 커브 시리즈 추출 ─────────────────────────────────

def _yield_curve_at(df: pd.DataFrame, country: str, ref_date) -> pd.Series:
    """ref_date 이하 가장 가까운 날짜의 해당 국가 금리 커브를 반환합니다."""
    cols       = [f"{country}_{t}Y" for t in TENORS]
    avail_cols = [c for c in cols if c in df.columns]
    if not avail_cols:
        return pd.Series(float("nan"), index=TENORS, dtype=float)

    avail_idx = df.index[df.index <= pd.Timestamp(ref_date)]
    if len(avail_idx) == 0:
        return pd.Series(float("nan"), index=TENORS, dtype=float)

    row    = df.loc[avail_idx[-1], avail_cols]
    result = pd.Series(index=TENORS, dtype=float)
    for t in TENORS:
        c = f"{country}_{t}Y"
        if c in row.index:
            result[t] = row[c]
    return result


# ─── 탭 목록 ─────────────────────────────────────────────────────────────────

tab_global, tab_kofia, tab_merged = st.tabs([
    "글로벌 국채 금리",
    "KOFIA 국채 금리 (KR)",
    "병합 데이터",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: 글로벌 국채 금리
# ══════════════════════════════════════════════════════════════════════════════
with tab_global:
    st.caption(
        f"Source: investing.com + KOFIA  ·  기준일: {TODAY_STR}  ·  "
        "주말·공휴일은 직전 거래일 값으로 채워짐"
    )

    if _merged_df is None:
        st.error("데이터를 불러오지 못했습니다. 터미널 로그를 확인해주세요.")

    else:
        # ── 섹션 1: 주요 금리 변화 현황 ─────────────────────────────────────
        st.subheader("주요 금리 변화 현황")
        st.caption("2년물 / 10년물 기준  ·  bp = basis point (0.01%p)")

        summary_df = build_change_summary(_merged_df, target_date=TARGET_DATE)

        # 색상 스타일링 함수 (bp 변화량에만 적용)
        def _color_bp(val):
            if pd.isna(val):
                return ""
            if isinstance(val, (int, float)):
                if val > 0:
                    return "color: #ff4b4b"   # 적색 (금리 상승)
                if val < 0:
                    return "color: #0068c9"   # 청색 (금리 하락)
            return ""

        # 포맷팅 함수 정의
        def _format_values(val, col_name):
            if pd.isna(val):
                return "-"
            # 컬럼명에 '%'가 포함되면 소수점 3자리, 아니면(bp) 소수점 1자리
            if "%" in str(col_name):
                return f"{val:.3f}"
            return f"{val:.1f}"

        # 스타일링 적용
        # 1. 포맷팅 (applymap 대신 format 사용이 더 깔끔함. 대신 컬럼별로 format 딕셔너리 생성)
        format_dict = {}
        for col in summary_df.columns:
            # MultiIndex 컬럼인 경우 튜플의 두 번째 요소 확인
            col_label = col[1] if isinstance(col, tuple) else col
            if "%" in col_label:
                format_dict[col] = "{:.3f}"
            else:
                format_dict[col] = "{:.1f}"

        styled = summary_df.style.format(format_dict)

        # 2. 색상 적용 (bp 컬럼만)
        bp_cols = [c for c in summary_df.columns if "금리" not in c[1]]
        styled = styled.map(_color_bp, subset=bp_cols)

        # 3. 가운데 정렬 (헤더 & 데이터)
        # set_properties: 데이터 셀 정렬
        # set_table_styles: 헤더 셀 정렬
        styled = styled.set_properties(**{'text-align': 'center'})
        styled = styled.set_table_styles([
            dict(selector='th', props=[('text-align', 'center')]),
            dict(selector='td', props=[('text-align', 'center')])
        ])

        st.dataframe(styled, use_container_width=True)

        st.divider()

        # ── 섹션 2: 국가별 금리 커브 ─────────────────────────────────────────
        st.subheader("국가별 금리 커브")

        # 국가명 매핑
        COUNTRY_MAP = {
            "US": "미국", "KR": "한국", "DE": "독일",
            "GB": "영국", "JP": "일본", "CN": "중국"
        }

        avail_countries = [
            c for c in COUNTRIES
            if any(f"{c}_{t}Y" in _merged_df.columns for t in TENORS)
        ]
        
        # selectbox에 표시될 때 한국어 이름 사용
        selected_code = st.selectbox(
            "국가 선택", 
            options=avail_countries, 
            format_func=lambda x: COUNTRY_MAP.get(x, x),
            key="curve_country"
        )
        selected_name = COUNTRY_MAP.get(selected_code, selected_code)

        today_curve = _yield_curve_at(_merged_df, selected_code, TODAY)
        week_curve  = _yield_curve_at(_merged_df, selected_code, TODAY - timedelta(days=7))
        month_curve = _yield_curve_at(_merged_df, selected_code, TODAY - timedelta(days=30))

        tenor_labels = [f"{t}Y" for t in TENORS]

        # 금리 커브 차트
        fig_curve = go.Figure()
        if not today_curve.dropna().empty:
            fig_curve.add_trace(go.Scatter(
                x=tenor_labels, y=today_curve.values,
                mode="lines+markers", name=f"현재 ({TODAY_STR})",
                line=dict(width=2.5),
            ))
        if not week_curve.dropna().empty:
            fig_curve.add_trace(go.Scatter(
                x=tenor_labels, y=week_curve.values,
                mode="lines+markers", name="1주 전",
                line=dict(dash="dot", width=1.5),
                opacity=0.8,
            ))
        if not month_curve.dropna().empty:
            fig_curve.add_trace(go.Scatter(
                x=tenor_labels, y=month_curve.values,
                mode="lines+markers", name="1개월 전",
                line=dict(dash="dash", width=1.5),
                opacity=0.8,
            ))

        fig_curve.update_layout(
            title=f"{selected_name} 국채 금리 커브",
            xaxis_title="만기",
            yaxis_title="수익률 (%)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_curve, use_container_width=True)

        # 금리 커브 변화 테이블
        # 계산은 raw 값으로 하고, 표시는 Styler로 처리
        curve_data = {
            "현재(%)": today_curve.values,
            "1W(bp)":  (today_curve - week_curve).values * 100,
            "1M(bp)":  (today_curve - month_curve).values * 100,
        }
        curve_table = pd.DataFrame(curve_data, index=pd.Index(tenor_labels, name="만기"))

        # 스타일링
        def _color_curve_bp(val):
            if pd.isna(val):
                return ""
            if val > 0:
                return "color: #ff4b4b"
            if val < 0:
                return "color: #0068c9"
            return ""

        curve_styled = curve_table.style.format({
            "현재(%)": "{:.3f}",
            "1W(bp)":  "{:.1f}",
            "1M(bp)":  "{:.1f}",
        })
        curve_styled = curve_styled.map(_color_curve_bp, subset=["1W(bp)", "1M(bp)"])
        
        # 가운데 정렬
        curve_styled = curve_styled.set_properties(**{'text-align': 'center'})
        curve_styled = curve_styled.set_table_styles([
            dict(selector='th', props=[('text-align', 'center')])
        ])

        st.dataframe(curve_styled, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: KOFIA 국채 금리 (KR)
# ══════════════════════════════════════════════════════════════════════════════
with tab_kofia:
    st.caption("Source: KOFIA (kofiabond.or.kr)  ·  Selenium으로 다운로드 후 xlsx 읽기")

    # 수동 다운로드 섹션
    with st.expander("KOFIA 데이터 새로 다운로드 (필요시만)"):
        k_date     = st.date_input("기준일", value=datetime.today(), key="k_date")
        k_date_str = k_date.strftime("%Y%m%d")
        if st.button("KOFIA 다운로드 (Selenium)", key="k_dl"):
            with st.spinner("Selenium으로 KOFIA 접속 중... 약 30~60초 소요"):
                ok = KofiaBondCollector().Treasury_Collector_Selenium(
                    target_date=k_date_str, headless=True
                )
            if ok:
                st.success(f"다운로드 완료: data/raw/{k_date_str}/kofia_bond_yield.xlsx")
                st.info("새 데이터를 반영하려면 페이지를 새로고침(F5)하세요.")
            else:
                st.error("다운로드 실패 — 터미널 로그를 확인해주세요.")

    # 자동 로드된 KOFIA 데이터 표시
    if _kofia_df is not None:
        df_kr   = _kofia_df
        df_melt = df_kr.reset_index().melt(
            id_vars="Date", var_name="Tenor", value_name="Yield (%)"
        )
        fig_kr = px.line(
            df_melt, x="Date", y="Yield (%)", color="Tenor",
            title="KOFIA 국채 최종호가 수익률",
        )
        fig_kr.update_layout(hovermode="x unified")
        st.plotly_chart(fig_kr, use_container_width=True)
        st.dataframe(df_kr, use_container_width=True)
    else:
        st.info(
            "KOFIA 데이터 파일이 없습니다.  \n"
            "위 [KOFIA 데이터 새로 다운로드] 섹션에서 먼저 데이터를 수집해주세요."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: 병합 데이터 (글로벌 + KR, 전체 달력 날짜)
# ══════════════════════════════════════════════════════════════════════════════
with tab_merged:
    st.caption(
        "글로벌 국채 금리 + KOFIA KR 금리 병합  ·  "
        "주말·공휴일은 직전 거래일 값으로 채워짐 (forward fill)"
    )

    if _merged_df is None:
        st.info("데이터를 불러오지 못했습니다.")
    else:
        df_m     = _merged_df
        all_cols = df_m.columns.tolist()
        selected = st.multiselect(
            "표시할 시리즈",
            options=all_cols,
            default=[c for c in ["US_10Y", "DE_10Y", "JP_10Y", "KR_10Y"] if c in all_cols],
            key="m_cols",
        )

        if selected:
            df_melt = df_m[selected].reset_index().melt(
                id_vars="Date", var_name="Series", value_name="Yield (%)"
            )
            fig_m = px.line(
                df_melt, x="Date", y="Yield (%)", color="Series",
                title="글로벌 + KR 국채 금리 (전체 달력 날짜)",
            )
            fig_m.update_layout(hovermode="x unified")
            st.plotly_chart(fig_m, use_container_width=True)

        st.dataframe(df_m, use_container_width=True)
