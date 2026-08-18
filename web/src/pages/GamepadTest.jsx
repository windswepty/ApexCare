import { useCallback, useEffect, useRef, useState } from 'react'
import { Gamepad2, Play, RotateCcw, Share2, Vibrate } from 'lucide-react'
import {
  STICKS, ANALOG_TRIGGERS, analyzeStick, buttonLabel,
  readGamepads, supportsVibration, vibrate
} from '../lib/gamepad.js'
import { drawScorecard, shareOrDownload } from '../lib/scorecard.js'
import { saveResult } from '../lib/storage.js'
import {
  Breadcrumb, Callout, KofiSupport, RelatedTools, Stat, useMeta
} from '../components/ui.jsx'

const REST_DURATION_MS = 5000

/** 스틱 위치 + 지금까지 닿은 최대 범위를 그린다. */
function StickCanvas({ stickRefs, stickKey, size = 168 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = size * dpr
    canvas.height = size * dpr
    const ctx = canvas.getContext('2d')
    let raf = 0

    const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

    const draw = () => {
      const { x, y, trace } = stickRefs.current[stickKey]
      const R = size / 2
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)

      const border = css('--border-strong') || '#888'
      const accent = css('--accent') || '#22d3ee'
      const dim = css('--text-dim') || '#888'

      // 바깥 원 = 스틱 최대 범위
      ctx.strokeStyle = border
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(R, R, R - 2, 0, Math.PI * 2)
      ctx.stroke()

      // 일반적인 게임 데드존 크기. 이 안쪽 드리프트는 대개 체감되지 않는다.
      ctx.setLineDash([3, 3])
      ctx.strokeStyle = dim
      ctx.beginPath()
      ctx.arc(R, R, (R - 2) * 0.12, 0, Math.PI * 2)
      ctx.stroke()
      ctx.setLineDash([])

      // 십자선
      ctx.strokeStyle = border
      ctx.globalAlpha = 0.5
      ctx.beginPath()
      ctx.moveTo(R, 6); ctx.lineTo(R, size - 6)
      ctx.moveTo(6, R); ctx.lineTo(size - 6, R)
      ctx.stroke()
      ctx.globalAlpha = 1

      // 지금까지 닿은 범위 — 스틱이 닳으면 원이 찌그러지거나 작아진다
      if (trace.length > 8) {
        ctx.strokeStyle = accent
        ctx.globalAlpha = 0.35
        ctx.lineWidth = 1.5
        ctx.beginPath()
        trace.forEach((p, i) => {
          const px = R + p.x * (R - 2)
          const py = R + p.y * (R - 2)
          if (i === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        })
        ctx.closePath()
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      // 현재 위치
      ctx.fillStyle = accent
      ctx.beginPath()
      ctx.arc(R + x * (R - 2), R + y * (R - 2), 6, 0, Math.PI * 2)
      ctx.fill()

      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
    // stickRefs 는 useRef 라 항상 같은 객체이고 stickKey 는 문자열이므로
    // 이 효과는 마운트 때 한 번만 돈다. 매 렌더마다 새 객체를 넘기면
    // rAF 루프가 초당 30번 해체·재설치된다.
  }, [size, stickRefs, stickKey])

  return <canvas ref={canvasRef} style={{ width: size, height: size, display: 'block' }} />
}

export default function GamepadTest() {
  useMeta()

  const [pad, setPad] = useState(null)
  const [buttons, setButtons] = useState([])
  const [axes, setAxes] = useState([])
  const [testedButtons, setTestedButtons] = useState(() => new Set())
  const [resting, setResting] = useState(false)
  const [restProgress, setRestProgress] = useState(0)
  const [drift, setDrift] = useState(null)
  const [rumbling, setRumbling] = useState(false)

  // 60fps 로 React 상태를 갱신하면 페이지 전체가 초당 60번 리렌더된다.
  // 부드러움이 필요한 스틱 그림은 canvas 가 ref 를 직접 읽어 매 프레임 그리고,
  // React 는 30fps 로만 갱신한다.
  const stickRefs = useRef({
    left: { x: 0, y: 0, trace: [] },
    right: { x: 0, y: 0, trace: [] }
  })
  const restSamples = useRef(null)
  const restStart = useRef(0)

  const finishRest = useCallback(() => {
    const s = restSamples.current
    restSamples.current = null
    setResting(false)
    setRestProgress(0)
    if (!s) return
    const result = {
      left: analyzeStick(s.left.x, s.left.y),
      right: analyzeStick(s.right.x, s.right.y)
    }
    setDrift(result)
    const worst = Math.max(result.left?.radius ?? 0, result.right?.radius ?? 0)
    saveResult({ tool: 'gamepad', worstDrift: Number(worst.toFixed(4)) })
  }, [])

  useEffect(() => {
    let raf = 0
    let frame = 0

    const loop = () => {
      // getGamepads() 를 매 프레임 새로 호출해야 최신 값이 나온다.
      // 받아둔 객체를 붙들고 있으면 값이 갱신되지 않는다.
      const pads = readGamepads()
      const gp = pads[0] || null

      if (gp) {
        for (const stick of STICKS) {
          const x = gp.axes[stick.xAxis] ?? 0
          const y = gp.axes[stick.yAxis] ?? 0
          const ref = stickRefs.current[stick.key]
          ref.x = x
          ref.y = y
          // 궤적은 각도별 최대 반경만 남긴다. 전부 쌓으면 금세 수만 점이 된다.
          const angle = Math.atan2(y, x)
          const slot = Math.round(((angle + Math.PI) / (Math.PI * 2)) * 72) % 72
          const r = Math.hypot(x, y)
          if (!ref.traceMap) ref.traceMap = new Array(72).fill(0)
          if (r > ref.traceMap[slot]) {
            ref.traceMap[slot] = r
            ref.trace = ref.traceMap.map((rad, i) => {
              const a = (i / 72) * Math.PI * 2 - Math.PI
              return { x: Math.cos(a) * rad, y: Math.sin(a) * rad }
            })
          }
        }

        if (restSamples.current) {
          const s = restSamples.current
          for (const stick of STICKS) {
            s[stick.key].x.push(gp.axes[stick.xAxis] ?? 0)
            s[stick.key].y.push(gp.axes[stick.yAxis] ?? 0)
          }
          const elapsed = performance.now() - restStart.current
          setRestProgress(Math.min(100, (elapsed / REST_DURATION_MS) * 100))
          if (elapsed >= REST_DURATION_MS) finishRest()
        }

        // 버튼은 눌린 순간 바로 반응해야 하므로 변화가 있으면 즉시 반영한다
        const pressed = gp.buttons.map((b) => b.pressed)
        setTestedButtons((prev) => {
          let next = prev
          pressed.forEach((p, i) => {
            if (p && !prev.has(i)) {
              if (next === prev) next = new Set(prev)
              next.add(i)
            }
          })
          return next
        })
      }

      if (frame % 2 === 0) {
        setPad(gp ? { id: gp.id, index: gp.index, mapping: gp.mapping, ref: gp } : null)
        setButtons(gp ? gp.buttons.map((b) => ({ pressed: b.pressed, value: b.value })) : [])
        setAxes(gp ? Array.from(gp.axes) : [])
      }
      frame++
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [finishRest])

  const startRest = () => {
    setDrift(null)
    restSamples.current = {
      left: { x: [], y: [] },
      right: { x: [], y: [] }
    }
    restStart.current = performance.now()
    setRestProgress(0)
    setResting(true)
  }

  const resetTrace = () => {
    for (const stick of STICKS) {
      stickRefs.current[stick.key] = { x: 0, y: 0, trace: [] }
    }
    setTestedButtons(new Set())
    setDrift(null)
  }

  const doVibrate = async () => {
    if (!pad?.ref) return
    setRumbling(true)
    await vibrate(pad.ref, { duration: 800 })
    setRumbling(false)
  }

  const share = async () => {
    if (!drift) return
    const worst = Math.max(drift.left?.radius ?? 0, drift.right?.radius ?? 0)
    const level = drift.left && drift.right
      ? (drift.left.radius > drift.right.radius ? drift.left.level : drift.right.level)
      : null
    const canvas = drawScorecard({
      title: '게임패드 드리프트 검사',
      score: level?.label ?? '—',
      scoreLabel: '판정',
      tone: level?.tone || 'accent',
      rows: [
        ['컨트롤러', pad?.id || '알 수 없음'],
        ['왼쪽 스틱 치우침', drift.left ? drift.left.radius.toFixed(4) : '—'],
        ['오른쪽 스틱 치우침', drift.right ? drift.right.radius.toFixed(4) : '—'],
        ['최대 치우침', worst.toFixed(4)],
        ['확인한 버튼', `${testedButtons.size} 개`]
      ]
    })
    await shareOrDownload(canvas, 'gamepad-drift.png')
  }

  if (!pad) {
    return (
      <>
        <Breadcrumb label="게임패드 테스트" />
        <h1>게임패드 스틱 드리프트 테스트</h1>
        <p className="lede">
          스틱을 놓았는데 캐릭터가 혼자 움직이나요? 중고로 산 컨트롤러가 멀쩡한가요?
          설치 없이 여기서 바로 확인하세요.
        </p>
        <div className="pad-area">
          <div>
            <Gamepad2 size={32} style={{ opacity: .5 }} />
            <p>
              컨트롤러를 USB 나 블루투스로 연결한 뒤 <strong>아무 버튼이나 한 번 눌러주세요.</strong>
            </p>
            <p className="dim" style={{ fontSize: 13 }}>
              브라우저는 보안상 버튼 입력이 있기 전까지 컨트롤러를 알려주지 않습니다.
            </p>
          </div>
        </div>
        <div className="section">
          <Callout>
            엑스박스·듀얼센스·듀얼쇼크·조이콘·스위치 프로콘 등 대부분의 컨트롤러가
            별도 드라이버 없이 인식됩니다. 인식이 안 되면 다른 USB 포트나
            크롬·엣지에서 시도해 보세요.
          </Callout>
        </div>
        <RelatedTools current="/gamepad-test" />
      </>
    )
  }

  const worstLevel = drift
    ? (drift.left && drift.right
        ? (drift.left.radius > drift.right.radius ? drift.left.level : drift.right.level)
        : (drift.left?.level || drift.right?.level))
    : null
  const toneColor = { good: 'var(--good)', warn: 'var(--warn)', bad: 'var(--bad)' }

  return (
    <>
      <Breadcrumb label="게임패드 테스트" />
      <h1>게임패드 스틱 드리프트 테스트</h1>
      <p className="lede">
        연결됨 — <span className="mono">{pad.id}</span>
        {pad.mapping !== 'standard' && ' (비표준 매핑: 버튼 이름 대신 번호로 표시합니다)'}
      </p>

      <div className="card">
        <h2>드리프트 검사</h2>
        <p className="muted" style={{ fontSize: 14, marginTop: -6 }}>
          <strong>양쪽 스틱에서 손을 완전히 떼고</strong> 시작 버튼을 누르세요. 5초 동안
          스틱이 정말 중앙에 머무는지 측정합니다. 검사 중에는 컨트롤러를 건드리지 마세요.
        </p>

        {resting && (
          <div style={{ margin: '16px 0' }}>
            <div className="bar-track"><div className="bar-fill" style={{ width: `${restProgress}%` }} /></div>
            <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>
              측정 중... 스틱에서 손을 떼고 기다려 주세요
            </p>
          </div>
        )}

        {drift && !resting && (
          <div style={{ margin: '16px 0' }}>
            <div style={{ fontSize: 26, fontWeight: 800, color: toneColor[worstLevel?.tone] }}>
              {worstLevel?.label}
            </div>
            <div className="grid cols-2" style={{ marginTop: 12 }}>
              {STICKS.map((s) => {
                const d = drift[s.key]
                if (!d) return null
                return (
                  <div key={s.key}>
                    <h3 style={{ color: toneColor[d.level.tone] }}>{s.label} — {d.level.label}</h3>
                    <Stat k="중앙에서 치우침" v={d.radius.toFixed(4)} />
                    <Stat k="X축 / Y축" v={`${d.x.center.toFixed(4)} / ${d.y.center.toFixed(4)}`} />
                    <Stat k="떨림(지터)" v={Math.max(d.x.jitter, d.y.jitter).toFixed(4)} />
                    <Stat k="정지 중 최대" v={Math.max(d.x.peak, d.y.peak).toFixed(4)} />
                  </div>
                )
              })}
            </div>
          </div>
        )}

        <div className="btn-row" style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={startRest} disabled={resting}>
            <Play size={16} /> {resting ? '측정 중...' : drift ? '다시 검사' : '드리프트 검사 시작'}
          </button>
          {drift && (
            <button className="btn" onClick={share}>
              <Share2 size={16} /> 결과 이미지
            </button>
          )}
        </div>
      </div>

      <div className="grid cols-2 section">
        {STICKS.map((s) => (
          <div className="card" key={s.key}>
            <h2>{s.label}</h2>
            <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
              스틱을 끝까지 밀면서 천천히 한 바퀴 돌려보세요. 청록색 궤적이 찌그러지거나
              바깥 원에 닿지 않으면 스틱이 닳은 것입니다.
            </p>
            <div style={{ display: 'flex', gap: 18, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
              <StickCanvas stickRefs={stickRefs} stickKey={s.key} />
              <div style={{ flex: 1, minWidth: 150 }}>
                <Stat k="X" v={(axes[s.xAxis] ?? 0).toFixed(3)} />
                <Stat k="Y" v={(axes[s.yAxis] ?? 0).toFixed(3)} />
                <Stat
                  k="중앙에서 거리"
                  v={Math.hypot(axes[s.xAxis] ?? 0, axes[s.yAxis] ?? 0).toFixed(3)}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="card section">
        <h2>버튼 ({testedButtons.size} / {buttons.length} 확인)</h2>
        <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
          모든 버튼을 한 번씩 눌러 인식되는지 확인하세요. 초록색이 확인된 버튼입니다.
        </p>
        <div className="grid cols-3" style={{ marginTop: 12, gap: 8 }}>
          {buttons.map((b, i) => (
            <div
              key={i}
              className={['kb-key', b.pressed && 'down', !b.pressed && testedButtons.has(i) && 'tested']
                .filter(Boolean).join(' ')}
              style={{ height: 38, fontSize: 12 }}
            >
              {buttonLabel(pad.ref, i)}
            </div>
          ))}
        </div>
      </div>

      <div className="grid cols-2 section">
        <div className="card">
          <h2>아날로그 트리거</h2>
          <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
            천천히 끝까지 당기세요. 0.00 에서 1.00 까지 매끄럽게 올라가야 정상입니다.
          </p>
          {ANALOG_TRIGGERS.map((t) => {
            const v = buttons[t.index]?.value ?? 0
            return (
              <div key={t.index} style={{ marginTop: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13.5 }}>
                  <span className="muted">{t.label}</span>
                  <span className="mono" style={{ fontWeight: 700 }}>{v.toFixed(2)}</span>
                </div>
                <div className="bar-track" style={{ marginTop: 5 }}>
                  <div className="bar-fill" style={{ width: `${v * 100}%` }} />
                </div>
              </div>
            )
          })}
        </div>

        <div className="card">
          <h2>진동</h2>
          {supportsVibration(pad.ref) ? (
            <>
              <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
                양쪽 진동 모터를 동시에 돌립니다. 한쪽만 떨리면 모터 하나가 고장 난 것입니다.
              </p>
              <button className="btn" style={{ marginTop: 12 }} onClick={doVibrate} disabled={rumbling}>
                <Vibrate size={16} /> {rumbling ? '진동 중...' : '진동 테스트'}
              </button>
            </>
          ) : (
            <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
              이 브라우저나 컨트롤러는 진동 제어를 지원하지 않습니다.
              크롬·엣지에서 유선 연결로 시도해 보세요.
            </p>
          )}
        </div>
      </div>

      <div className="section" style={{ display: 'grid', gap: 12 }}>
        <Callout>
          <strong>판정 기준</strong> — 치우침이 0.05 아래면 정상, 0.12 아래면 경미한 드리프트입니다.
          대부분의 게임이 자체 데드존(엑스박스 공식값 기준 좌스틱 약 0.24)을 두기 때문에
          경미한 수준은 실제 게임에서 체감되지 않는 경우가 많습니다. 0.12 를 넘으면
          조준이 밀리는 게 느껴지기 시작합니다.
        </Callout>
        <Callout kind="warn">
          치우침은 작은데 <strong>떨림(지터)이 크다면</strong> 드리프트가 아니라 접촉 불량이나
          전기적 노이즈일 수 있습니다. 무선이라면 유선으로 바꿔서 다시 측정해 보세요.
        </Callout>
      </div>

      <div className="btn-row section">
        <button className="btn" onClick={resetTrace}>
          <RotateCcw size={16} /> 초기화
        </button>
      </div>

      <KofiSupport context="컨트롤러 상태를 확인하셨나요?" />
      <RelatedTools current="/gamepad-test" />
    </>
  )
}
