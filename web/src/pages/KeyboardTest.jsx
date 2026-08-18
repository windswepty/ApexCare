import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RotateCcw, Keyboard as KeyboardIcon } from 'lucide-react'
import {
  Breadcrumb, Callout, KofiSupport, RelatedTools, Stat, useMeta
} from '../components/ui.jsx'

// [code, 표시라벨, 너비배수]. 너비 1 = 42px 기준.
const LAYOUT = [
  [
    ['Escape', 'Esc', 1], ['', '', 0.6],
    ['F1', 'F1', 1], ['F2', 'F2', 1], ['F3', 'F3', 1], ['F4', 'F4', 1], ['', '', 0.4],
    ['F5', 'F5', 1], ['F6', 'F6', 1], ['F7', 'F7', 1], ['F8', 'F8', 1], ['', '', 0.4],
    ['F9', 'F9', 1], ['F10', 'F10', 1], ['F11', 'F11', 1], ['F12', 'F12', 1], ['', '', 0.4],
    ['PrintScreen', 'PrtSc', 1], ['ScrollLock', 'ScrLk', 1], ['Pause', 'Pause', 1]
  ],
  [
    ['Backquote', '`', 1], ['Digit1', '1', 1], ['Digit2', '2', 1], ['Digit3', '3', 1],
    ['Digit4', '4', 1], ['Digit5', '5', 1], ['Digit6', '6', 1], ['Digit7', '7', 1],
    ['Digit8', '8', 1], ['Digit9', '9', 1], ['Digit0', '0', 1], ['Minus', '-', 1],
    ['Equal', '=', 1], ['Backspace', 'Backspace', 2], ['', '', 0.4],
    ['Insert', 'Ins', 1], ['Home', 'Home', 1], ['PageUp', 'PgUp', 1]
  ],
  [
    ['Tab', 'Tab', 1.5], ['KeyQ', 'Q', 1], ['KeyW', 'W', 1], ['KeyE', 'E', 1], ['KeyR', 'R', 1],
    ['KeyT', 'T', 1], ['KeyY', 'Y', 1], ['KeyU', 'U', 1], ['KeyI', 'I', 1], ['KeyO', 'O', 1],
    ['KeyP', 'P', 1], ['BracketLeft', '[', 1], ['BracketRight', ']', 1], ['Backslash', '\\', 1.5],
    ['', '', 0.4], ['Delete', 'Del', 1], ['End', 'End', 1], ['PageDown', 'PgDn', 1]
  ],
  [
    ['CapsLock', 'Caps', 1.8], ['KeyA', 'A', 1], ['KeyS', 'S', 1], ['KeyD', 'D', 1],
    ['KeyF', 'F', 1], ['KeyG', 'G', 1], ['KeyH', 'H', 1], ['KeyJ', 'J', 1], ['KeyK', 'K', 1],
    ['KeyL', 'L', 1], ['Semicolon', ';', 1], ['Quote', "'", 1], ['Enter', 'Enter', 2.2]
  ],
  [
    ['ShiftLeft', 'Shift', 2.4], ['KeyZ', 'Z', 1], ['KeyX', 'X', 1], ['KeyC', 'C', 1],
    ['KeyV', 'V', 1], ['KeyB', 'B', 1], ['KeyN', 'N', 1], ['KeyM', 'M', 1],
    ['Comma', ',', 1], ['Period', '.', 1], ['Slash', '/', 1], ['ShiftRight', 'Shift', 2.6],
    ['', '', 1.4], ['ArrowUp', '↑', 1]
  ],
  [
    ['ControlLeft', 'Ctrl', 1.4], ['MetaLeft', 'Win', 1.1], ['AltLeft', 'Alt', 1.1],
    ['Space', 'Space', 6.4], ['AltRight', 'Alt', 1.1], ['MetaRight', 'Win', 1.1],
    ['ContextMenu', 'Menu', 1.1], ['ControlRight', 'Ctrl', 1.4], ['', '', 0.4],
    ['ArrowLeft', '←', 1], ['ArrowDown', '↓', 1], ['ArrowRight', '→', 1]
  ]
]

const ALL_CODES = LAYOUT.flat().filter(([code]) => code).map(([code]) => code)

