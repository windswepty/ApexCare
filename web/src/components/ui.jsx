import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Info, AlertTriangle, Coffee } from 'lucide-react'
import { KOFI_USERNAME, SITE } from '../config.js'
import { routeMeta } from '../routes.js'

/**
 * 라우트별 title/description 을 현재 주소에 맞춰 갱신한다.
 *
 * 문구는 routes.js 에서만 가져온다. 페이지마다 따로 적으면 빌드 시 프리렌더가
 * 넣는 값과 클라이언트가 넣는 값이 갈라져, 크롤러가 본 제목과 사용자가 본 제목이
 * 달라진다. 오버라이드는 routes.js 에 없는 페이지(404)용이다.
 */
export function useMeta(overrideTitle, overrideDescription) {
  const { pathname } = useLocation()
  const meta = routeMeta(pathname)
  const title = overrideTitle || meta?.title || `${SITE.name} — ${SITE.tagline}`
  const description = overrideDescription || meta?.description

  useEffect(() => {
    document.title = title
    if (description) {
      let tag = document.querySelector('meta[name="description"]')
      if (!tag) {
        tag = document.createElement('meta')
        tag.setAttribute('name', 'description')
        document.head.appendChild(tag)
      }
      tag.setAttribute('content', description)
    }
  }, [title, description])
}

export function Callout({ kind = 'info', children }) {
  const Icon = kind === 'warn' ? AlertTriangle : Info
  return (
    <div className={`callout ${kind}`}>
      <Icon size={16} />
      <div>{children}</div>
    </div>
  )
}

export function Stat({ k, v, title }) {
  return (
    <div className="stat">
      <span className="k">{k}</span>
      <span className="v" title={title}>{v}</span>
    </div>
  )
}

export function Readout({ value, unit, caption }) {
  return (
    <div className="readout">
      <div className="value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {caption && <div className="caption">{caption}</div>}
    </div>
  )
}

export function Histogram({ buckets }) {
  const max = Math.max(1, ...buckets.map((b) => b.count))
  return (
    <div className="histogram">
      {buckets.map((b, i) => (
        <div
          key={i}
          className="hb"
          style={{ height: `${(b.count / max) * 100}%` }}
          title={`${b.from.toFixed(2)}–${b.to.toFixed(2)}ms · ${b.count}회`}
        />
      ))}
    </div>
  )
}

/**
 * 후원 요청. 측정이 끝난 뒤에만 노출한다 — 들어오자마자 돈 얘기를 하면
 * 도구를 써보기도 전에 이탈한다.
 * KOFI_USERNAME 이 비어 있으면 아무것도 그리지 않는다(빈 링크 방지).
 *
 * 운영 비용을 명분으로 쓰지 않는다. 호스팅이 실제로 무료라 '서버비가 나간다'는
 * 말은 거짓이고, 확인하면 바로 드러난다. 광고·추적을 넣지 않겠다는 약속과
 * 만든 노력에 대해 부탁하는 것이 사실이면서 명분도 강하다.
 */
export function KofiSupport({ context }) {
  if (!KOFI_USERNAME) return null
  return (
    <div className="kofi">
      <div className="kofi-text">
        <strong>이 도구가 도움이 됐다면</strong>
        <p>
          {context || '광고도 로그인도 없이 운영합니다.'} 앞으로도 광고 없이,
          측정값을 팔지 않고 유지하려 합니다. 커피 한 잔이면 다음 도구를 만드는 데 큰 힘이 됩니다.
        </p>
      </div>
      <a
        className="kofi-btn"
        href={`https://ko-fi.com/${KOFI_USERNAME}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Coffee size={17} /> Ko-fi로 후원하기
      </a>
    </div>
  )
}

/** 도구 간 이동을 유도해 체류를 만든다. 현재 페이지는 자동으로 빠진다. */
export function RelatedTools({ current }) {
  const all = [
    { to: '/mouse-polling-rate', label: '마우스 폴링레이트 측정' },
    { to: '/monitor-test', label: '모니터 불량화소·잔상 테스트' },
    { to: '/keyboard-test', label: '키보드 동시입력 테스트' },
    { to: '/gamepad-test', label: '게임패드 드리프트 테스트' },
    { to: '/system-check', label: '내 PC 사양·성능 진단' }
  ].filter((t) => t.to !== current)

  return (
    <div className="section">
      <h2>다른 도구도 써보세요</h2>
      <div className="related">
        {all.map((t) => <Link key={t.to} to={t.to}>{t.label}</Link>)}
      </div>
    </div>
  )
}

export function Breadcrumb({ label }) {
  return (
    <div className="breadcrumb">
      <Link to="/">홈</Link> <span>/</span> {label}
    </div>
  )
}
