"""
기술적 지표 계산 모듈

주의: 모든 지표는 '해당 시점까지의 과거 데이터만' 사용해서 계산해야 함(lookahead bias 방지).
      pandas의 rolling/ewm은 기본적으로 과거 데이터만 사용하므로 안전하지만,
      백테스트에서 신호 판단 시 '오늘 종가'를 신호 발생 당일 매수가로 쓰면 안 됨(미래 정보 사용).
      -> backtest.py에서는 signal은 t일 종가 확정 후 계산하고, 매수 체결은 t+1일 시가로 처리한다.
"""

import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    df["rsi14"] = _rsi(df["close"], period=14)

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]

    # 20일선과의 괴리율(%) -> 눌림목 판단용
    df["dist_from_ma20_pct"] = (df["close"] - df["ma20"]) / df["ma20"] * 100

    # 돌파매매용: 오늘을 제외한 과거 20일 최고가, 오늘 하루 등락률
    df["high20"] = df["high"].rolling(20).max().shift(1)
    df["daily_return_pct"] = df["close"].pct_change() * 100

    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # 초기 구간은 중립값으로
    return rsi
