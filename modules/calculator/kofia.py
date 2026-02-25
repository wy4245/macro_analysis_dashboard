"""
KOFIA 데이터 표준화 / 가공

KofiaCalc
  fill_calendar(df)     : 전체 달력 날짜로 reindex 후 forward fill
  standardize(df)       : TreasurySummary raw DataFrame → KR_nY 컬럼 형식
  standardize_bond(df)  : BondSummary raw DataFrame → 영문 코드 컬럼 형식
    컬럼 코드: KTB_nY, NHB_5Y, MSB_91D/nY, KEPCO_3Y, KDB_1Y,
               CORP_AA_3Y, CORP_BBB_3Y, CD_91D, CP_91D
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

    # ── BondSummary 표준화 ────────────────────────────────────────────────────

    @staticmethod
    def _bond_col_code(s: str) -> str | None:
        """
        KOFIA 채권명 문자열에서 영문 코드를 추출합니다.
        멀티레벨 헤더 잔재('최종호가수익률_국고채(1년)' 등)도 처리합니다.
        매핑 불가 시 None 반환 → 해당 컬럼은 standardize_bond에서 제외됩니다.
        """
        # 공백·개행 제거 후 매칭 (XLS 헤더에 \n이 포함될 수 있음)
        s = re.sub(r"\s+", "", s)
        # 국고채(n년) / 국고채권(n년)
        m = re.search(r"국고채[권]?\((\d+)년\)", s)
        if m:
            return f"KTB_{m.group(1)}Y"
        # 국민주택1종(n년)
        if "국민주택" in s:
            m = re.search(r"\((\d+)년\)", s)
            return f"NHB_{m.group(1)}Y" if m else None
        # 통안증권
        if "통안" in s:
            if "91" in s:
                return "MSB_91D"
            m = re.search(r"\((\d+)년\)", s)
            return f"MSB_{m.group(1)}Y" if m else None
        # 한전채(n년)
        if "한전" in s:
            m = re.search(r"\((\d+)년\)", s)
            return f"KEPCO_{m.group(1)}Y" if m else None
        # 산금채(n년)
        if "산금" in s:
            m = re.search(r"\((\d+)년\)", s)
            return f"KDB_{m.group(1)}Y" if m else None
        # 회사채 AA- / BBB-
        if "회사채" in s:
            if "AA" in s:
                return "CORP_AA_3Y"
            if "BBB" in s:
                return "CORP_BBB_3Y"
            return None
        # CD수익률(91일)
        if "CD" in s:
            return "CD_91D"
        # CP(91일)
        if "CP" in s:
            return "CP_91D"
        return None

    @staticmethod
    def standardize_bond(df: pd.DataFrame) -> pd.DataFrame:
        """
        BondSummary.collect() 결과를 표준 형식으로 변환.

        변환 내용:
          - Date 컬럼 → DatetimeIndex (오름차순 정렬)
          - 한글 채권명 → 영문 코드 (KTB_nY, MSB_nY 등)
          - 매핑 불가 컬럼 제거 (멀티레벨 헤더 잔재 등)
          - fill_calendar 적용 (주말·공휴일 forward fill)

        Args:
            df: BondSummary.collect() 반환 DataFrame (Date 컬럼 포함)

        Returns:
            Date 인덱스, 영문 코드 컬럼 형식의 DataFrame.

        Raises:
            ValueError: 매핑 가능한 채권 컬럼을 하나도 인식할 수 없는 경우
        """
        df = df.copy()

        # Date 인덱스 설정
        date_col = next(
            (c for c in df.columns if "Date" in str(c) or "일자" in str(c)),
            df.columns[0],
        )
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        df.index.name = "Date"
        df = df.sort_index(ascending=True)

        # 영문 코드 매핑 (매핑 안 되는 컬럼은 제외)
        rename_map: dict[str, str] = {}
        for col in df.columns:
            code = KofiaCalc._bond_col_code(str(col))
            if code:
                rename_map[col] = code

        if not rename_map:
            raise ValueError(
                "BondSummary 컬럼에서 채권명을 인식할 수 없습니다. "
                f"실제 컬럼: {df.columns.tolist()}"
            )

        dropped = [c for c in df.columns if c not in rename_map]
        if dropped:
            print(f"  [표준화] 제외된 컬럼 ({len(dropped)}개): {dropped}")

        df = df[list(rename_map.keys())]
        df = df.rename(columns=rename_map)
        df = df.apply(pd.to_numeric, errors="coerce")

        # 컬럼 순서 정렬 (KTB → NHB → MSB → KEPCO → KDB → CORP → CD → CP)
        prefix_order = ["KTB", "NHB", "MSB", "KEPCO", "KDB", "CORP", "CD", "CP"]

        def _col_sort_key(c: str) -> tuple:
            for i, prefix in enumerate(prefix_order):
                if c.startswith(prefix):
                    num = re.search(r"\d+", c)
                    return (i, int(num.group()) if num else 0)
            return (len(prefix_order), 0)

        sorted_cols = sorted(df.columns, key=_col_sort_key)
        df = df[sorted_cols]

        return KofiaCalc.fill_calendar(df)
