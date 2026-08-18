# APEX CARE Web

설치 없이 브라우저에서 도는 PC 진단 도구 모음. 데스크톱 앱과 별개인 정적 사이트다.

## 개발

```bash
npm install --prefix web
npm run dev --prefix web       # http://localhost:5173
npm run build --prefix web     # 클라이언트 빌드 + SSR 빌드 + 프리렌더
npm run preview --prefix web   # 빌드 결과물을 실제로 서빙해 확인
```

`build` 는 세 단계다. 마지막 프리렌더 단계가 빠지면 SEO 와 링크 미리보기가
통째로 죽으므로 `build:client` 만 돌려서 배포하면 안 된다.

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

## 프리렌더 — 이게 왜 있는가

SPA 는 모든 주소에 같은 빈 `index.html` 을 준다. 그대로 두면

1. 카카오톡·디스코드·커뮤니티에 어느 페이지를 공유하든 미리보기가 홈 문구로 뜬다.
2. JS 실행이 약한 크롤러(특히 네이버)에는 본문이 아예 보이지 않는다.

공유와 검색이 이 사이트의 주 유입 경로라 둘 다 치명적이다. 그래서 빌드 시
`scripts/prerender.mjs` 가 라우트마다 실제 HTML 을 뽑는다.

- 라우트별 `<title>`, `description`, `canonical`, OG, Twitter 카드
- JSON-LD 구조화 데이터
- 본문이 들어간 실제 마크업 (JS 없이도 읽힌다)
- `sitemap.xml`, `robots.txt` 자동 생성

라우트를 추가할 때는 **`src/routes.js` 에만** 메타를 적는다. 클라이언트의 `useMeta` 와
프리렌더가 같은 출처를 쓰므로 두 곳에 따로 적으면 반드시 어긋난다.

각 라우트는 `<경로>.html` 과 `<경로>/index.html` 두 형태로 저장된다. 정적 호스트마다
슬래시 없는 주소를 푸는 방식이 달라서, 하나만 만들면 호스트에 따라 SPA 폴백(=홈 HTML)이
나가면서 라우트별 메타가 무의미해진다.

## 구조

```
src/routes.js  라우트 메타데이터 단일 출처 (클라이언트 + 프리렌더 공용)
src/entry-server.jsx  프리렌더 전용 진입점
scripts/prerender.mjs 빌드 후 정적 HTML·sitemap 생성
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
