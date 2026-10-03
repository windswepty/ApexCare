// src/theme.js 의 색 조합과 강조색 직접 지정 로직을 확인한다.
//   node tools/check_theme_contrast.mjs
//
// 1. 기본 테마(시안)가 Tailwind 원래 색과 정확히 같은지 (테마 기능을 넣어도 기본 화면은 그대로)
// 2. 모든 색 조합이 글자 대비 기준을 통과하는지 (기준은 theme.js 의 checkContrast 와 같다)
// 3. 직접 고른 강조색: 읽기 어려운 색을 거부하고, readableAccent() 가 고친 색은 반드시 통과하는지
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// package.json 이 commonjs 라서 src/theme.js(ESM)를 그대로 import 할 수 없다.
const src = readFileSync(new URL('../src/theme.js', import.meta.url), 'utf8');
const T = await import('data:text/javascript,' + encodeURIComponent(src));
const { THEMES, DEFAULT_THEME_ID, STEPS, checkContrast, accentProblems, readableAccent, accentScale, resemblesWarningColor } = T;

let failed = 0;
const report = (ok, msg) => { if (!ok) failed++; console.log(`${ok ? 'OK  ' : 'FAIL'} ${msg}`); };

// 1
const tw = createRequire(import.meta.url)('tailwindcss/colors');
const base = THEMES.find(t => t.id === DEFAULT_THEME_ID);
for (const [family, twName] of [['accent', 'cyan'], ['slate', 'slate'], ['gray', 'gray'], ['zinc', 'zinc']]) {
  const diff = STEPS.filter((s, i) => base[family][i].toLowerCase() !== tw[twName][s]);
  report(!diff.length, `기본 테마 ${family} = Tailwind ${twName}${diff.length ? ` (다름: ${diff.join(', ')})` : ''}`);
}

// 2
for (const t of THEMES) {
  console.log(`\n[${t.id}] ${t.name}`);
  for (const r of checkContrast(t)) {
    report(r.ok, `${r.ratio.toFixed(2).padStart(5)}  (기준 ${r.floor.toFixed(2)})  ${r.name}`);
  }
}

// 3
console.log('\n[강조색 직접 지정]');
const scale = accentScale('#06b6d4');
report(scale.length === 11 && scale[5] === '#06b6d4' && STEPS.every((_, i) => /^#[0-9a-f]{6}$/.test(scale[i])),
  'accentScale: 11단계, 고른 색이 500');
// 어두운 파랑은 검은 글자를 올릴 수 없어 거부돼야 한다
report(accentProblems('cyan', '#1d4ed8').length > 0, '어두운 파랑(#1d4ed8)은 거부');
report(accentProblems('cyan', '#000000').length > 0, '검정(#000000)은 거부');
report(accentProblems('cyan', '#22d3ee').length === 0, '밝은 시안(#22d3ee)은 허용');
// 여러 색을 모든 테마에서 고쳐 보고, 고친 색이 통과하는지 확인
const samples = [];
for (let h = 0; h < 360; h += 15) for (const l of [0.2, 0.45, 0.7]) samples.push(hsl(h, 0.8, l));
samples.push('#000000', '#ffffff', '#808080', '#1d4ed8', '#7f1d1d');
let fixedOk = 0, total = 0, untouched = 0;
for (const t of THEMES) for (const hex of samples) {
  total++;
  const fixed = readableAccent(t.id, hex);
  if (accentProblems(t.id, fixed).length === 0) fixedOk++;
  if (accentProblems(t.id, hex).length === 0 && fixed !== hex.toLowerCase()) untouched++;
}
report(fixedOk === total, `readableAccent 결과가 모두 통과 (${fixedOk}/${total})`);
report(untouched === 0, `이미 읽을 수 있는 색은 바꾸지 않음 (바뀐 수 ${untouched})`);
// 고친 색은 원래 색상(hue)을 유지해야 한다. 어두운 빨강은 여전히 빨강 계열이어야 한다
report(resemblesWarningColor(readableAccent('cyan', '#7f1d1d')), `어두운 빨강을 고쳐도 빨강 계열 유지 (${readableAccent('cyan', '#7f1d1d')})`);
report(resemblesWarningColor('#ef4444') && resemblesWarningColor('#f59e0b') && !resemblesWarningColor('#3b82f6') && !resemblesWarningColor('#a3a3a3'),
  '빨강·주황 계열 경고 판정');

// 4
console.log('\n[배경색 직접 지정]');
const { fitBackground, composeTheme } = T;
const bgSamples = [];
for (let h = 0; h < 360; h += 20) for (const s of [0.3, 0.7, 1]) for (const l of [0.1, 0.5, 0.9]) bgSamples.push(hsl(h, s, l));
bgSamples.push('#000000', '#ffffff', '#808080');
let bgOk = 0, bgTotal = 0, bgNull = 0;
for (const t of THEMES) for (const hex of bgSamples) {
  bgTotal++;
  if (!fitBackground(t.id, hex)) { bgNull++; continue; }
  if (checkContrast(composeTheme(t.id, null, hex)).every(r => r.ok)) bgOk++;
}
report(bgNull === 0, `모든 배경색을 읽을 수 있게 맞춤 (못 맞춘 수 ${bgNull})`);
report(bgOk === bgTotal, `맞춘 배경에서 모든 글자 대비 통과 (${bgOk}/${bgTotal})`);
const purple = fitBackground('cyan', '#7c3aed');
report(Boolean(purple) && purple.scale[9] !== base.zinc[9], `배경색이 실제로 패널 색을 바꿈 (보라 → 패널 ${purple && purple.scale[9]})`);
// 배경색을 바꿔도 직접 고른 강조색 검사는 그 배경 위에서 한다
const onPurple = readableAccent('cyan', '#1d4ed8', '#7c3aed');
report(accentProblems('cyan', onPurple, '#7c3aed').length === 0, `보라 배경에서 고친 강조색도 통과 (${onPurple})`);

console.log(failed ? `\n실패 ${failed}건` : '\n모든 검사 통과');
process.exit(failed ? 1 : 0);

function hsl(h, s, l) {
  const a = s * Math.min(l, 1 - l);
  const f = n => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return '#' + [f(0), f(8), f(4)].map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
}
