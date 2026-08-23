"""
학습구간(과거 70%)에서 여러 파라미터 조합을 탐색하고, 검증구간(최근 30%, 탐색에 전혀
사용 안 한 데이터)에서 그 결과가 재현되는지 확인한다.

왜 이렇게 하나: 같은 전체 데이터로 계속 조정->확인을 반복하면, 우연히 그 데이터에만
잘 맞는 조합을 '진짜 좋은 전략'으로 착각하기 쉽다(과최적화/데이터 스누핑).
학습구간에서 고른 조합이 한 번도 보지 않은 검증구간에서도 비슷하게 나와야
실제로 신뢰할 수 있는 결과다.

실행:
    python3 scripts/grid_search.py
"""

import itertools

import pandas as pd

from indicators import add_indicators
from upbit_data import fetch_top_markets_by_value, load_or_fetch

UNIVERSE_SIZE = 20
TRAIN_RATIO = 0.7
HOLD_DAYS = 3
COST_RATE = 0.0015  # 수수료+슬리피지 (매수/매도 각각)

TARGET_STOP_COMBOS = [(4, 2.5), (5, 3), (6, 3.5), (5, 2.5), (4, 3)]
VOL_MULTS = [1.3, 1.5, 2.0]


def simulate(df_ind: pd.DataFrame, market: str, vol_mult: float, target_pct: float, stop_pct: float):
    """돌파매매 조건을 파라미터화해서 백테스트. strategy.py의 실제 로직과 동일한 구조."""
    trades = []
    i = 0
    n = len(df_ind)
    while i < n - 1:
        row = df_ind.iloc[i]
        if pd.isna(row["ma60"]) or pd.isna(row["high20"]):
            i += 1
            continue

        is_breakout = row["close"] > row["high20"]
        is_vol_ok = row["vol_ratio"] >= vol_mult
        is_not_overextended = row["daily_return_pct"] <= 15.0
        is_uptrend = row["ma20"] > row["ma60"]

        if not (is_breakout and is_vol_ok and is_not_overextended and is_uptrend):
            i += 1
            continue

        entry_idx = i + 1
        entry_row = df_ind.iloc[entry_idx]
        entry_price = entry_row["open"] * (1 + COST_RATE)
        target_price = entry_price * (1 + target_pct / 100)
        stop_price = entry_price * (1 - stop_pct / 100)

        exit_idx, exit_price, exit_reason = None, None, None
        for offset in range(HOLD_DAYS):
            day_idx = entry_idx + offset
            if day_idx >= n:
                break
            day = df_ind.iloc[day_idx]
            if day["low"] <= stop_price:
                exit_idx, exit_price, exit_reason = day_idx, stop_price, "stop"
                break
            if day["high"] >= target_price:
                exit_idx, exit_price, exit_reason = day_idx, target_price, "target"
                break

        if exit_idx is None:
            exit_idx = min(entry_idx + HOLD_DAYS - 1, n - 1)
            exit_price = df_ind.iloc[exit_idx]["close"]
            exit_reason = "time"

        eff_exit = exit_price * (1 - COST_RATE)
        ret_pct = (eff_exit / entry_price - 1) * 100
        trades.append({"market": market, "exit_reason": exit_reason, "return_pct": ret_pct})
        i = exit_idx + 1

    return trades


def summarize(trades):
    if not trades:
        return {"n_trades": 0, "win_rate": None, "avg_return_pct": None}
    df = pd.DataFrame(trades)
    wins = (df["return_pct"] > 0).sum()
    return {
        "n_trades": len(df),
        "win_rate": round(wins / len(df) * 100, 1),
        "avg_return_pct": round(df["return_pct"].mean(), 2),
    }


def main():
    print(f"거래대금 상위 {UNIVERSE_SIZE}개 코인 데이터 로딩...")
    markets = fetch_top_markets_by_value(UNIVERSE_SIZE)

    train_data, test_data = {}, {}
    for market in markets:
        try:
            df, _ = load_or_fetch(market, count_days=400)
        except Exception as e:
            print(f"[스킵] {market}: {e}")
            continue
        df_ind = add_indicators(df).reset_index(drop=True)
        split = int(len(df_ind) * TRAIN_RATIO)
        train_data[market] = df_ind.iloc[:split].reset_index(drop=True)
        test_data[market] = df_ind.iloc[split:].reset_index(drop=True)

    print(f"학습구간: 데이터 앞 {int(TRAIN_RATIO*100)}% / 검증구간: 뒤 {int((1-TRAIN_RATIO)*100)}% (완전히 분리)\n")

    grid_results = []
    for vol_mult, (target_pct, stop_pct) in itertools.product(VOL_MULTS, TARGET_STOP_COMBOS):
        all_trades = []
        for market, df_ind in train_data.items():
            all_trades.extend(simulate(df_ind, market, vol_mult, target_pct, stop_pct))
        summary = summarize(all_trades)
        breakeven = stop_pct / (target_pct + stop_pct) * 100
        grid_results.append({
            "vol_mult": vol_mult, "target_pct": target_pct, "stop_pct": stop_pct,
            "breakeven_pct": round(breakeven, 1), **summary,
        })

    df_grid = pd.DataFrame(grid_results)
    df_grid["edge"] = df_grid["win_rate"] - df_grid["breakeven_pct"]  # 양수면 손익분기 초과
    df_grid = df_grid.sort_values("edge", ascending=False)

    print("=" * 70)
    print("학습구간 그리드서치 결과 (edge = 실제승률 - 손익분기승률, 클수록 좋음)")
    print("=" * 70)
    print(df_grid.to_string(index=False))

    best = df_grid.iloc[0]
    print(f"\n최고 조합: 거래량 {best['vol_mult']}배 / 목표 {best['target_pct']}% / 손절 {best['stop_pct']}%")
    print(f"  (학습구간 성적: 승률 {best['win_rate']}%, 평균수익률 {best['avg_return_pct']}%, 표본 {best['n_trades']}건)")

    print("\n" + "=" * 70)
    print("이 조합을 검증구간(한 번도 안 본 데이터)에 그대로 적용한 결과")
    print("=" * 70)
    test_trades = []
    for market, df_ind in test_data.items():
        test_trades.extend(simulate(df_ind, market, best["vol_mult"], best["target_pct"], best["stop_pct"]))
    test_summary = summarize(test_trades)
    print(test_summary)
    print(f"손익분기 승률: {best['breakeven_pct']}%")

    if test_summary["n_trades"] and test_summary["win_rate"] is not None:
        if test_summary["win_rate"] >= best["breakeven_pct"]:
            print("\n[결과] 검증구간에서도 손익분기점을 넘었습니다. 우연이 아닐 가능성이 있습니다.")
        else:
            print("\n[결과] 검증구간에서는 손익분기점에 못 미쳤습니다. 학습구간 결과는 과최적화였을 가능성이 높습니다.")
    else:
        print("\n[참고] 검증구간에 신호가 거의 없어 판단하기 어렵습니다.")


if __name__ == "__main__":
    main()
