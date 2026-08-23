"""
웹 푸시(Web Push)에 필요한 VAPID 키 쌍을 생성합니다. 최초 1회만 실행하면 됩니다.

실행:
    python generate_vapid_keys.py

출력된 두 값을 각각:
  - PUBLIC KEY  -> docs/index.html 안의 VAPID_PUBLIC_KEY 값에 붙여넣기
  - PRIVATE KEY -> GitHub 저장소 Settings > Secrets and variables > Actions 에서
                   이름 VAPID_PRIVATE_KEY 로 시크릿 등록

주의: PRIVATE KEY는 절대 코드/공개 저장소에 커밋하지 마세요. GitHub Secret에만 저장합니다.
"""

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid


def main():
    vapid = Vapid()
    vapid.generate_keys()

    raw_pub = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    b64_pub = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()

    priv_value = vapid.private_key.private_numbers().private_value
    raw_priv = priv_value.to_bytes(32, "big")
    b64_priv = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()

    print("=" * 60)
    print("PUBLIC KEY (docs/index.html의 VAPID_PUBLIC_KEY에 붙여넣기)")
    print(b64_pub)
    print()
    print("PRIVATE KEY (GitHub Secret 'VAPID_PRIVATE_KEY'로 등록, 절대 공개 금지)")
    print(b64_priv)
    print("=" * 60)


if __name__ == "__main__":
    main()
