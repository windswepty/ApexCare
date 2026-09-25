// src/theme.js 의 각 테마가 글자를 읽을 수 있는 대비를 갖는지 확인한다.
//   node tools/check_theme_contrast.mjs
//
// 기준: WCAG 본문 글자 4.5:1. 다만 기본 테마(시안)가 이미 4.5 에 못 미치는 조합은
// 기본 테마보다 나빠지지 않으면 통과로 본다(지금 화면보다 읽기 어려워지지 않게).
// 조합은 컴포넌트에서 실제로 많이 쓰는 글자색/배경색 짝이다.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// package.json 이 commonjs 라서 src/theme.js(ESM)를 그대로 import 할 수 없다.
const src = readFileSync(new URL('../src/theme.js', import.meta.url), 'utf8');
const { THEMES, DEFAULT_THEME_ID } = await import('data:text/javascript,' + encodeURIComponent(src));

const IDX = { 300: 3, 400: 4, 500: 5, 600: 6, 800: 8, 900: 9, 950: 10 };

function lum(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// [이름, 글자색 선택, 배경색 선택]
const PAIRS = [
  ['강조 글자(cyan-400) / 페이지 배경', t => t.accent[IDX[400]], t => t.black],
  ['강조 글자(cyan-400) / 패널(zinc-900)', t => t.accent[IDX[400]], t => t.zinc[IDX[900]]],
  ['강조 글자(cyan-400) / 카드(slate-800)', t => t.accent[IDX[400]], t => t.slate[IDX[800]]],
  ['강조 글자(cyan-500) / 패널(zinc-900)', t => t.accent[IDX[500]], t => t.zinc[IDX[900]]],
  ['검은 글자 / 강조 버튼(cyan-500)', t => t.black, t => t.accent[IDX[500]]],
  ['검은 글자 / 강조 버튼 hover(cyan-400)', t => t.black, t => t.accent[IDX[400]]],
  ['보조 글자(gray-400) / 패널(zinc-900)', t => t.gray[IDX[400]], t => t.zinc[IDX[900]]],
  ['보조 글자(slate-400) / 카드(slate-900)', t => t.slate[IDX[400]], t => t.slate[IDX[900]]],
  ['보조 글자(slate-400) / 카드(slate-800)', t => t.slate[IDX[400]], t => t.slate[IDX[800]]],
  ['흐린 글자(slate-500) / 페이지 배경', t => t.slate[IDX[500]], t => t.black],
  ['본문(slate-200) / 카드(slate-900)', t => t.slate[2], t => t.slate[IDX[900]]],
];

const base = THEMES.find(t => t.id === DEFAULT_THEME_ID);
let failed = 0;

// 기본 테마는 Tailwind 원래 색과 정확히 같아야 한다(테마 기능을 넣어도 기본 화면은 그대로).
const tw = createRequire(import.meta.url)('tailwindcss/colors');
const STEPS = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950'];
for (const [family, twName] of [['accent', 'cyan'], ['slate', 'slate'], ['gray', 'gray'], ['zinc', 'zinc']]) {
  const diff = STEPS.filter((s, i) => base[family][i].toLowerCase() !== tw[twName][s]);
  if (diff.length) failed++;
  console.log(`${diff.length ? 'FAIL' : 'OK  '} 기본 테마 ${family} = Tailwind ${twName}${diff.length ? ` (다름: ${diff.join(', ')})` : ''}`);
}
for (const t of THEMES) {
  console.log(`\n[${t.id}] ${t.name}`);
  for (const [name, fg, bg] of PAIRS) {
    const c = contrast(fg(t), bg(t));
    const floor = Math.min(4.5, contrast(fg(base), bg(base)));
    const ok = c + 1e-9 >= floor;
    if (!ok) failed++;
    console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${c.toFixed(2).padStart(5)}  (기준 ${floor.toFixed(2)})  ${name}`);
  }
}
console.log(failed ? `\n실패 ${failed}건` : '\n모든 조합 통과');
process.exit(failed ? 1 : 0);
