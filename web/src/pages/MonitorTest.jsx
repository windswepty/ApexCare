import { useCallback, useEffect, useRef, useState } from 'react'
import { Monitor, Play } from 'lucide-react'
import { measureRefreshRate } from '../lib/refreshRate.js'
import {
  Breadcrumb, Callout, KofiSupport, RelatedTools, Stat, useMeta
} from '../components/ui.jsx'

const COLORS = [
  { name: '검정 — 백라이트 블리딩·밝은 점', value: '#000000' },
  { name: '흰색 — 어두운 점·얼룩', value: '#ffffff' },
  { name: '빨강', value: '#ff0000' },
  { name: '초록', value: '#00ff00' },
  { name: '파랑', value: '#0000ff' },
  { name: '회색 50% — 균일도', value: '#808080' },
  { name: '청록', value: '#00ffff' },
  { name: '자홍', value: '#ff00ff' },
  { name: '노랑', value: '#ffff00' }
]

/** 전체화면 단색 순회 — 불량화소는 이 방식이 가장 확실하다. */
function ColorStage({ index, setIndex, onExit }) {
  const [hintVisible, setHintVisible] = useState(true)

  useEffect(() => {
    const t = setTimeout(() => setHintVisible(false), 2600)
    return () => clearTimeout(t)
  }, [index])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { onExit(); return }
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'Enter') {
        e.preventDefault()
        setIndex((i) => (i + 1) % COLORS.length)
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setIndex((i) => (i - 1 + COLORS.length) % COLORS.length)
      }
      setHintVisible(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onExit, setIndex])

  return (
    <>
      <div
        className="fs-stage"
        style={{ background: COLORS[index].value }}
        onClick={() => { setIndex((i) => (i + 1) % COLORS.length); setHintVisible(true) }}
      />
      <div className="fs-hint" style={{ opacity: hintVisible ? 1 : 0 }}>
        {COLORS[index].name} · {index + 1}/{COLORS.length} — 클릭/→ 다음, ESC 종료
      </div>
    </>
  )
}

/** 잔상(고스팅) 테스트 — 일정 속도로 움직이는 블록의 꼬리를 눈으로 확인한다. */
function GhostingStage({ onExit }) {
  const canvasRef = useRef(null)
  const [speed, setSpeed] = useState(900)
  const speedRef = useRef(speed)
  speedRef.current = speed

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf = 0
    let last = performance.now()
    let x = 0

    const resize = () => {
      canvas.width = window.innerWidth * window.devicePixelRatio
      canvas.height = window.innerHeight * window.devicePixelRatio
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = (now) => {
      const dt = (now - last) / 1000
      last = now
      const dpr = window.devicePixelRatio
      // 시간 기반 이동이라 주사율이 달라도 실제 속도는 동일하다
      x += speedRef.current * dpr * dt
      if (x > canvas.width + 200 * dpr) x = -200 * dpr

      ctx.fillStyle = '#000'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      const rowH = canvas.height / 3
      const colors = ['#ffffff', '#00e5ff', '#ff2d55']
      colors.forEach((c, i) => {
        ctx.fillStyle = c
        ctx.fillRect(x, rowH * i + rowH * 0.25, 120 * dpr, rowH * 0.5)
      })
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)

    const onKey = (e) => {
      if (e.key === 'Escape') onExit()
      if (e.key === 'ArrowUp') setSpeed((s) => Math.min(3000, s + 150))
      if (e.key === 'ArrowDown') setSpeed((s) => Math.max(150, s - 150))
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('keydown', onKey)
    }
  }, [onExit])

  return (
    <>
      <canvas ref={canvasRef} className="fs-stage" style={{ width: '100vw', height: '100vh' }} />
      <div className="fs-hint">
        블록의 뒤쪽 꼬리를 보세요 · {speed}px/s — ↑↓ 속도, ESC 종료
      </div>
    </>
  )
}

