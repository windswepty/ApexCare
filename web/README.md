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
   canonical·OG·sitemap·공유 이미지에 모두 들어간다.

### 후원 배치 원칙

먼저 주고, 결과가 나온 뒤에 조용히 묻는다.

- 랜딩과 측정 중에는 후원을 언급하지 않는다. 도구를 써보기도 전에 돈 얘기를 하면 이탈한다.
- Ko-fi 팝업 위젯을 쓰지 않는다. 이탈률만 올린다.
- "광고 없음 / 로그인 없음 / 측정값 서버 전송 없음" 이 후원의 명분이므로, 이걸 어기는
  변경(애널리틱스 추가 등)은 후원 전환율을 직접 깎는다는 걸 알고 결정해야 한다.

## 배포 (Cloudflare Pages)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Create → Pages →
   Connect to Git → `windswepty/ApexCare` 선택
2. 빌드 설정

   | 항목 | 값 |
   |---|---|
   | 프레임워크 프리셋 | None |
   | 빌드 명령 | `npm install && npm run build` |
   | 빌드 출력 디렉터리 | `dist` |
   | 루트 디렉터리 | `web` |

3. Save and Deploy

무료 플랜으로 충분하다. 대역폭 무제한, 월 500회 빌드. **서버비 0원이라 후원이 곧 순이익이다.**

`main` 에 푸시하면 자동으로 다시 배포된다.

### 도메인을 붙일 때

`src/config.js` 의 `SITE.url` 을 실제 주소로 바꿔야 한다. 이 값이 canonical·OG·sitemap 에
모두 들어가므로, 안 바꾸면 검색엔진이 엉뚱한 주소를 정본으로 인식한다.
바꾼 뒤 다시 빌드·배포한다.

### 리다이렉트 설정이 없는 이유

`_redirects` 로 모든 미매칭 경로를 `index.html` 200 으로 넘기는 흔한 SPA 설정을
일부러 쓰지 않는다. 그건 검색엔진에 "이 주소는 정상 페이지"라고 거짓말하는 것(soft 404)이라
오타 주소가 홈 내용으로 색인될 수 있다. 실제 라우트는 전부 프리렌더되므로 매칭되지 않는
주소는 진짜 404 가 맞고, 그 용도로 `404.html` 을 생성한다. Cloudflare Pages 와 Netlify 는
이 파일을 미매칭 경로에 404 상태로 서빙한다.

## 구조

```
src/routes.js  라우트 메타데이터 단일 출처 (클라이언트 + 프리렌더 공용)
               도구를 추가하면 여기 + App.jsx + Layout.jsx(내비) + ui.jsx(관련도구)
               + Home.jsx(카드) 다섯 곳을 함께 고친다
src/entry-server.jsx  프리렌더 전용 진입점
scripts/prerender.mjs 빌드 후 정적 HTML·sitemap 생성
src/lib/       측정 로직 (UI 와 분리되어 있어 Node 에서 단독 검증 가능)
  pollingRate.js   폴링레이트 계산 + 타임스탬프 정밀도 감지
  refreshRate.js   rAF 간격으로 실제 주사율 실측
  bench.js         단일/멀티코어(워커) + WebGL2 그래픽 벤치
  hardware.js      사양 감지 + GPU 이름 정리
  scorecard.js     공유용 1200x630 PNG 생성
  gamepad.js       스틱 드리프트 판정 (축별이 아니라 반경으로 봐야 대각선을 놓치지 않는다)
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
