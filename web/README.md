# APEX CARE Web

설치 없이 브라우저에서 도는 PC 진단 도구 모음. 데스크톱 앱과 별개인 정적 사이트다.

## 개발

```bash
npm install --prefix web
npm run dev --prefix web       # http://localhost:5173
npm run build --prefix web     # web/dist 에 정적 파일 생성
```

## 배포하기 전에 해야 할 일

1. **Ko-fi 사용자명 채우기** — `src/config.js` 의 `KOFI_USERNAME` 이 비어 있으면
   후원 버튼이 아예 렌더링되지 않는다(빈 링크 노출 방지). `ko-fi.com/<사용자명>` 의
   `<사용자명>` 부분을 넣으면 결과 화면 하단에 후원 카드가 나타난다.
2. **도메인 확정** — `src/config.js` 의 `SITE.url` 을 실제 주소로 바꾼다.
   공유 스코어카드 이미지 하단에 이 주소가 찍힌다.

## 배포

Cloudflare Pages 기준:

- 빌드 명령: `npm run build`
- 빌드 출력 디렉터리: `dist`
- 루트 디렉터리: `web`

`public/_redirects` 가 모든 경로를 `index.html` 로 넘긴다. 이게 없으면
`/mouse-polling-rate` 같은 주소로 직접 들어왔을 때 404 가 난다.

## 구조

```
src/lib/       측정 로직 (UI 와 분리되어 있어 Node 에서 단독 검증 가능)
  pollingRate.js   폴링레이트 계산 + 타임스탬프 정밀도 감지
  refreshRate.js   rAF 간격으로 실제 주사율 실측
  bench.js         단일/멀티코어(워커) + WebGL2 그래픽 벤치
  hardware.js      사양 감지 + GPU 이름 정리
  scorecard.js     공유용 1200x630 PNG 생성
  storage.js       측정 이력 (localStorage 전용, 서버 전송 없음)
src/pages/     도구 1개 = 페이지 1개 = 검색 키워드 1개
```

## 측정에 관한 원칙

브라우저가 주는 값에는 한계가 있다. 이 사이트는 그 한계를 숨기지 않는다.

- `navigator.deviceMemory` 는 2의 거듭제곱으로 반올림된 근사치이고 브라우저마다
  상한이 다르다. 특정 숫자를 상한이라고 단정하지 않는다.
- CPU 모델명과 디스크 여유 공간은 어떤 브라우저도 알려주지 않는다.
- `navigator.storage.estimate()` 는 브라우저 할당량이지 디스크 여유 공간이 아니다.
- 파이어폭스는 입력 시각을 1ms 로 반올림하므로 1000Hz 초과 마우스를 측정할 수 없다.
  이 경우 결과 화면에 경고를 띄운다.
- 성능 점수는 상대 지표다. 그래서 점수 옆에 항상 실측 원값(ops/s, pass/ms)을 함께 보여준다.

### 점수 보정

`src/lib/bench.js` 의 `REFERENCE` 상수 한 곳만 고치면 된다.
현재 값은 16스레드 데스크톱(AMD)에서 종합 약 1150~1200 이 나오도록 맞춰져 있다.
