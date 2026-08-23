"""
백테스트 엔진

정확성을 위해 반드시 지킨 규칙:
  1) 룩어헤드 방지: t일 종가로 신호 판단 -> 체결은 t+1일 시가 (실제로 신호를 그날 종가 마감 후에나 알 수 있으므로)
  2) 손절 우선 가정: 같은 날 고가(목표가)와 저가(손절가)가 동시에 조건 충족되면
     보수적으로 손절이 먼저 발생했다고 가정 (실제 장중 순서는 알 수 없으므로 낙관적 가정 금지)
  3) 수수료+슬리피지 반영: 매수/매도 각각 비용 적용 (업비트 taker 수수료 0.05% + 슬리피지 가정치)
  4) 워크포워드 분할: 전체 기간을 N개 구간으로 나눠 구간별 성과를 따로 리포트.
     -> 특정 구간(예: 강세장)에서만 잘 맞는 전략인지, 전 구간에서 안정적인지 구분하기 위함.
     -> 나중에 파라미터를 데이터에 맞춰 최적화하게 되면, 반드시 학습 구간과 검증 구간을 분리해서
        검증 구간 성과만 신뢰해야 함 (학습 구간 성과는 과최적화로 부풀려짐).
  5) 동시 포지션 미허용: 한 종목 기준으로 포지션이 열려 있는 동안은 새 신호를 받지 않음
     (신호 자체의 순수 성과를 측정하기 위함. 실제 앱은 종목별로 독립 운용하면 됨)
"""

from dataclasses import dataclass, asdict

import pandas as pd

from indicators import add_indicators
from strategy import check_signal, HOLD_DAYS, TARGET_PCT, STOP_PCT

FEE_RATE = 0.0005       # 업비트 taker 수수료 0.05%
SLIPPAGE_RATE = 0.001   # 슬리피지 가정 0.1% (보수적으로 여유있게 설정)
COST_RATE = FEE_RATE + SLIPPAGE_RATE  # 매수/매도 각 1회씩 적용


@dataclass
class Trade:
    market: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str          # "target" | "stop_loss" | "time_exit"
    hold_days: int
    confidence: float
    reason: str
    net_return_pct: float


def run_backtest(df: pd.DataFrame, market: str) -> list[Trade]:
    """룩어헤드 없이 순차적으로 신호 -> 체결 -> 청산까지 시뮬레이션."""
    df = add_indicators(df).reset_index(drop=True)
    trades: list[Trade] = []

    i = 0
    n = len(df)
    while i < n - 1:  # 최소 t+1 진입일이 있어야 하므로 마지막 행은 신호 판단 제외
        signal = check_signal(df, i, market)
        if signal is None:
            i += 1
            continue

        entry_idx = i + 1
        entry_row = df.iloc[entry_idx]
        entry_price = entry_row["open"] * (1 + COST_RATE)

        target_price = entry_price * (1 + TARGET_PCT / 100)
        stop_price = entry_price * (1 - abs(STOP_PCT) / 100)

        exit_idx = None
        exit_price = None
        exit_reason = None

        for offset in range(HOLD_DAYS):
            day_idx = entry_idx + offset
            if day_idx >= n:
                break
            day = df.iloc[day_idx]

            if day["low"] <= stop_price:          # 손절 우선 가정(보수적)
                exit_idx, exit_price, exit_reason = day_idx, stop_price, "stop_loss"
                break
            if day["high"] >= target_price:
                exit_idx, exit_price, exit_reason = day_idx, target_price, "target"
                break

        if exit_idx is None:
            exit_idx = min(entry_idx + HOLD_DAYS - 1, n - 1)
            exit_price = df.iloc[exit_idx]["close"]
            exit_reason = "time_exit"

        effective_exit = exit_price * (1 - COST_RATE)
        net_return_pct = round((effective_exit / entry_price - 1) * 100, 2)

        trades.append(
            Trade(
                market=market,
                signal_date=signal.date,
                entry_date=entry_row["date"],
                entry_price=round(entry_price),
                exit_date=df.iloc[exit_idx]["date"],
                exit_price=round(exit_price),
                exit_reason=exit_reason,
                hold_days=exit_idx - entry_idx + 1,
                confidence=signal.confidence,
                reason=signal.reason,
                net_return_pct=net_return_pct,
            )
        )

        i = exit_idx + 1  # 포지션 종료 후부터 다시 탐색 (동시 포지션 미허용)

    return trades


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {"n_trades": 0, "win_rate": None, "avg_return_pct": None}

    df = pd.DataFrame([asdict(t) for t in trades])
    wins = (df["net_return_pct"] > 0).sum()
    return {
        "n_trades": len(df),
        "win_rate": round(wins / len(df) * 100, 1),
        "avg_return_pct": round(df["net_return_pct"].mean(), 2),
        "target_hit": int((df["exit_reason"] == "target").sum()),
        "stop_hit": int((df["exit_reason"] == "stop_loss").sum()),
        "time_exit": int((df["exit_reason"] == "time_exit").sum()),
    }


def walk_forward_report(df: pd.DataFrame, market: str, n_folds: int = 4) -> pd.DataFrame:
    """
    전체 기간을 시간 순서로 n_folds개 구간으로 쪼개서 구간별 성과를 따로 계산.
    한 구간 성과가 유독 좋고 나머지는 별로라면 -> 특정 장세에만 맞는 전략이라는 뜻이므로
    실제 운용 시 주의해야 함.
    """
    df = df.reset_index(drop=True)
    fold_size = len(df) // n_folds
    rows = []

    for f in range(n_folds):
        start = f * fold_size
        end = len(df) if f == n_folds - 1 else (f + 1) * fold_size
        fold_df = df.iloc[start:end].reset_index(drop=True)
        if len(fold_df) < 70:  # 지표 워밍업(60일) + 최소 거래 확인 여유
            continue

        trades = run_backtest(fold_df, market)
        summary = summarize(trades)
        rows.append(
            {
                "fold": f + 1,
                "period_start": fold_df["date"].iloc[0].date(),
                "period_end": fold_df["date"].iloc[-1].date(),
                **summary,
            }
        )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    from upbit_data import load_or_fetch

    market = "KRW-BTC"
    df, data_report = load_or_fetch(market, count_days=400)
    print("데이터 검증:", data_report)

    trades = run_backtest(df, market)
    print("\n전체 백테스트 요약:", summarize(trades))

    print("\n워크포워드(구간별) 리포트:")
    print(walk_forward_report(df, market, n_folds=4))
