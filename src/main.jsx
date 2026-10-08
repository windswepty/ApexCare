import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { applyTheme, applyDisplay, applyIcon, applyMode, cachedAppearance } from './theme.js'

// 첫 화면부터 지난번 색·크기로 그린다. 저장된 값은 백엔드 설정을 받은 뒤 다시 맞춘다(App.jsx).
const cached = cachedAppearance()
applyMode(cached.mode)
applyTheme(cached.id, cached.accent, cached.background)
applyDisplay(cached)
applyIcon(cached.icon, cached.id, cached.accent, cached.background)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
