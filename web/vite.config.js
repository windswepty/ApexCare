import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 정적 호스팅(Cloudflare Pages / Vercel)용. 앱 빌드와 달리 절대 경로를 쓴다.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true }
})
