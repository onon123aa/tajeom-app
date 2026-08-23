"""
GitHub Actions가 주기적으로 실행하는 메인 스크립트.

하는 일:
  1) 거래대금 상위 마켓들의 최신 일봉 데이터를 받아옴
  2) 이미 활성화된 신호(포지션)는 상태를 유지/만료 처리 (data/state.json)
     - 3일(HOLD_DAYS) 경과, 또는 목표가/손절가 도달 시 만료
     - 매수가/목표가/손절가는 최초 신호 발생 시점 값으로 고정 (매일 다시 계산하지 않음)
  3) 아직 신호가 없던 마켓에서 새 신호가 뜨면 새 포지션으로 등록
     - 등록 시점에 과거 유사 패턴 검색도 함께 계산해서 고정
  4) 활성 포지션을 신뢰도순으로 정렬해 상위 5개를 docs/signals.json으로 출력 (프론트엔드가 읽음)
  5) 이번 실행에서 "새로" 추가된 신호 목록을 data/new_alerts.json으로 출력 (푸시 알림 트리거용)
"""

import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from indicators import add_indicators
from strategy import check_signal, HOLD_DAYS
from upbit_data import fetch_top_markets_by_value, fetch_daily_candles, fetch_krw_markets

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
ALERTS_PATH = ROOT / "data" / "new_alerts.json"
SIGNALS_PATH = ROOT / "docs" / "signals.json"
HISTORY_PATH = ROOT / "data" / "trade_history.json"

UNIVERSE_SIZE = 20      # 거래대금 상위 N개 마켓만 스캔 (유동성 낮은 잡코인 배제 + API 부담 감소)
TOP_DISPLAY = 5
KST = timezone(timedelta(hours=9))


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"positions": {}}


