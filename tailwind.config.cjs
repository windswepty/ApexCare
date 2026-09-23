/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: { extend: {} },
  // 여러 화면이 animate-in / slide-in-from-* / zoom-in 클래스를 쓰는데
  // 이 플러그인이 없으면 전부 무시돼 애니메이션이 동작하지 않는다.
  // CDN 을 쓰던 시절에도 없었으므로 원래부터 죽어 있던 클래스들이다.
  plugins: [require('tailwindcss-animate')],
}
