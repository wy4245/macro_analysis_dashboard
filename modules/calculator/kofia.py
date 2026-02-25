"""
KOFIA 데이터 표준화 / 가공

KofiaCalc
  fill_calendar(df)  : 전체 달력 날짜로 reindex 후 forward fill
  standardize(df)    : load_excel() 결과 → KR_nY 컬럼 형식으로 변환
"""

import re
import pandas as pd


class KofiaCalc:
    """KOFIA 수집 데이터의 표준화 및 캘린더 채움 처리."""

    @staticmethod
    def fill_calendar(df: pd.DataFrame) -> pd.DataFrame:
        """
        주말·공휴일을 포함한 전체 달력 날짜(일별)로 reindex 후 forward fill.

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

    @staticmethod
    def standardize(df: pd.DataFrame) -> pd.DataFrame:
        """
        KofiaBondCollector.load_excel() 결과를 표준 형식으로 변환.

        변환 내용:
          - 첫 번째 컬럼(일자) → DatetimeIndex
          - 컬럼명 '(n년)' 패턴 → KR_nY (예: KR_2Y, KR_10Y)
          - fill_calendar 적용

        Args:
            df: treasury_summary.xlsx 로드 결과 DataFrame

        Returns:
            Date 인덱스, KR_{n}Y 컬럼 형식의 DataFrame.

        Raises:
            ValueError: 만기 컬럼을 인식할 수 없는 경우
        """
        df = df.copy()

        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        df.index.name = "Date"

        rename_map: dict[str, str] = {}
        for col in df.columns:
            m = re.search(r"\((\d+)\ub144\)", str(col))  # '\ub144' = '년'
            if m:
                rename_map[col] = f"KR_{m.group(1)}Y"

        if not rename_map:
            raise ValueError(
                "KOFIA 컬럼에서 만기를 인식할 수 없습니다. "
                f"실제 컬럼: {df.columns.tolist()}"
            )

        df = df.rename(columns=rename_map)

        kr_cols = sorted(
            [c for c in df.columns if re.match(r"KR_\d+Y$", c)],
            key=lambda x: int(re.search(r"\d+", x).group()),
        )
        df = df[kr_cols]
        df = df.apply(pd.to_numeric, errors="coerce")

        return KofiaCalc.fill_calendar(df)
