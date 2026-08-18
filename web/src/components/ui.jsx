import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Info, AlertTriangle, Coffee } from 'lucide-react'
import { KOFI_USERNAME, SITE } from '../config.js'

/** 라우트별 title/description. SPA 라도 검색엔진과 공유 미리보기가 이걸 읽는다. */
export function useMeta(title, description) {
  useEffect(() => {
    document.title = title ? `${title} — ${SITE.name}` : `${SITE.name} — ${SITE.tagline}`
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
 */
export function KofiSupport({ context }) {
  if (!KOFI_USERNAME) return null
  return (
    <div className="kofi">
      <div className="kofi-text">
        <strong>이 도구가 도움이 됐다면</strong>
        <p>
          {context || '광고도 로그인도 없이 운영합니다.'} 서버비와 도메인 비용만 나가고 있어서,
          커피 한 잔이면 계속 굴러갑니다.
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
