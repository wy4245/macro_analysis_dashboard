"""
MAT 공용 유틸리티

fill_calendar       : 주말·공휴일을 포함한 전체 달력 날짜로 forward fill
standardize_kofia   : KOFIA raw DataFrame → KR_2Y … KR_30Y + 달력 fill
merge_treasury      : GlobalTreasuryCollector 결과 + KOFIA 표준화 결과 병합
get_ref_value       : ref_date 이하 가장 가까운 날짜의 행 반환
build_change_summary: 2Y/10Y 금리 + 1D/1W/MTD/YTD/YoY 변화량(bp) 요약 테이블
"""

import re
import pandas as pd


def fill_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """
    주말·공휴일을 포함한 전체 달력 날짜(일별)로 reindex 후 forward fill.

    토요일·일요일·공휴일처럼 데이터가 없는 날은 직전 거래일 값으로 채웁니다.
    인덱스는 pd.DatetimeIndex(freq='D')로 설정됩니다.

    Args:
        df: Date 인덱스(date 또는 datetime)를 가진 DataFrame

    Returns:
        전체 달력 날짜로 확장·fill된 DataFrame
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    full = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full)
    df = df.ffill()
    df.index.name = "Date"
    return df


def standardize_kofia(df: pd.DataFrame) -> pd.DataFrame:
    """
    KofiaBondCollector.load_excel() 결과를 표준 형식으로 변환합니다.

    변환 내용:
      - 첫 번째 컬럼(일자)을 DatetimeIndex로 설정
      - 수익률 컬럼을 KR_2Y, KR_3Y, KR_5Y, KR_10Y, KR_20Y, KR_30Y 로 변환
        패턴: 컬럼명 내 '(숫자년)' 형식에서 숫자 추출
      - fill_calendar 적용 (주말·공휴일 ffill)

    Args:
        df: KofiaBondCollector.load_excel() 반환 DataFrame

    Returns:
        Date 인덱스, KR_{n}Y 컬럼 형식의 DataFrame.
        인식된 컬럼이 없으면 ValueError.
    """
    df = df.copy()

    # 첫 컬럼 = 날짜
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    df.index.name = "Date"

    # 컬럼명에서 만기(숫자) 추출: '(2년)', '(10년)' 등
    # \ub144 = '년' (한글 유니코드)
    rename_map: dict[str, str] = {}
    for col in df.columns:
        m = re.search(r"\((\d+)\ub144\)", str(col))
        if m:
            rename_map[col] = f"KR_{m.group(1)}Y"

    if not rename_map:
        raise ValueError(
            "KOFIA 컬럼에서 만기를 인식할 수 없습니다. "
            f"실제 컬럼: {df.columns.tolist()}"
        )

    df = df.rename(columns=rename_map)

    # KR_*Y 컬럼만 남기고 만기 오름차순 정렬
    kr_cols = sorted(
        [c for c in df.columns if re.match(r"KR_\d+Y$", c)],
        key=lambda x: int(re.search(r"\d+", x).group()),
    )
    df = df[kr_cols]
    df = df.apply(pd.to_numeric, errors="coerce")

    return fill_calendar(df)


def get_ref_value(df: pd.DataFrame, ref_date) -> pd.Series:
    """
    ref_date 이하 가장 가까운 날짜의 행을 반환합니다.

    Args:
        df     : DatetimeIndex를 가진 DataFrame
        ref_date: 기준 날짜 (date / datetime / str)

    Returns:
        해당 날짜의 pd.Series. 해당 날짜 이전 데이터가 없으면 NaN Series.
    """
    avail = df.index[df.index <= pd.Timestamp(ref_date)]
    if len(avail) == 0:
        return pd.Series(float("nan"), index=df.columns, dtype=float)
    return df.loc[avail[-1]]


def build_change_summary(df: pd.DataFrame, target_date=None) -> pd.DataFrame:
    """
    2Y / 10Y 금리와 1D / 1W / MTD / YTD / YoY 변화량(bp) 요약 테이블을 생성합니다.
    (MultiIndex 컬럼 구조, 한국어 국가명, 소수점 3자리 포맷팅용 raw value 반환)

    Args:
        df: DatetimeIndex, 컬럼 '{CC}_{n}Y' 형식의 병합 DataFrame
        target_date: 기준일 (없으면 df의 마지막 날짜 사용)

    Returns:
        MultiIndex DataFrame
        - Index: 미국, 한국, 독일, 영국, 일본, 중국
        - Columns: (2년물, 금리 (%)), (2년물, 1D), ... (10년물, 금리 (%)), ...
    """
    if target_date is None:
        today = df.index.max()
    else:
        today = pd.Timestamp(target_date)

    # 데이터가 해당 날짜에 없을 수 있으므로 가장 가까운 과거 날짜 사용
    today_vals = get_ref_value(df, today)
    
    # 레퍼런스 날짜 계산
    ref_infos = [
        ("1D",  today - pd.Timedelta(days=1)),
        ("1W",  today - pd.Timedelta(days=7)),
        ("MTD", pd.Timestamp(today.year, today.month, 1) - pd.Timedelta(days=1)),
        ("YTD", pd.Timestamp(today.year - 1, 12, 31)),
        ("YoY", today - pd.DateOffset(years=1)),
    ]

    # 국가 순서 및 매핑 (요청: 미국, 한국, 독일, 영국, 일본, 중국)
    country_map = {
        "US": "미국",
        "KR": "한국",
        "DE": "독일",
        "GB": "영국",
        "JP": "일본",
        "CN": "중국"
    }
    ordered_codes = ["US", "KR", "DE", "GB", "JP", "CN"]
    
    # 결과 담을 딕셔너리 구조
    # data[country_name][(tenor_label, col_label)] = value
    data = {}

    for code in ordered_codes:
        c_name = country_map.get(code, code)
        data[c_name] = {}
        
        for tenor in [2, 10]:
            tenor_label = f"{tenor}년물"
            col_key = f"{code}_{tenor}Y"
            
            # 현재 금리
            curr = today_vals.get(col_key, float("nan")) if col_key in today_vals.index else float("nan")
            
            # (2년물, 금리 (%))
            data[c_name][(tenor_label, f"금리 (%)")] = curr

            # 변화량 계산 (bp)
            for label, ref_date in ref_infos:
                ref_vals = get_ref_value(df, ref_date)
                ref = ref_vals.get(col_key, float("nan")) if col_key in ref_vals.index else float("nan")
                
                diff = float("nan")
                if pd.notna(curr) and pd.notna(ref):
                    diff = (curr - ref) * 100  # bp 단위
                
                # (2년물, 1D), (2년물, 1W) ...
                data[c_name][(tenor_label, label)] = diff

    # DataFrame 생성
    df_result = pd.DataFrame.from_dict(data, orient='index')
    
    # MultiIndex 컬럼 정렬을 위해 튜플 리스트 생성
    # 원하는 순서: 2년물 -> [금리, 1D, 1W, MTD, YTD, YoY], 그 다음 10년물 -> [...]
    cols = []
    for t in ["2년물", "10년물"]:
        cols.append((t, f"금리 (%)"))
        for label, _ in ref_infos:
            cols.append((t, label))
            
    df_result.columns = pd.MultiIndex.from_tuples(df_result.columns)
    df_result = df_result[cols]  # 컬럼 순서 재배치
    
    df_result.index.name = "구분"
    return df_result


def merge_treasury(
    global_df: pd.DataFrame,
    kr_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    GlobalTreasuryCollector 결과와 KOFIA 표준화 결과를 병합합니다.

    처리 순서:
      1. 두 df 모두 이미 fill_calendar / standardize_kofia 적용된 상태로 받음
      2. outer join → 병합 후 날짜 경계의 빈 값 ffill → 날짜 오름차순 정렬

    Args:
        global_df: GlobalTreasuryCollector.collect() 반환 DataFrame (fill 완료)
        kr_df    : KofiaBondCollector.load_excel() 반환 DataFrame (fill 완료)

    Returns:
        전체 달력 날짜 기준으로 정렬된 병합 DataFrame
    """
    g = global_df.copy()
    g.index = pd.to_datetime(g.index)

    k = kr_df.copy()
    k.index = pd.to_datetime(k.index)

    merged = g.join(k, how="outer")
    merged = merged.ffill()
    merged = merged.sort_index()
    return merged
