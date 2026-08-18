import { renderToString } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom'
import App from './App.jsx'

/** 빌드 시 각 라우트를 정적 HTML 로 뽑기 위한 진입점. 브라우저에서는 쓰이지 않는다. */
export function render(url) {
  return renderToString(
    <StaticRouter location={url}>
      <App />
    </StaticRouter>
  )
}

export { ROUTES } from './routes.js'
export { SITE } from './config.js'
