# python -m streamlit run main.py --server.port 8801


import os
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta, date

from modules.calculator.global_treasury import TreasuryCalc


# ─── 페이지 기본 설정 ──────────────────────────────────────────────────────────
st.set_page_config(page_title="MMS", layout="wide")
st.title("MMS(Macro Monitoring System)")

COUNTRIES = ["KR", "US", "DE", "GB", "JP", "CN"]
TENORS    = [2, 3, 5, 10, 20, 30]


# ─── 데이터 로드 ──────────────────────────────────────────────────────────────

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


def _load_bond() -> pd.DataFrame | None:
    """data/bond_summary.csv 에서 국내 채권 데이터를 로드합니다."""
    csv_path = os.path.join("data", "bond_summary.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        df.index.name = "Date"
        return df
    except Exception as e:
        print(f"[BondSummary] 파일 읽기 오류: {e}")
        return None


# ─── 앱 시작 시 사전 계산 ────────────────────────────────────────────────────

_global_df: pd.DataFrame | None = _load_global()
_bond_df:   pd.DataFrame | None = _load_bond()

# bond_summary의 KTB_nY 컬럼을 KR_nY 형식으로 변환하여 글로벌 데이터와 병합
_merged_df: pd.DataFrame | None = None
if _global_df is not None and _bond_df is not None:
    _ktb_to_kr = {f"KTB_{t}Y": f"KR_{t}Y" for t in TENORS if f"KTB_{t}Y" in _bond_df.columns}
    _kr_df = _bond_df[list(_ktb_to_kr.keys())].rename(columns=_ktb_to_kr)
    _merged_df = TreasuryCalc.merge(_global_df, _kr_df)
elif _global_df is not None:
    _merged_df = _global_df


# ─── 기준일: 실제 데이터의 마지막 날짜 ──────────────────────────────────────────

_candidates = []
if _merged_df is not None and not _merged_df.empty:
    _candidates.append(_merged_df.index.max().date())
if _bond_df is not None and not _bond_df.empty:
    _candidates.append(_bond_df.index.max().date())
TARGET_DATE = max(_candidates) if _candidates else date.today() - timedelta(days=1)

TODAY     = TARGET_DATE
TODAY_STR = TODAY.strftime("%Y-%m-%d")
try:
    START_DATE = TODAY.replace(year=TODAY.year - 1)
except ValueError:  # 2월 29일인 경우
    START_DATE = TODAY - timedelta(days=365)
START_STR = START_DATE.strftime("%Y-%m-%d")


# ─── 채권 종목 한글 레이블 ────────────────────────────────────────────────────

BOND_LABELS: dict[str, str] = {
    "KTB_1Y": "국고채(1년)",    "KTB_2Y": "국고채(2년)",   "KTB_3Y": "국고채(3년)",
    "KTB_5Y": "국고채(5년)",    "KTB_10Y": "국고채(10년)", "KTB_20Y": "국고채(20년)",
    "KTB_30Y": "국고채(30년)",  "KTB_50Y": "국고채(50년)",
    "NHB_5Y":  "국민주택1종(5년)",
    "MSB_91D": "통안증권(91일)", "MSB_1Y": "통안증권(1년)", "MSB_2Y": "통안증권(2년)",
    "KEPCO_3Y": "한전채(3년)",  "KDB_1Y": "산금채(1년)",
    "CORP_AA_3Y": "회사채AA-(3년)", "CORP_BBB_3Y": "회사채BBB-(3년)",
    "CD_91D": "CD(91일)",       "CP_91D": "CP(91일)",
}

# KTB 만기 순서
KTB_TENORS = [1, 2, 3, 5, 10, 20, 30, 50]


def _build_bond_summary(df: pd.DataFrame, target_date) -> pd.DataFrame:
    """각 채권 시리즈의 현재 금리 + 변화량(bp) 요약 테이블."""
    today = pd.Timestamp(target_date)
    ref_infos = [
        ("1D",  today - pd.Timedelta(days=1)),
        ("1W",  today - pd.Timedelta(days=7)),
        ("MTD", pd.Timestamp(today.year, today.month, 1) - pd.Timedelta(days=1)),
        ("YTD", pd.Timestamp(today.year - 1, 12, 31)),
        ("YoY", today - pd.DateOffset(years=1)),
    ]
    today_vals = TreasuryCalc.get_ref_value(df, today)
    rows: dict = {}
    for col in df.columns:
        label = BOND_LABELS.get(col, col)
        curr  = today_vals.get(col, float("nan")) if col in today_vals.index else float("nan")
        row: dict = {"금리 (%)": curr}
        for ref_label, ref_date in ref_infos:
            ref_vals = TreasuryCalc.get_ref_value(df, ref_date)
            ref      = ref_vals.get(col, float("nan")) if col in ref_vals.index else float("nan")
            row[ref_label] = (curr - ref) * 100 if pd.notna(curr) and pd.notna(ref) else float("nan")
        rows[label] = row
    result = pd.DataFrame.from_dict(rows, orient="index")
    result.index.name = "종목"
    return result


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
    subtab_global, subtab_bond = st.tabs(["글로벌 국채 금리", "국내 채권 금리"])

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

            summary_df = TreasuryCalc.build_change_summary(_merged_df, target_date=TARGET_DATE)

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

            styled = summary_df.style.format(format_dict, na_rep="-")
            bp_cols = [c for c in summary_df.columns if "금리" not in c[1]]
            styled = styled.map(_color_bp, subset=bp_cols)
            styled = styled.set_properties(**{'text-align': 'center'})
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
            }, na_rep="-")
            curve_styled = curve_styled.map(_color_curve_bp, subset=["1W(bp)", "1M(bp)"])
            curve_styled = curve_styled.set_properties(**{'text-align': 'center'})
            st.dataframe(curve_styled, use_container_width=True)


    with subtab_bond:
        st.caption(
            f"Source: KOFIA  ·  기준일: {TODAY_STR}  ·  "
            "주말·공휴일은 직전 거래일 값으로 채워짐"
        )

        if _bond_df is None:
            st.error(
                "데이터 파일이 없습니다.  \n"
                "로컬 PC에서 `python collect_data.py` 실행 후 `git push` 해주세요."
            )
        else:
            # ── 섹션 1: 국내 채권 금리 동향 ──────────────────────────────────────
            st.subheader("국내 채권 금리 동향")
            st.caption("단위: 금리 (%), 변화 bp (0.01%p)")

            bond_summary_df = _build_bond_summary(_bond_df, TARGET_DATE)

            bond_format = {"금리 (%)": "{:.3f}", "1D": "{:.1f}", "1W": "{:.1f}",
                           "MTD": "{:.1f}", "YTD": "{:.1f}", "YoY": "{:.1f}"}
            bp_cols_bond = [c for c in bond_summary_df.columns if c != "금리 (%)"]

            def _color_bp_bond(val):
                if pd.isna(val):
                    return ""
                if isinstance(val, (int, float)):
                    if val > 0:
                        return "color: #ff4b4b"
                    if val < 0:
                        return "color: #0068c9"
                return ""

            bond_styled = (
                bond_summary_df.style
                .format(bond_format, na_rep="-")
                .map(_color_bp_bond, subset=bp_cols_bond)
                .set_properties(**{"text-align": "center"})
            )
            st.dataframe(bond_styled, use_container_width=True)

            st.divider()

            # ── 섹션 2: 국고채 Yield Curve ───────────────────────────────────────
            ktb_avail = [t for t in KTB_TENORS if f"KTB_{t}Y" in _bond_df.columns]

            if ktb_avail:
                st.subheader("국내 채권 Yield Curve")

                ktb_tenor_labels = [f"{t}Y" for t in ktb_avail]
                ktb_cols         = [f"KTB_{t}Y" for t in ktb_avail]

                def _ktb_curve_at(ref_date) -> pd.Series:
                    avail_idx = _bond_df.index[_bond_df.index <= pd.Timestamp(ref_date)]
                    if len(avail_idx) == 0:
                        return pd.Series(float("nan"), index=ktb_avail, dtype=float)
                    row = _bond_df.loc[avail_idx[-1], ktb_cols]
                    return pd.Series(row.values, index=ktb_avail, dtype=float)

                today_ktb = _ktb_curve_at(TODAY)
                week_ktb  = _ktb_curve_at(TODAY - timedelta(days=7))
                month_ktb = _ktb_curve_at(TODAY - timedelta(days=30))

                fig_ktb = go.Figure()
                if not today_ktb.dropna().empty:
                    fig_ktb.add_trace(go.Scatter(
                        x=ktb_tenor_labels, y=today_ktb.values,
                        mode="lines+markers", name=f"현재 ({TODAY_STR})",
                        line=dict(width=2.5),
                    ))
                if not week_ktb.dropna().empty:
                    fig_ktb.add_trace(go.Scatter(
                        x=ktb_tenor_labels, y=week_ktb.values,
                        mode="lines+markers", name="1주 전",
                        line=dict(dash="dot", width=1.5),
                        opacity=0.8,
                    ))
                if not month_ktb.dropna().empty:
                    fig_ktb.add_trace(go.Scatter(
                        x=ktb_tenor_labels, y=month_ktb.values,
                        mode="lines+markers", name="1개월 전",
                        line=dict(dash="dash", width=1.5),
                        opacity=0.8,
                    ))
                fig_ktb.update_layout(
                    title="국고채 금리 커브",
                    xaxis_title="만기",
                    yaxis_title="수익률 (%)",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_ktb, use_container_width=True)

                ktb_curve_data = {
                    "현재(%)": today_ktb.values,
                    "1W(bp)":  (today_ktb - week_ktb).values * 100,
                    "1M(bp)":  (today_ktb - month_ktb).values * 100,
                }
                ktb_curve_table = pd.DataFrame(
                    ktb_curve_data,
                    index=pd.Index(ktb_tenor_labels, name="만기"),
                )
                ktb_styled = (
                    ktb_curve_table.style
                    .format({"현재(%)": "{:.3f}", "1W(bp)": "{:.1f}", "1M(bp)": "{:.1f}"}, na_rep="-")
                    .map(_color_bp_bond, subset=["1W(bp)", "1M(bp)"])
                    .set_properties(**{"text-align": "center"})
                )
                st.dataframe(ktb_styled, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Raw Data
# ══════════════════════════════════════════════════════════════════════════════
with tab_rawdata:
    subtab_global_raw, subtab_bond_raw = st.tabs(["글로벌 국채 금리", "국내 채권 금리"])

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

            df_m_display = df_m.copy()
            df_m_display.index = df_m_display.index.strftime("%Y-%m-%d")
            df_m_styled = (
                df_m_display.style
                .format("{:.3f}", na_rep="-")
                .set_properties(**{'text-align': 'center'})
            )
            st.dataframe(df_m_styled, use_container_width=True)

    with subtab_bond_raw:
        st.caption(
            "KOFIA 전종목 최종호가수익률  ·  "
            "주말·공휴일은 직전 거래일 값으로 채워짐 (forward fill)"
        )

        if _bond_df is None:
            st.info("데이터를 불러오지 못했습니다.")
        else:
            bond_all_cols     = _bond_df.columns.tolist()
            bond_default_cols = [c for c in ["KTB_10Y", "KTB_3Y", "CORP_AA_3Y", "CD_91D"] if c in bond_all_cols]
            if not bond_default_cols:
                bond_default_cols = bond_all_cols[:4]

            bond_selected = st.multiselect(
                "표시할 시리즈",
                options=bond_all_cols,
                format_func=lambda x: f"{BOND_LABELS.get(x, x)} ({x})",
                default=bond_default_cols,
                key="bond_cols",
            )

            if bond_selected:
                df_bond_melt = _bond_df[bond_selected].reset_index().melt(
                    id_vars="Date", var_name="Series", value_name="Yield (%)"
                )
                df_bond_melt["Series"] = df_bond_melt["Series"].map(
                    lambda x: f"{BOND_LABELS.get(x, x)} ({x})"
                )
                fig_bond = px.line(
                    df_bond_melt, x="Date", y="Yield (%)", color="Series",
                    title="국내 채권 금리 시계열",
                )
                fig_bond.update_layout(hovermode="x unified")
                st.plotly_chart(fig_bond, use_container_width=True)

            df_bond_display = _bond_df.copy()
            df_bond_display.index = df_bond_display.index.strftime("%Y-%m-%d")
            df_bond_display.columns = [
                f"{BOND_LABELS.get(c, c)} ({c})" for c in df_bond_display.columns
            ]
            df_bond_styled = (
                df_bond_display.style
                .format("{:.3f}", na_rep="-")
                .set_properties(**{"text-align": "center"})
            )
            st.dataframe(df_bond_styled, use_container_width=True)
