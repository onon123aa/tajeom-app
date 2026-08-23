# 타점 — 아이폰 PWA 코인 단타 시그널 앱

업비트 거래대금 상위 코인을 자동으로 스캔해서 3일 이내 단타에 맞는 매수/매도 타이밍 Top 5를
아이폰 홈 화면 앱(PWA)으로 보여주고, 새 신호가 뜨면 푸시 알림도 보내주는 개인용 앱입니다.

- 신호 계산: GitHub Actions가 4시간마다 자동 실행 (내 컴퓨터를 켜둘 필요 없음, 무료)
- 화면: GitHub Pages로 호스팅되는 웹앱, 아이폰 홈 화면에 아이콘처럼 추가
- 알림: 아이폰 웹푸시 (iOS 16.4 이상 필요)

## 폴더 구조

```
docs/                   -> GitHub Pages로 배포될 실제 앱 화면
  index.html              메인 대시보드 (Top 5 카드, 알림 켜기 버튼)
  manifest.json           PWA 설정
  service-worker.js       푸시 수신 처리
  signals.json            최신 신호 데이터 (Actions가 자동 갱신)
  icons/                  앱 아이콘

scripts/                -> 신호 계산 로직 (GitHub Actions가 실행)
  upbit_data.py            업비트 API 데이터 수집
  indicators.py            기술 지표 계산
  strategy.py              매수 신호 조건 + 신뢰도 점수
  generate_signals.py      메인 스캔 스크립트 (신호 등록/유지/만료 상태 관리)
  send_push.py             푸시 알림 발송
  generate_vapid_keys.py   푸시용 키 생성 (최초 1회만 실행)

data/                   -> 신호 상태 저장 (Actions가 자동 갱신, 건드릴 필요 없음)

.github/workflows/
  update_signals.yml       4시간마다 자동 실행되는 설정
```

## 설치 순서 (처음 한 번만 하면 됨)

### 1. GitHub 저장소 만들고 파일 업로드
1. GitHub에서 새 저장소 생성 (이름 예: `tajeom-app`, Public으로 — Pages 무료 사용을 위해)
2. 이 폴더(docs, scripts, data, .github)를 통째로 저장소에 업로드/커밋

### 2. GitHub Pages 켜기
1. 저장소 **Settings → Pages**
2. Source: `Deploy from a branch` 선택
3. Branch: `main`, 폴더: `/docs` 선택 후 저장
4. 몇 분 후 `https://내아이디.github.io/tajeom-app/` 형태의 주소가 생성됨 (이 주소를 아이폰에서 열 것)

### 3. 알림용 키(VAPID) 생성
로컬 컴퓨터에서:
```bash
pip install -r scripts/requirements.txt
python scripts/generate_vapid_keys.py
```
콘솔에 PUBLIC KEY / PRIVATE KEY 두 값이 출력됩니다.

1. **PUBLIC KEY** → `docs/index.html` 파일을 열어서 아래 줄을 찾아 값을 교체:
   ```js
   const VAPID_PUBLIC_KEY = "REPLACE_WITH_YOUR_VAPID_PUBLIC_KEY";
   ```
   → 발급받은 PUBLIC KEY로 바꾸고 저장, 다시 GitHub에 커밋/푸시

2. **PRIVATE KEY** → 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `VAPID_PRIVATE_KEY`
   - Value: 발급받은 PRIVATE KEY 값
   - PRIVATE KEY는 코드에 넣지 말고 반드시 이 Secret에만 저장하세요.

### 4. Actions 켜기 & 최초 실행
1. 저장소 **Actions** 탭 → 처음이면 "I understand my workflows, go ahead and enable them" 클릭
2. `Update Signals` 워크플로우 선택 → **Run workflow** 버튼으로 한 번 수동 실행
3. 성공하면 `docs/signals.json`이 실제 업비트 데이터로 갱신된 채 자동 커밋됨

### 5. 아이폰에 앱 설치
1. 아이폰 **Safari**로 2번 단계의 GitHub Pages 주소 접속 (꼭 Safari여야 함, 크롬 불가)
2. 공유 버튼(⬆️) → **홈 화면에 추가**
3. 홈 화면에 생긴 "타점" 아이콘으로 앱 열기 (Safari 탭이 아니라 이 아이콘으로 열어야 알림이 됨)
4. 화면 우측 상단 **🔕 알림 켜기** 버튼 탭 → 알림 권한 허용
5. 화면에 긴 코드(구독 정보)가 뜨고 자동으로 클립보드에 복사됨

### 6. 구독 정보를 Secret에 등록
1. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `PUSH_SUBSCRIPTION`
3. Value: 5번 단계에서 복사된 코드를 그대로 붙여넣기 (`{"endpoint":"...","keys":{...}}` 형태)
4. 저장

여기까지 하면 끝입니다. 이후 4시간마다 자동으로:
- 업비트 거래대금 상위 20개 코인을 스캔
- 조건에 맞는 새 신호가 있으면 → 아이폰으로 푸시 알림 + `signals.json` 갱신
- 기존 신호는 3일 경과 또는 목표가/손절가 도달 시 자동으로 목록에서 빠짐

앱을 다시 열면 항상 최신 Top 5가 보입니다.

## 알아두면 좋은 점

- **알림 주체가 바뀌면(폰 변경, 앱 재설치 등)** 5~6번 단계(구독 정보 재등록)를 다시 해야 합니다.
- **매수가/목표가/손절가는 신호가 처음 뜬 시점 가격으로 고정**됩니다. 이후 현재가가 바뀌어도 이 기준선은 유지되고, 3일이 지나거나 목표/손절에 닿으면 자동으로 목록에서 빠집니다.
- **"과거 유사 패턴" 수치**는 간단한 유사도 기반 검색 결과입니다. 표본이 3건 미만이면 화면에 "참고용 아님"으로 표시됩니다.
- 화면 하단 문구대로 **이 앱은 투자 판단 참고용이며 투자 권유가 아닙니다.**

## 다음에 고려하면 좋은 것

- [ ] `scripts/strategy.py`의 조건값(RSI 구간, 눌림 폭, 목표/손절 비율)을 백테스트 결과에 맞게 튜닝
- [ ] 신호 정확도 자체 기록(신호가 실제로 며칠 후 어떻게 됐는지 트래킹) 대시보드 추가
- [ ] 유사 패턴 검색을 DTW 기반으로 고도화
