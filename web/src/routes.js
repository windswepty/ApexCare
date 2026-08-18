import { SITE } from './config.js'

/**
 * 라우트 메타데이터의 단일 출처.
 * 클라이언트의 useMeta 와 빌드 시 프리렌더가 같은 값을 쓴다.
 * 두 곳에 따로 적으면 반드시 어긋난다.
 */
export const ROUTES = [
  {
    path: '/',
    title: `${SITE.name} — ${SITE.tagline}`,
    description:
      '마우스 폴링레이트, 모니터 불량화소, 키보드 동시입력, PC 사양·성능을 브라우저에서 바로 측정합니다. 설치도 로그인도 없습니다.',
    changefreq: 'weekly',
    priority: '1.0'
  },
  {
    path: '/mouse-polling-rate',
    title: `마우스 폴링레이트 측정 — ${SITE.name}`,
    description:
      '마우스의 실제 폴링레이트(Hz)를 브라우저에서 바로 측정합니다. 합쳐지기 전 원본 입력 샘플을 읽어 125Hz부터 8000Hz까지 정확하게 잽니다. 설치 없이 10초면 끝납니다.',
    changefreq: 'monthly',
    priority: '0.9'
  },
  {
    path: '/monitor-test',
    title: `모니터 불량화소·잔상 테스트 — ${SITE.name}`,
    description:
      '전체화면 단색 화면으로 불량화소와 백라이트 블리딩을 찾고, 움직이는 블록으로 잔상(고스팅)을 확인합니다. 실제 주사율도 실측합니다. 개봉·중고 검수에 쓰세요.',
    changefreq: 'monthly',
    priority: '0.9'
  },
  {
    path: '/keyboard-test',
    title: `키보드 동시입력·눌림 테스트 — ${SITE.name}`,
    description:
      '키보드의 모든 키가 정상 인식되는지, 동시에 몇 개까지 눌리는지(N키 롤오버) 브라우저에서 바로 확인합니다. 눌림 불량 점검에 쓰세요.',
    changefreq: 'monthly',
    priority: '0.9'
  },
  {
    path: '/system-check',
    title: `내 PC 사양·성능 진단 — ${SITE.name}`,
    description:
      'CPU 스레드, GPU 모델, 화면 주사율을 자동으로 감지하고 단일코어·멀티코어·그래픽 성능을 측정해 종합 점수를 냅니다. 설치 없이 약 3초.',
    changefreq: 'monthly',
    priority: '0.9'
  }
]

export const routeMeta = (path) => ROUTES.find((r) => r.path === path) || null
