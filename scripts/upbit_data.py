"""
업비트 캔들 데이터 수집 + 정합성 검증 모듈

- fetch_daily_candles: 업비트 Open API에서 일봉 캔들 수집 (최대 200개씩 페이징)
- validate_candles: 결측/중복/이상치 체크
- load_or_fetch: 로컬 캐시(csv) 있으면 사용, 없으면 API 호출 후 저장

주의: 이 파일은 인터넷이 되는 사용자 로컬 환경에서 실행해야 합니다.
      (이 개발 샌드박스는 api.upbit.com 접근이 막혀 있어 여기서는 직접 호출 테스트를 못 합니다.)
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

UPBIT_CANDLE_URL = "https://api.upbit.com/v1/candles/days"
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)


def fetch_daily_candles(market: str, count_days: int = 400) -> pd.DataFrame:
    """
    업비트 일봉 캔들을 count_days만큼 수집.
    업비트 API는 1회 최대 200개 제한이 있어 여러 번 나눠서 호출(페이징)한다.

    Parameters
    ----------
    market : str
        예: "KRW-BTC"
    count_days : int
        가져올 일봉 개수 (기본 400일 = 백테스트에 넉넉한 기간)

    Returns
    -------
    pd.DataFrame columns: [date, open, high, low, close, volume, value(거래대금)]
        날짜 오름차순 정렬됨 (과거 -> 최신)
    """
    all_rows = []
    to_ts = None  # None이면 가장 최신부터

    remaining = count_days
    while remaining > 0:
        req_count = min(200, remaining)
        params = {"market": market, "count": req_count}
        if to_ts:
            params["to"] = to_ts

        resp = requests.get(UPBIT_CANDLE_URL, params=params, timeout=10)
        if resp.status_code == 429:
            # 업비트 rate limit -> 잠깐 대기 후 재시도
            time.sleep(1.0)
            continue
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break

        all_rows.extend(rows)
        # 다음 페이지는 이번에 받은 것 중 가장 과거 캔들 이전부터
        oldest = rows[-1]
        to_ts = oldest["candle_date_time_utc"]
        remaining -= len(rows)

        time.sleep(0.15)  # 업비트 초당 요청 제한 보호

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise ValueError(f"{market} 캔들 데이터를 가져오지 못했습니다.")

    df = df.rename(
        columns={
            "candle_date_time_kst": "date",
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
            "candle_acc_trade_price": "value",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "open", "high", "low", "close", "volume", "value"]]
    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    return df


def validate_candles(df: pd.DataFrame, market: str) -> dict:
    """
    데이터 정합성 체크. 문제가 있으면 report에 기록하되, 앱은 이 리포트를 보고
    '이 신호는 데이터 품질이 낮으니 신뢰도 감점' 처리에 사용한다.

    체크 항목:
      1) 날짜 중복
      2) 날짜 결측(연속된 일봉 사이 빠진 날)
      3) OHLC 논리 오류 (high < low, close가 high/low 범위 밖 등)
      4) 거래대금 0 또는 음수 (사실상 거래 정지/데이터 오류 가능성)
      5) 이상 급등락 (전일 대비 ±80% 이상, 데이터 오류 가능성 높음 -> 별도 확인 필요)
    """
    report = {"market": market, "n_rows": len(df), "issues": []}

    dup_count = df["date"].duplicated().sum()
    if dup_count > 0:
        report["issues"].append(f"중복 날짜 {dup_count}건")

    expected_days = (df["date"].max() - df["date"].min()).days + 1
    missing_days = expected_days - df["date"].nunique()
    if missing_days > 0:
        report["issues"].append(f"결측(빠진 날짜) 약 {missing_days}건")

    bad_ohlc = df[(df["high"] < df["low"]) | (df["close"] > df["high"]) | (df["close"] < df["low"])]
    if len(bad_ohlc) > 0:
        report["issues"].append(f"OHLC 논리 오류 {len(bad_ohlc)}건")

    bad_value = df[df["value"] <= 0]
    if len(bad_value) > 0:
        report["issues"].append(f"거래대금 0/음수 {len(bad_value)}건")

    daily_change = df["close"].pct_change().abs()
    extreme = daily_change[daily_change > 0.8]
    if len(extreme) > 0:
        report["issues"].append(f"전일 대비 ±80% 이상 급변 {len(extreme)}건 (데이터 오류 가능성, 수동 확인 권장)")

    report["is_clean"] = len(report["issues"]) == 0
    return report


def fetch_krw_markets() -> list[str]:
    """업비트에 상장된 KRW 마켓 전체 목록."""
    resp = requests.get("https://api.upbit.com/v1/market/all", params={"isDetails": "false"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [d["market"] for d in data if d["market"].startswith("KRW-")]


def fetch_top_markets_by_value(n: int = 30) -> list[str]:
    """24시간 누적 거래대금 기준 상위 n개 KRW 마켓. (유동성 낮은 잡코인 배제 목적)"""
    markets = fetch_krw_markets()
    tickers = []
    batch_size = 100  # ticker API 한번에 너무 많이 요청하지 않도록 배치 처리
    for i in range(0, len(markets), batch_size):
        batch = markets[i : i + batch_size]
        resp = requests.get(
            "https://api.upbit.com/v1/ticker", params={"markets": ",".join(batch)}, timeout=10
        )
        resp.raise_for_status()
        tickers.extend(resp.json())
        time.sleep(0.15)

    tickers.sort(key=lambda x: x.get("acc_trade_price_24h", 0), reverse=True)
    return [t["market"] for t in tickers[:n]]


def load_or_fetch(market: str, count_days: int = 400, force_refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """캐시 파일이 있으면 재사용, 없으면 API 호출 후 캐시 저장. 검증 리포트도 함께 반환."""
    cache_path = CACHE_DIR / f"{market}_daily.csv"

    if cache_path.exists() and not force_refresh:
        df = pd.read_csv(cache_path, parse_dates=["date"])
    else:
        df = fetch_daily_candles(market, count_days)
        df.to_csv(cache_path, index=False)

    report = validate_candles(df, market)
    return df, report


if __name__ == "__main__":
    # 사용 예시 (실제 업비트 API 접근 가능한 환경에서 실행)
    df, report = load_or_fetch("KRW-BTC", count_days=400)
    print(report)
    print(df.tail())
