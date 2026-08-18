import { NavLink, Link, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Zap, Sun, Moon, ShieldCheck, EyeOff, LogIn } from 'lucide-react'
import { SITE } from '../config.js'

const NAV = [
  { to: '/mouse-polling-rate', label: '마우스 폴링레이트' },
  { to: '/monitor-test', label: '모니터 테스트' },
  { to: '/keyboard-test', label: '키보드 테스트' },
  { to: '/system-check', label: '내 PC 진단' }
]

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('apexcare.theme') || 'auto' } catch { return 'auto' }
  })
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'auto') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try { localStorage.setItem('apexcare.theme', theme) } catch { /* 사파리 프라이빗 모드 */ }
  }, [theme])
  return [theme, setTheme]
}

export default function Layout({ children }) {
  const [theme, setTheme] = useTheme()
  const { pathname } = useLocation()

  // 라우트가 바뀌면 항상 맨 위에서 시작해야 한다
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])

  const isDark = theme === 'dark' ||
    (theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)

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
          <p style={{ marginTop: 10 }}>© {new Date().getFullYear()} {SITE.name}</p>
        </div>
      </footer>
    </div>
  )
}
