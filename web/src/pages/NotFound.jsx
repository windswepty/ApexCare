import { Link } from 'react-router-dom'
import { useMeta } from '../components/ui.jsx'
import { SITE } from '../config.js'

export default function NotFound() {
  useMeta(`페이지를 찾을 수 없습니다 — ${SITE.name}`)
  return (
    <>
      <h1>404</h1>
      <p className="lede">주소가 잘못되었거나 옮겨진 페이지입니다.</p>
      <Link className="btn primary" to="/">홈으로</Link>
    </>
  )
}
