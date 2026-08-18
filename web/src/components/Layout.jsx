import { NavLink, Link, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Zap, Sun, Moon, ShieldCheck, EyeOff, LogIn } from 'lucide-react'
import { SITE } from '../config.js'

const YEAR = new Date().getFullYear()

const NAV = [
  { to: '/mouse-polling-rate', label: '마우스 폴링레이트' },
  { to: '/monitor-test', label: '모니터 테스트' },
  { to: '/keyboard-test', label: '키보드 테스트' },
  { to: '/gamepad-test', label: '게임패드' },
  { to: '/system-check', label: '내 PC 진단' }
]

// 프리렌더(빌드 시 Node 실행) 중에는 window/localStorage 가 없다.
// 렌더 도중 이것들을 만지면 빌드가 통째로 죽는다.
const isBrowser = typeof window !== 'undefined'

/**
 * 테마를 바꿀 때 전환 효과를 잠깐 껐다 켠다.
 *
 * color 나 border-color 에 transition 이 걸린 요소는, CSS 변수가 바뀌어도
 * 브라우저가 이전 색을 붙들고 갱신하지 않는다(전환이 시작되면서 값이 고착된다).
 * 그래서 밝은 테마로 바꿔도 흰 글자가 흰 배경 위에 그대로 남는다.
 * 전환이 아예 시작되지 않게 만든 뒤 강제 리플로우로 새 색을 확정하고 되돌린다.
 */
function applyTheme(theme) {
  const root = document.documentElement
  root.classList.add('theme-switching')
  if (theme === 'auto') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
  void root.offsetHeight // 강제 리플로우 — 이 시점에 새 색이 확정된다
  root.classList.remove('theme-switching')
}

function useTheme() {
  const [theme, setTheme] = useState(() => {
    if (!isBrowser) return 'auto'
    try { return localStorage.getItem('apexcare.theme') || 'auto' } catch { return 'auto' }
  })

  useEffect(() => {
    applyTheme(theme)
    try { localStorage.setItem('apexcare.theme', theme) } catch { /* 사파리 프라이빗 모드 */ }
  }, [theme])

  // 'auto' 일 때 운영체제 테마가 바뀌면 우리 JS 를 거치지 않고 변수만 바뀐다.
  // 같은 고착 문제가 생기므로 여기서도 전환을 끄고 다시 칠한다.
  useEffect(() => {
    if (!isBrowser || theme !== 'auto') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('auto')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  return [theme, setTheme]
}

export default function Layout({ children }) {
  const [theme, setTheme] = useTheme()
  const { pathname } = useLocation()

  // 라우트가 바뀌면 항상 맨 위에서 시작해야 한다
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])

  const isDark = theme === 'dark' ||
    (theme === 'auto' && isBrowser && window.matchMedia?.('(prefers-color-scheme: dark)').matches)

  return (
    <div className="shell">
      <header className="site-header">
        <div className="wrap">
          <Link to="/" className="brand">
            <span className="brand-mark"><Zap size={19} strokeWidth={2.6} /></span>
            {SITE.name}
          </Link>
          <nav className="nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? 'active' : '')}>
                {n.label}
              </NavLink>
            ))}
            <button
              className="icon-btn"
              style={{ marginLeft: 6 }}
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              aria-label={isDark ? '밝은 테마로 전환' : '어두운 테마로 전환'}
              title={isDark ? '밝은 테마로 전환' : '어두운 테마로 전환'}
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </div>
      </header>

      <main>
        <div className="wrap">{children}</div>
      </main>

      <footer className="site-footer">
        <div className="wrap">
          <div className="footer-promise">
            <span><ShieldCheck size={15} /> 설치 없음</span>
            <span><LogIn size={15} /> 로그인 없음</span>
            <span><EyeOff size={15} /> 측정값 서버 전송 없음</span>
          </div>
          <p style={{ margin: 0 }}>
            모든 측정은 브라우저 안에서만 이뤄지고, 기록은 이 기기에만 저장됩니다.
            광고와 추적 스크립트를 넣지 않습니다.
          </p>
          <p style={{ marginTop: 10 }}>© {YEAR} {SITE.name}</p>
        </div>
      </footer>
    </div>
  )
}