export default function KeyboardTest() {
  useMeta()

  const [down, setDown] = useState(() => new Set())
  const [tested, setTested] = useState(() => new Set())
  const [maxSimultaneous, setMaxSimultaneous] = useState(0)
  const [lastCode, setLastCode] = useState(null)
  const areaRef = useRef(null)

  const onKeyDown = useCallback((e) => {
    // 브라우저 단축키(Ctrl+W, F5, Tab 이동 등)가 먼저 먹으면 테스트가 불가능하다
    e.preventDefault()
    setLastCode(e.code)
    setDown((prev) => {
      if (prev.has(e.code)) return prev
      const next = new Set(prev)
      next.add(e.code)
      setMaxSimultaneous((m) => Math.max(m, next.size))
      return next
    })
    setTested((prev) => {
      if (prev.has(e.code)) return prev
      const next = new Set(prev)
      next.add(e.code)
      return next
    })
  }, [])

  const onKeyUp = useCallback((e) => {
    e.preventDefault()
    setDown((prev) => {
      if (!prev.has(e.code)) return prev
      const next = new Set(prev)
      next.delete(e.code)
      return next
    })
  }, [])

  useEffect(() => {
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    // 창 밖으로 포커스가 나가면 keyup 을 못 받아 키가 눌린 채로 굳는다
    const onBlur = () => setDown(new Set())
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
    }
  }, [onKeyDown, onKeyUp])

  const reset = () => {
    setDown(new Set())
    setTested(new Set())
    setMaxSimultaneous(0)
    setLastCode(null)
  }

  const untested = useMemo(() => ALL_CODES.filter((c) => !tested.has(c)), [tested])
  const progress = ((ALL_CODES.length - untested.length) / ALL_CODES.length) * 100

  return (
    <>
      <Breadcrumb label="키보드 테스트" />
      <h1>키보드 동시입력·눌림 테스트</h1>
      <p className="lede">
        키를 하나씩 눌러 전부 인식되는지 확인하고, 여러 키를 <strong>동시에</strong> 눌러
        몇 개까지 같이 인식되는지(N키 롤오버) 확인하세요.
      </p>

      <div className="card" ref={areaRef}>
        <div className="kb-scroll">
          <div className="kb">
            {LAYOUT.map((row, ri) => (
              <div className="kb-row" key={ri}>
                {row.map(([code, label, w], ki) => (
                  <div
                    key={`${ri}-${ki}`}
                    className={[
                      'kb-key',
                      !code && 'kb-gap',
                      code && down.has(code) && 'down',
                      code && !down.has(code) && tested.has(code) && 'tested'
                    ].filter(Boolean).join(' ')}
                    style={{ flex: `${w} 0 0`, minWidth: 0 }}
                  >
                    {label}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid cols-2 section">
        <div className="card">
          <h2>결과</h2>
          <Stat k="현재 눌린 키" v={down.size ? [...down].join(' + ') : '없음'} />
          <Stat k="동시 인식 최대" v={`${maxSimultaneous} 개`} />
          <Stat k="확인한 키" v={`${ALL_CODES.length - untested.length} / ${ALL_CODES.length}`} />
          <Stat k="마지막 입력 코드" v={lastCode || '—'} />
          <div className="bar-track" style={{ marginTop: 14 }}>
            <div className="bar-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>

        <div className="card">
          <h2>아직 안 눌러본 키 ({untested.length})</h2>
          {untested.length === 0 ? (
            <p className="muted" style={{ fontSize: 14 }}>
              모든 키가 정상 인식됐습니다. 눌림 불량은 없습니다.
            </p>
          ) : (
            <p className="mono" style={{ fontSize: 12.5, color: 'var(--text-muted)', wordBreak: 'break-word' }}>
              {untested.join(', ')}
            </p>
          )}
        </div>
      </div>

      <div className="section" style={{ display: 'grid', gap: 12 }}>
        {maxSimultaneous >= 6 && (
          <Callout>
            <strong>동시 {maxSimultaneous}개까지 인식됩니다.</strong> 6개 이상이면 게임용으로 충분한
            수준입니다. 멤브레인 키보드는 보통 2~3개에서 막힙니다.
          </Callout>
        )}
        <Callout kind="warn">
          <strong>운영체제가 가로채는 키는 여기까지 오지 않습니다.</strong> Alt+Tab, Win, Ctrl+Alt+Del,
          Fn 조합은 브라우저가 받기 전에 윈도우가 먼저 처리합니다. 이 키들이 반응 없다고 해서
          고장은 아닙니다.
        </Callout>
      </div>

      <div className="btn-row section">
        <button className="btn" onClick={reset}>
          <RotateCcw size={16} /> 초기화
        </button>
        <button className="btn" onClick={() => areaRef.current?.scrollIntoView({ behavior: 'smooth' })}>
          <KeyboardIcon size={16} /> 키보드로 이동
        </button>
      </div>

      <KofiSupport context="키보드 눌림 불량을 잡으셨나요?" />
      <RelatedTools current="/keyboard-test" />
    </>
  )
}
