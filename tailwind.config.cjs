// 강조색(cyan)과 무채색(slate·gray·zinc), black 을 CSS 변수로 연결한다.
// 값은 src/theme.js 의 applyTheme() 이 넣는다. 기본 테마는 Tailwind 원래 값과 같다.
// 경고·위험·성공 색(red·rose·amber·emerald 등)은 고정이므로 연결하지 않는다.
const STEPS = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950'];
const scale = (name) =>
  Object.fromEntries(STEPS.map(s => [s, `rgb(var(--${name}-${s}) / <alpha-value>)`]));

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      // 숫자·코드는 고정폭 글꼴로, 한글은 맑은 고딕으로. 예전에는 font-mono 안의 한글이 Windows 기본 고정폭 한글 글꼴(굴림체 등)로
      // 그려져 자간이 넓고 화면의 다른 글자와 따로 놀았다.
      fontFamily: {
        sans: ['Pretendard', '"Segoe UI Variable"', '"Segoe UI"', '"Malgun Gothic"', 'system-ui', 'sans-serif'],
        mono: ['"Cascadia Mono"', 'Consolas', '"Malgun Gothic"', 'ui-monospace', 'monospace'],
      },
      colors: {
        cyan: scale('accent'),
        slate: scale('slate'),
        gray: scale('gray'),
        zinc: scale('zinc'),
        black: 'rgb(var(--black) / <alpha-value>)',
      },
    },
  },
  // 여러 화면이 animate-in / slide-in-from-* / zoom-in 클래스를 쓰는데
  // 이 플러그인이 없으면 전부 무시돼 애니메이션이 동작하지 않는다.
  // CDN 을 쓰던 시절에도 없었으므로 원래부터 죽어 있던 클래스들이다.
  plugins: [require('tailwindcss-animate')],
}
