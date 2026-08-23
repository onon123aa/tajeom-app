"""
'타점' 앱 아이콘 생성. 브랜드 팔레트(다크 네이비 배경 + 골드/레드 캔들)로
간단한 캔들스틱 모티프를 그려 180/192/512 사이즈로 저장.
"""

from PIL import Image, ImageDraw

BG = (10, 13, 18)        # --bg-base
RED = (240, 51, 77)      # --up-red
BLUE = (47, 125, 240)    # --down-blue
GOLD = (232, 184, 75)    # --gold


def draw_icon(size: int, path: str):
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)

    # 3개의 캔들 (좌: 파랑 음봉, 중: 골드 강조, 우: 빨강 양봉) - 상승 전환 모티프
    unit = size / 12
    candle_w = unit * 2.0
    gap = unit * 1.2

    candles = [
        # (x_center, body_top, body_bottom, wick_top, wick_bottom, color)
        (size * 0.28, size * 0.52, size * 0.66, size * 0.46, size * 0.72, BLUE),
        (size * 0.50, size * 0.34, size * 0.58, size * 0.26, size * 0.64, GOLD),
        (size * 0.72, size * 0.20, size * 0.46, size * 0.14, size * 0.52, RED),
    ]

    for cx, top, bottom, wtop, wbottom, color in candles:
        d.line([(cx, wtop), (cx, wbottom)], fill=color, width=max(2, int(unit * 0.25)))
        d.rounded_rectangle(
            [cx - candle_w / 2, top, cx + candle_w / 2, bottom],
            radius=unit * 0.3,
            fill=color,
        )

    img.save(path)


if __name__ == "__main__":
    draw_icon(180, "docs/icons/icon-180.png")
    draw_icon(192, "docs/icons/icon-192.png")
    draw_icon(512, "docs/icons/icon-512.png")
    print("아이콘 생성 완료")
