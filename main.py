# python -m streamlit run main.py --server.port 8801


import os
import glob
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta, date

from modules.collector.kofia_bond import KofiaBondCollector
from modules.utils import merge_treasury, build_change_summary, get_ref_value, standardize_kofia


# ─── 기준일 자동 설정: 전일 ────────────────────────────────────────────────────
TARGET_DATE = date.today() - timedelta(days=1)


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

@st.cache_data(ttl=3600, show_spinner="글로벌 금리 데이터 로드 중...")
def _load_global() -> pd.DataFrame | None:
    """data/global_treasury.csv 에서 글로벌 국채 데이터를 로드합니다."""
    csv_path = os.path.join("data", "global_treasury.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        df.index.name = "Date"
        return df
    except Exception as e:
        print(f"[글로벌] 파일 읽기 오류: {e}")
        return None


def _load_latest_kofia() -> pd.DataFrame | None:
    """data/raw/*/kofia_bond_yield.xlsx 중 가장 최근 파일을 직접 로드합니다.
    (클라우드 환경에서 download_dir 경로 오류를 방지하기 위해 파일 경로를 직접 사용)
    """
    pattern = os.path.join("data", "raw", "*", "kofia_bond_yield.xlsx")
    files   = sorted(glob.glob(pattern))
    if not files:
        return None
    latest = files[-1]
    try:
        df = pd.read_excel(latest, engine="openpyxl")
        return standardize_kofia(df)
    except Exception as e:
        print(f"[KOFIA] 파일 읽기 오류: {e}")
        return None


# ─── 앱 시작 시 사전 계산 (탭 렌더링 전) ─────────────────────────────────────

_global_df: pd.DataFrame | None = _load_global()
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

tab_analysis, tab_rawdata = st.tabs(["Analysis", "Raw Data"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Analysis
# ══════════════════════════════════════════════════════════════════════════════
with tab_analysis:
    [subtab_global] = st.tabs(["글로벌 국채 금리"])

    with subtab_global:
        st.caption(
            f"Source: investing.com + KOFIA  ·  기준일: {TODAY_STR}  ·  "
            "주말·공휴일은 직전 거래일 값으로 채워짐"
        )

        if _merged_df is None:
            st.error(
                "데이터 파일이 없습니다.  \n"
                "로컬 PC에서 `python collect_data.py` 실행 후 `git push` 해주세요."
            )
        else:
            # ── 섹션 1: 주요 금리 변화 현황 ─────────────────────────────────────
            st.subheader("주요국 금리 동향")
            st.caption("2년물 / 10년물 기준  ·  bp = basis point (0.01%p)")

            summary_df = build_change_summary(_merged_df, target_date=TARGET_DATE)

            def _color_bp(val):
                if pd.isna(val):
                    return ""
                if isinstance(val, (int, float)):
                    if val > 0:
                        return "color: #ff4b4b"
                    if val < 0:
                        return "color: #0068c9"
                return ""

            format_dict = {}
            for col in summary_df.columns:
                col_label = col[1] if isinstance(col, tuple) else col
                if "%" in col_label:
                    format_dict[col] = "{:.3f}"
                else:
                    format_dict[col] = "{:.1f}"

            styled = summary_df.style.format(format_dict)
            bp_cols = [c for c in summary_df.columns if "금리" not in c[1]]
            styled = styled.map(_color_bp, subset=bp_cols)
            styled = styled.set_properties(**{'text-align': 'center'})
            styled = styled.set_table_styles([
                dict(selector='th', props=[('text-align', 'center')]),
                dict(selector='td', props=[('text-align', 'center')]),
            ])
            st.dataframe(styled, use_container_width=True)

            st.divider()

            # ── 섹션 2: 국가별 금리 커브 ─────────────────────────────────────────
            st.subheader("국가별 Yield Curve")

            COUNTRY_MAP = {
                "US": "미국", "KR": "한국", "DE": "독일",
                "GB": "영국", "JP": "일본", "CN": "중국",
            }

            avail_countries = [
                c for c in COUNTRIES
                if any(f"{c}_{t}Y" in _merged_df.columns for t in TENORS)
            ]

            selected_code = st.selectbox(
                "국가 선택",
                options=avail_countries,
                format_func=lambda x: COUNTRY_MAP.get(x, x),
                key="curve_country",
            )
            selected_name = COUNTRY_MAP.get(selected_code, selected_code)

            today_curve = _yield_curve_at(_merged_df, selected_code, TODAY)
            week_curve  = _yield_curve_at(_merged_df, selected_code, TODAY - timedelta(days=7))
            month_curve = _yield_curve_at(_merged_df, selected_code, TODAY - timedelta(days=30))

            tenor_labels = [f"{t}Y" for t in TENORS]

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

            curve_data = {
                "현재(%)": today_curve.values,
                "1W(bp)":  (today_curve - week_curve).values * 100,
                "1M(bp)":  (today_curve - month_curve).values * 100,
            }
            curve_table = pd.DataFrame(curve_data, index=pd.Index(tenor_labels, name="만기"))

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
            curve_styled = curve_styled.set_properties(**{'text-align': 'center'})
            curve_styled = curve_styled.set_table_styles([
                dict(selector='th', props=[('text-align', 'center')]),
            ])
            st.dataframe(curve_styled, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Raw Data
# ══════════════════════════════════════════════════════════════════════════════
with tab_rawdata:
    [subtab_global_raw] = st.tabs(["글로벌 국채 금리"])

    with subtab_global_raw:
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

            df_m_styled = df_m.style.set_properties(**{'text-align': 'center'}).set_table_styles([
                dict(selector='th', props=[('text-align', 'center')]),
            ])
            st.dataframe(df_m_styled, use_container_width=True)
