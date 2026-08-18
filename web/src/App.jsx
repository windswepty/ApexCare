import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Home from './pages/Home.jsx'
import MousePolling from './pages/MousePolling.jsx'
import MonitorTest from './pages/MonitorTest.jsx'
import KeyboardTest from './pages/KeyboardTest.jsx'
import SystemCheck from './pages/SystemCheck.jsx'
import NotFound from './pages/NotFound.jsx'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/mouse-polling-rate" element={<MousePolling />} />
        <Route path="/monitor-test" element={<MonitorTest />} />
        <Route path="/keyboard-test" element={<KeyboardTest />} />
        <Route path="/system-check" element={<SystemCheck />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
