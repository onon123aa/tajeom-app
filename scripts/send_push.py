"""
data/new_alerts.json에 있는 '이번에 새로 생긴 신호'들을 웹 푸시로 전송합니다.
GitHub Actions에서 VAPID_PRIVATE_KEY, PUSH_SUBSCRIPTION 시크릿을 환경변수로 주입해서 실행합니다.
"""

import json
import os
import sys
from pathlib import Path

from pywebpush import webpush, WebPushException

ROOT = Path(__file__).resolve().parent.parent
ALERTS_PATH = ROOT / "data" / "new_alerts.json"

VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:tajeom-app@example.com")


def format_won(n: float) -> str:
    return f"{round(n):,}원"


def build_message(alerts: list[dict]) -> tuple[str, str]:
    if len(alerts) == 1:
        a = alerts[0]
        title = f"타점 신호 · {a.get('name', a['market'])}"
        body = f"매수 {format_won(a['buy_price'])} · 목표 {format_won(a['target_price'])} · 신뢰도 {round(a['confidence'])}점"
    else:
        names = ", ".join(a.get("name", a["market"]) for a in alerts[:3])
        more = f" 외 {len(alerts) - 3}건" if len(alerts) > 3 else ""
        title = f"타점 · 새 신호 {len(alerts)}건"
        body = f"{names}{more} — 앱에서 확인하세요"
    return title, body


def main():
    if not ALERTS_PATH.exists():
        print("new_alerts.json 없음, 알림 스킵")
        return

    alerts = json.loads(ALERTS_PATH.read_text(encoding="utf-8"))
    if not alerts:
        print("새 신호 없음, 알림 스킵")
        return

    vapid_private_key = os.environ.get("VAPID_PRIVATE_KEY")
    subscription_raw = os.environ.get("PUSH_SUBSCRIPTION")

    if not vapid_private_key or not subscription_raw:
        print("VAPID_PRIVATE_KEY 또는 PUSH_SUBSCRIPTION 환경변수가 없어 알림을 보낼 수 없습니다.")
        sys.exit(1)

    subscription_info = json.loads(subscription_raw)
    title, body = build_message(alerts)

    payload = json.dumps({"title": title, "body": body, "url": "./index.html"}, ensure_ascii=False)

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        print("푸시 알림 전송 완료:", title)
    except WebPushException as e:
        print("푸시 알림 전송 실패:", repr(e))
        # 구독이 만료/취소된 경우(410 Gone) 등은 재구독이 필요하다는 신호이므로 실패해도 워크플로 자체는 계속 진행
        sys.exit(0)


if __name__ == "__main__":
    main()
