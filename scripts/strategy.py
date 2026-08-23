"""
전략 로직: 돌파매매 (Breakout)

이전에 시도했던 '눌림목(추세 중 되돌림) 매매'는 4번의 실제 백테스트 튜닝에도
손익분기점을 넘지 못했음 (최고 성적 v2: 승률 34%, 필요 승률 37%).
그래서 완전히 다른 유형의 신호로 전환: "최근 20일 최고가를 거래량 실리면서
돌파할 때 매수" — 추세추종이 아니라 모멘텀/돌파 기반.

매수 신호 조건 (모두 충족 시 신호 발생):
  1) 돌파: 오늘 종가가 '오늘을 제외한' 과거 20일 최고가보다 높음 (신규 20일 고점 갱신)
  2) 거래량 확인: 거래량이 20일 평균 대비 2.0배 이상 (그리드서치 결과, 1.3~1.5배보다 2.0배가
     학습/검증 구간 모두에서 일관되게 더 나았음 -> 가짜 돌파를 거르는 데 효과적)
  3) 과열 방지: 오늘 하루 등락률이 +15% 이하 (이미 급등 다 끝난 뒤 추격매수 방지)
  4) 추세 맥락: MA20 > MA60 (상승 추세 안에서의 돌파만 채택, 하락장 반짝 돌파 제외)

튜닝 이력:
  [눌림목 계열] v1~v4: 전부 손익분기점 미달
  [돌파 계열]   v5(거래량1.5배, 목표5%/손절3%): 15개 코인 22건 승률41%(+), 30개 코인 33건 승률36%(손익분기 근접)
  [돌파 계열]   v6(거래량2.0배, 목표5%/손절2.5%): 그리드서치로 선정.
                학습구간 3건(표본 매우 작음), 검증구간(안 본 데이터) 12건 승률50%/평균+1.17%로 손익분기(33%) 상회

주의: 표본이 여전히 작아서(학습3건+검증12건) 완전히 확신할 수 있는 결과는 아님.
      이 설정으로 실제 운영하면서 data/trade_history.json에 쌓이는 진짜 결과로
      계속 검증해나가는 것을 권장.

신뢰도 점수(0~100) = 돌파강도 25 + 거래량 25 + 추세강도 25 + 비과열 25
"""

from dataclasses import dataclass

import pandas as pd

TARGET_PCT = 5.0     # 목표 수익률(%)
STOP_PCT = -2.5       # 손절률(%)
HOLD_DAYS = 3         # 최대 보유일 (단타 목적)


@dataclass
class Signal:
    date: pd.Timestamp
    market: str
    buy_price: float
    target_price: float
    stop_price: float
    confidence: float
    reason: str


def check_signal(df: pd.DataFrame, i: int, market: str) -> Signal | None:
    """
    i번째 행(row) 시점에서 신호 여부를 판단.
    i 시점까지의 데이터만 사용 (i+1 이후 데이터는 절대 참조하지 않음 -> lookahead 방지).
    """
    row = df.iloc[i]

    if pd.isna(row["ma60"]) or pd.isna(row["high20"]):  # 워밍업 기간 스킵
        return None

    is_breakout = row["close"] > row["high20"]
    is_volume_confirmed = row["vol_ratio"] >= 2.0
    is_not_overextended = row["daily_return_pct"] <= 15.0
    is_uptrend_context = row["ma20"] > row["ma60"]

    if not (is_breakout and is_volume_confirmed and is_not_overextended and is_uptrend_context):
        return None

    # --- 신뢰도 점수 계산 ---
    breakout_pct = (row["close"] / row["high20"] - 1) * 100
    # 돌파 직후(2~4% 위)가 이상적, 너무 붙어있거나(가짜 돌파 위험) 너무 멀면(이미 늦음) 감점
    breakout_score = 25 - abs(breakout_pct - 3) / 6 * 25
    breakout_score = max(0, min(25, breakout_score))

    volume_score = min(25, row["vol_ratio"] * 10)

    trend_strength = (row["ma20"] / row["ma60"] - 1) * 100
    trend_score = min(25, max(0, trend_strength * 10))

    # 오늘 등락률이 작을수록(이제 막 돌파 시작) 만점, 15%에 가까울수록 0점
    extension_score = 25 - max(0, row["daily_return_pct"]) / 15 * 25
    extension_score = max(0, min(25, extension_score))

    confidence = round(breakout_score + volume_score + trend_score + extension_score, 1)

    buy_price = row["close"]
    target_price = round(buy_price * (1 + TARGET_PCT / 100))
    stop_price = round(buy_price * (1 + STOP_PCT / 100))

    reason = (
        f"20일 신고가 돌파 +{breakout_pct:.1f}% · 거래량 {row['vol_ratio']:.1f}배 · "
        f"정배열 +{trend_strength:.1f}% · 당일등락 +{row['daily_return_pct']:.1f}%"
    )

    return Signal(
        date=row["date"],
        market=market,
        buy_price=buy_price,
        target_price=target_price,
        stop_price=stop_price,
        confidence=confidence,
        reason=reason,
    )
