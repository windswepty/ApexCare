import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './', // Use relative paths for PyWebView local html
  build: {
    outDir: 'dist_react', // Different directory to avoid lock issues
    emptyOutDir: true,
  }
})