def save_json(path: Path, data: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def find_similar_patterns(df_ind: pd.DataFrame, current_idx: int, lookback: int = 10, hold_days: int = HOLD_DAYS):
    """
    간단한 최근접 이웃 기반 유사 패턴 검색 (DTW 아님, 정규화된 수익률 모양 비교).
    현재 시점 직전 lookback일간의 '수익률 모양(shape)'과 가장 비슷했던 과거 구간들을 찾아
    그 이후 hold_days 동안 실제로 어떻게 됐는지 통계를 낸다.

    주의: 표본이 3건 미만이면 프론트엔드에서 '참고용 아님'으로 표시됨.
    """
    closes = df_ind["close"].values
    returns = np.diff(closes) / closes[:-1]  # returns[i] = (close[i+1]-close[i])/close[i]

    end = current_idx  # 오늘까지
    start = end - lookback
    if start < 0:
        return {"count": 0, "avg_return_pct": 0.0, "win_rate": 0.0}

    current_window = returns[start:end]
    if current_window.std() < 1e-9:
        return {"count": 0, "avg_return_pct": 0.0, "win_rate": 0.0}
    current_norm = (current_window - current_window.mean()) / current_window.std()

    candidates = []
    # 과거 구간 중, 이후 hold_days 결과까지 알 수 있는(미래 데이터가 존재하는) 구간만 후보로 삼음
    for s in range(0, end - lookback - hold_days):
        e = s + lookback
        past_window = returns[s:e]
        if past_window.std() < 1e-9:
            continue
        past_norm = (past_window - past_window.mean()) / past_window.std()
        dist = float(np.linalg.norm(current_norm - past_norm))

        entry_price = closes[e]
        exit_price = closes[min(e + hold_days, len(closes) - 1)]
        fwd_return_pct = (exit_price / entry_price - 1) * 100
        candidates.append((dist, fwd_return_pct))

    if not candidates:
        return {"count": 0, "avg_return_pct": 0.0, "win_rate": 0.0}

    candidates.sort(key=lambda x: x[0])
    dists = [c[0] for c in candidates]
    threshold = np.percentile(dists, 15)  # 거리 하위 15% 이내만 '유사'로 인정
    matched = [c for c in candidates if c[0] <= threshold][:15]

    if not matched:
        return {"count": 0, "avg_return_pct": 0.0, "win_rate": 0.0}

    fwd_returns = [m[1] for m in matched]
    win_rate = sum(1 for r in fwd_returns if r > 0) / len(fwd_returns) * 100

    return {
        "count": len(matched),
        "avg_return_pct": round(float(np.mean(fwd_returns)), 1),
        "win_rate": round(win_rate, 1),
    }


def scan_markets(markets: list[str]) -> dict[str, tuple[pd.DataFrame, object]]:
    """마켓별 (지표포함 데이터프레임, 최신 signal or None) 반환."""
    results = {}
    for market in markets:
        try:
            df = fetch_daily_candles(market, count_days=400)
        except Exception as e:
            print(f"[경고] {market} 데이터 수집 실패: {e}")
            continue
        df_ind = add_indicators(df).reset_index(drop=True)
        if len(df_ind) < 65:
            continue
        latest_idx = len(df_ind) - 1
        sig = check_signal(df_ind, latest_idx, market)
        results[market] = (df_ind, sig)
    return results


def main():
    today = date.today()
    state = load_state()
    positions = state.get("positions", {})

    krw_markets = fetch_krw_markets()
    market_name_map_path = ROOT / "data" / "market_names.json"
    # 마켓 이름(한글) 캐시: 매번 새로 조회하지 않도록 저장해두고 재사용
    if market_name_map_path.exists():
        market_names = json.loads(market_name_map_path.read_text(encoding="utf-8"))
    else:
        market_names = {}

    universe = fetch_top_markets_by_value(UNIVERSE_SIZE)
    # 이미 활성 포지션인 마켓은 유니버스에 없어도 계속 추적해야 하므로 합쳐서 스캔
    scan_targets = sorted(set(universe) | set(positions.keys()))
    scanned = scan_markets(scan_targets)

    new_alerts = []
    expired = []

    for market, (df_ind, sig) in scanned.items():
        latest_close = float(df_ind["close"].iloc[-1])

        if market in positions:
            pos = positions[market]
            first_seen = date.fromisoformat(pos["first_seen_date"])
            days_elapsed = (today - first_seen).days

            hit_target = latest_close >= pos["target_price"]
            hit_stop = latest_close <= pos["stop_price"]
            time_up = days_elapsed >= HOLD_DAYS

            if hit_target or hit_stop or time_up:
                reason = "target" if hit_target else ("stop" if hit_stop else "time")
                expired.append((market, reason))
                return_pct = round((latest_close / pos["buy_price"] - 1) * 100, 2)
                history_entry = {
                    "market": market,
                    "first_seen_date": pos["first_seen_date"],
                    "resolved_date": today.isoformat(),
                    "buy_price": pos["buy_price"],
                    "exit_price": latest_close,
                    "exit_reason": reason,
                    "return_pct": return_pct,
                    "confidence": pos["confidence"],
                }
                history = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
                history.append(history_entry)
                save_json(HISTORY_PATH, history)
                del positions[market]
                continue

            pos["current_price"] = latest_close
            pos["days_left"] = max(0, HOLD_DAYS - days_elapsed)

        elif sig is not None:
            similar = find_similar_patterns(df_ind, len(df_ind) - 1)
            positions[market] = {
                "market": market,
                "first_seen_date": today.isoformat(),
                "current_price": latest_close,
                "buy_price": sig.buy_price,
                "target_price": sig.target_price,
                "stop_price": sig.stop_price,
                "confidence": sig.confidence,
                "reason": sig.reason,
                "days_left": HOLD_DAYS,
                "similar_patterns": similar,
            }
            new_alerts.append(positions[market])

    if expired:
        print("만료된 신호:", expired)
    if new_alerts:
        print("새 신호:", [a["market"] for a in new_alerts])

    # 마켓 한글 이름 채우기 (없는 것만 업비트 마켓 목록에서 보강 후 캐시에 저장)
    if any(m not in market_names for m in positions):
        try:
            import requests

            resp = requests.get(
                "https://api.upbit.com/v1/market/all", params={"isDetails": "false"}, timeout=10
            )
            resp.raise_for_status()
            for d in resp.json():
                market_names[d["market"]] = d.get("korean_name", d["market"])
            save_json(market_name_map_path, market_names)
        except Exception as e:
            print(f"[경고] 마켓 이름 조회 실패: {e}")

    state["positions"] = positions
    save_json(STATE_PATH, state)
    save_json(ALERTS_PATH, new_alerts)

    ranked = sorted(positions.values(), key=lambda p: p["confidence"], reverse=True)[:TOP_DISPLAY]
    for p in ranked:
        p["name"] = market_names.get(p["market"], p["market"])

    signals_output = {
        "generated_at": datetime.now(KST).isoformat(),
        "signals": ranked,
    }
    save_json(SIGNALS_PATH, signals_output)
    print(f"완료: 활성 포지션 {len(positions)}개, 표시 {len(ranked)}개, 신규 알림 {len(new_alerts)}개")


if __name__ == "__main__":
    main()
