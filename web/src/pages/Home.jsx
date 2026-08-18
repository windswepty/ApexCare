import { Link } from 'react-router-dom'
import { MousePointer2, Monitor, Keyboard, Gamepad2, Gauge, ShieldCheck } from 'lucide-react'
import { KofiSupport, useMeta } from '../components/ui.jsx'
import { SITE } from '../config.js'

const TOOLS = [
  {
    to: '/mouse-polling-rate',
    icon: MousePointer2,
    title: '마우스 폴링레이트 측정',
    desc: '마우스가 초당 몇 번 좌표를 보고하는지 실측합니다. 합쳐지기 전 원본 입력을 읽어 8000Hz까지 정확하게 잽니다.',
    tag: '10초'
  },
  {
    to: '/monitor-test',
    icon: Monitor,
    title: '모니터 불량화소·잔상 테스트',
    desc: '전체화면 단색으로 불량화소와 백라이트 블리딩을 찾고, 움직이는 블록으로 잔상을 확인합니다.',
    tag: '개봉·중고 검수용'
  },
  {
    to: '/keyboard-test',
    icon: Keyboard,
    title: '키보드 동시입력 테스트',
    desc: '모든 키가 인식되는지 확인하고, 동시에 몇 개까지 눌리는지(N키 롤오버) 측정합니다.',
    tag: '눌림 불량 확인'
  },
  {
    to: '/gamepad-test',
    icon: Gamepad2,
    title: '게임패드 스틱 드리프트 테스트',
    desc: '스틱을 놓았는데 캐릭터가 혼자 움직이나요? 드리프트를 수치로 재고 버튼·트리거·진동까지 확인합니다.',
    tag: '중고 검수용'
  },
  {
    to: '/system-check',
    icon: Gauge,
    title: '내 PC 사양·성능 진단',
    desc: 'GPU 모델과 주사율을 감지하고 단일코어·멀티코어·그래픽 성능을 재서 종합 점수를 냅니다.',
    tag: '약 3초'
  }
]

export default function Home() {
  useMeta()

  return (
    <>
      <h1>설치 없이 되는 PC 진단 도구</h1>
      <p className="lede">
        새로 산 마우스가 제 성능을 내는지, 모니터에 불량화소가 있는지, 키보드가 멀쩡한지 —
        프로그램 설치도 로그인도 없이 이 페이지에서 바로 확인하세요.
        측정은 전부 브라우저 안에서만 이뤄집니다.
      </p>

      <div className="grid cols-2">
        {TOOLS.map((t) => (
          <Link key={t.to} to={t.to} className="tool-card">
            <div className="tc-icon"><t.icon size={19} /></div>
            <h3>{t.title}</h3>
            <p>{t.desc}</p>
            <span className="tc-tag">{t.tag}</span>
          </Link>
        ))}
      </div>

      <div className="card section">
        <h2><ShieldCheck size={17} style={{ verticalAlign: -3, marginRight: 6, color: 'var(--accent)' }} />
          이 사이트가 하지 않는 것</h2>
        <p className="muted" style={{ fontSize: 14.5, margin: 0 }}>
          측정 결과를 서버로 보내지 않습니다. 계정을 만들라고 하지 않습니다. 광고와 추적 스크립트를
          넣지 않습니다. 기록은 이 기기의 브라우저 저장소에만 남고, 버튼 하나로 지울 수 있습니다.
          그래서 결과 화면에만 조용히 후원 링크를 둡니다.
        </p>
      </div>

      <div className="card section">
        <h2>정확한 값과 근사치를 구분해서 보여줍니다</h2>
        <p className="muted" style={{ fontSize: 14.5, margin: 0 }}>
          브라우저는 CPU 모델명이나 디스크 여유 공간을 알려주지 않고, 메모리 용량은 2의 거듭제곱으로
          반올림한 근사치만 알려줍니다. 파이어폭스는 입력 시각을 1밀리초로 반올림해서 1000Hz 이상
          마우스를 측정할 수 없습니다. {SITE.name}은 이런 한계를 숨기지 않고 해당 항목 옆에
          그대로 표시합니다.
        </p>
      </div>

      <KofiSupport context="여기 있는 도구가 쓸모 있었다면요." />
    </>
  )
}
