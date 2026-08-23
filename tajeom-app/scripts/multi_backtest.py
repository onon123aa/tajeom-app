"""
코인 하나만 보면 표본이 너무 적어서(9번 등) 우연인지 실력인지 구분이 안 됨.
거래대금 상위 여러 코인을 합쳐서 전체 승률/평균수익률을 계산해 통계적 신뢰도를 높인다.

실행:
    python3 scripts/multi_backtest.py

TARGET_PCT/STOP_PCT는 strategy.py에서 가져오므로, 그 값을 바꾸면 여기 결과도 같이 바뀐다.
여러 목표/손절 조합을 비교하고 싶으면 strategy.py의 TARGET_PCT, STOP_PCT를 바꿔가며
이 스크립트를 반복 실행해서 결과를 비교하면 된다.
"""

import pandas as pd

from backtest import run_backtest, summarize
from strategy import TARGET_PCT, STOP_PCT, HOLD_DAYS
from upbit_data import fetch_top_markets_by_value, load_or_fetch

UNIVERSE_SIZE = 30      # 거래대금 상위 N개 마켓만 스캔 (표본 확대: 15 -> 30)


def main():
    print(f"설정: 목표 +{TARGET_PCT}% / 손절 {STOP_PCT}% / 보유 {HOLD_DAYS}일")
    print(f"거래대금 상위 {UNIVERSE_SIZE}개 코인으로 백테스트 시작...\n")

    markets = fetch_top_markets_by_value(UNIVERSE_SIZE)
    all_trades = []
    per_market_rows = []

    for market in markets:
        try:
            df, report = load_or_fetch(market, count_days=400)
        except Exception as e:
            print(f"[스킵] {market}: {e}")
            continue

        trades = run_backtest(df, market)
        all_trades.extend(trades)
        summary = summarize(trades)
        per_market_rows.append({"market": market, **summary})
        print(f"  {market}: {summary}")

    print("\n" + "=" * 60)
    print(f"전체 합산 결과 (코인 {len(markets)}개, 신호 {len(all_trades)}건)")
    print("=" * 60)

    overall = summarize(all_trades)
    for k, v in overall.items():
        print(f"  {k}: {v}")

    if per_market_rows:
        df_summary = pd.DataFrame(per_market_rows).sort_values("win_rate", ascending=False, na_position="last")
        print("\n코인별 성과 (승률 높은 순):")
        print(df_summary.to_string(index=False))

    if overall.get("n_trades", 0) < 30:
        print("\n[참고] 표본이 30건 미만입니다. 조건을 더 완화하거나 더 많은 코인/기간으로 늘려서 재확인하는 게 좋습니다.")


if __name__ == "__main__":
    main()