export default function MonitorTest() {
  useMeta(
    '모니터 불량화소·잔상 테스트',
    '전체화면 단색 화면으로 불량화소와 백라이트 블리딩을 찾고, 움직이는 블록으로 잔상(고스팅)을 확인합니다. 실제 주사율도 실측합니다.'
  )

  const [mode, setMode] = useState(null) // null | 'color' | 'ghost'
  const [colorIndex, setColorIndex] = useState(0)
  const [refresh, setRefresh] = useState(null)
  const [measuring, setMeasuring] = useState(false)

  const enter = useCallback(async (next) => {
    setMode(next)
    try { await document.documentElement.requestFullscreen?.() } catch { /* 사용자가 거부 */ }
  }, [])

  const exit = useCallback(async () => {
    setMode(null)
    try { if (document.fullscreenElement) await document.exitFullscreen?.() } catch { /* 무시 */ }
  }, [])

  // ESC 로 전체화면이 풀리면 스테이지도 같이 닫아야 한다
  useEffect(() => {
    const onFsChange = () => { if (!document.fullscreenElement) setMode(null) }
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  const measure = async () => {
    setMeasuring(true)
    setRefresh(await measureRefreshRate(1500))
    setMeasuring(false)
  }

  if (mode === 'color') {
    return <ColorStage index={colorIndex} setIndex={setColorIndex} onExit={exit} />
  }
  if (mode === 'ghost') return <GhostingStage onExit={exit} />

  return (
    <>
      <Breadcrumb label="모니터 테스트" />
      <h1>모니터 불량화소·잔상 테스트</h1>
      <p className="lede">
        새 모니터 개봉했거나 중고로 받으셨나요? 반품 기간이 지나기 전에 확인하세요.
        전체화면 단색이 불량화소를 찾는 가장 확실한 방법입니다.
      </p>

      <div className="grid cols-2">
        <div className="card">
          <h2>불량화소 · 백라이트 블리딩</h2>
          <p className="muted" style={{ fontSize: 14, marginTop: -6 }}>
            화면 전체를 단색으로 채웁니다. 다른 색으로 남아 있는 점이 불량화소입니다.
            검정 화면에서 모서리가 하얗게 뜨면 백라이트 블리딩입니다.
          </p>
          <div className="swatches" style={{ margin: '14px 0' }}>
            {COLORS.map((c, i) => (
              <button
                key={c.value}
                className={`swatch ${colorIndex === i ? 'on' : ''}`}
                style={{ background: c.value }}
                onClick={() => setColorIndex(i)}
                aria-label={c.name}
                title={c.name}
              />
            ))}
          </div>
          <button className="btn primary" onClick={() => enter('color')}>
            <Play size={16} /> 전체화면으로 시작
          </button>
        </div>

        <div className="card">
          <h2>잔상 (고스팅)</h2>
          <p className="muted" style={{ fontSize: 14, marginTop: -6 }}>
            일정 속도로 움직이는 블록의 뒤에 꼬리가 남는지 봅니다. 꼬리가 길면 응답속도가 느리거나
            오버드라이브 설정이 낮은 것입니다. 반대로 블록 앞뒤에 반대색 테두리가 보이면
            오버드라이브가 과합니다.
          </p>
          <button className="btn primary" onClick={() => enter('ghost')}>
            <Play size={16} /> 전체화면으로 시작
          </button>
        </div>
      </div>

      <div className="card section">
        <h2>실제 주사율 측정</h2>
        <p className="muted" style={{ fontSize: 14, marginTop: -6 }}>
          윈도우 설정에 적힌 값이 아니라, 브라우저가 <strong>실제로 받고 있는</strong> 프레임 간격을 잽니다.
          144Hz 모니터인데 60Hz로 나온다면 케이블이나 디스플레이 설정 문제입니다.
        </p>
        {refresh && (
          <div style={{ margin: '14px 0' }}>
            <Stat
              k="실측 주사율"
              v={`${refresh.raw.toFixed(1)} Hz${refresh.snapped ? ` (${refresh.snapped}Hz 판정)` : ''}`}
            />
            <Stat k="측정 프레임" v={`${refresh.samples} 프레임`} />
          </div>
        )}
        <button className="btn" onClick={measure} disabled={measuring}>
          <Monitor size={16} /> {measuring ? '측정 중...' : refresh ? '다시 측정' : '주사율 측정'}
        </button>
      </div>

      <div className="section">
        <Callout>
          <strong>불량화소 판정 기준은 제조사마다 다릅니다.</strong> 보통 밝은 점(항상 켜진 픽셀)은
          1개만 있어도 교환 대상이지만, 어두운 점은 여러 개까지 정상으로 봅니다.
          발견하셨다면 화면을 촬영해 두고 구매처 기준을 확인하세요.
        </Callout>
      </div>

      <KofiSupport context="반품 기간 안에 확인하셨나요?" />
      <RelatedTools current="/monitor-test" />
    </>
  )
}
