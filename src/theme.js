// UI 색 조합(테마).
//
// 컴포넌트는 Tailwind 의 cyan(강조색)·slate/gray/zinc(무채색)·black 클래스를 그대로 쓴다.
// tailwind.config.cjs 가 이 다섯 색을 CSS 변수(--accent-*, --slate-*, --gray-*, --zinc-*, --black)로
// 연결하므로, 여기서 변수 값만 바꾸면 화면 전체 색이 바뀐다.
//
// 경고·위험·성공 색(red·rose·amber·emerald)은 테마와 관계없이 고정한다.
// 되돌릴 수 없는 동작을 알리는 색이 테마 때문에 흐려지면 안 된다.
//
// 각 테마의 대비는 tools/check_theme_contrast.mjs 로 확인한다.

const STEPS = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950'];

// Tailwind v3 기본 팔레트 값 (node_modules/tailwindcss/colors 와 같다)
const TW = {
  cyan: ['#ecfeff', '#cffafe', '#a5f3fc', '#67e8f9', '#22d3ee', '#06b6d4', '#0891b2', '#0e7490', '#155e75', '#164e63', '#083344'],
  slate: ['#f8fafc', '#f1f5f9', '#e2e8f0', '#cbd5e1', '#94a3b8', '#64748b', '#475569', '#334155', '#1e293b', '#0f172a', '#020617'],
  gray: ['#f9fafb', '#f3f4f6', '#e5e7eb', '#d1d5db', '#9ca3af', '#6b7280', '#4b5563', '#374151', '#1f2937', '#111827', '#030712'],
  zinc: ['#fafafa', '#f4f4f5', '#e4e4e7', '#d4d4d8', '#a1a1aa', '#71717a', '#52525b', '#3f3f46', '#27272a', '#18181b', '#09090b'],
  neutral: ['#fafafa', '#f5f5f5', '#e5e5e5', '#d4d4d4', '#a3a3a3', '#737373', '#525252', '#404040', '#262626', '#171717', '#0a0a0a'],
  stone: ['#fafaf9', '#f5f5f4', '#e7e5e4', '#d6d3d1', '#a8a29e', '#78716c', '#57534e', '#44403c', '#292524', '#1c1917', '#0c0a09'],
  blue: ['#eff6ff', '#dbeafe', '#bfdbfe', '#93c5fd', '#60a5fa', '#3b82f6', '#2563eb', '#1d4ed8', '#1e40af', '#1e3a8a', '#172554'],
  violet: ['#f5f3ff', '#ede9fe', '#ddd6fe', '#c4b5fd', '#a78bfa', '#8b5cf6', '#7c3aed', '#6d28d9', '#5b21b6', '#4c1d95', '#2e1065'],
};

// 무채색 테마의 강조색. 어두운 배경 위에서 강조가 되도록 400·500 을 밝게 둔다.
// (bg-cyan-500 위에는 검은 글자가 올라가므로 500 도 밝아야 한다)
const GRAPHITE_ACCENT = ['#fafafa', '#f5f5f5', '#f0f0f0', '#ebebeb', '#e5e5e5', '#d4d4d4', '#a3a3a3', '#737373', '#525252', '#404040', '#262626'];
const STONE_ACCENT = ['#fafaf9', '#f5f5f4', '#f0eeec', '#ebe8e5', '#e7e5e4', '#d6d3d1', '#a8a29e', '#78716c', '#57534e', '#44403c', '#292524'];
// 바이올렛 500(#8b5cf6) 위의 검은 글자는 대비가 모자라 한 단계씩 밝게 당긴다.
const VIOLET_ACCENT = ['#f5f3ff', '#ede9fe', '#ddd6fe', '#d4c8fe', '#c4b5fd', '#a78bfa', '#8b5cf6', '#7c3aed', '#6d28d9', '#5b21b6', '#4c1d95'];

// 한 단계만 바꾼 팔레트. 흐린 글자(500)가 어두운 배경에서 4.5:1 에 못 미치는 테마에 쓴다.
function withStep(scale, step, hex) {
  const out = scale.slice();
  out[STEPS.indexOf(step)] = hex;
  return out;
}
const STONE_NEUTRAL = withStep(TW.stone, '500', '#837c77');
const MIDNIGHT_NEUTRAL = withStep(TW.slate, '500', '#6e7e95');
const VIOLET_NEUTRAL = withStep(TW.zinc, '500', '#77777f');

export const DEFAULT_THEME_ID = 'cyan';

export const THEMES = [
  {
    id: 'cyan',
    name: '시안',
    description: '기본 색 조합',
    accent: TW.cyan, slate: TW.slate, gray: TW.gray, zinc: TW.zinc, black: '#000000',
  },
  {
    id: 'graphite',
    name: '그라파이트',
    description: '차가운 무채색',
    accent: GRAPHITE_ACCENT, slate: TW.neutral, gray: TW.neutral, zinc: TW.neutral, black: '#000000',
  },
  {
    id: 'stone',
    name: '스톤',
    description: '따뜻한 무채색',
    accent: STONE_ACCENT, slate: STONE_NEUTRAL, gray: STONE_NEUTRAL, zinc: STONE_NEUTRAL, black: '#0c0a09',
  },
  {
    id: 'midnight',
    name: '미드나잇 블루',
    description: '남색 배경과 파란 강조색',
    accent: TW.blue, slate: MIDNIGHT_NEUTRAL, gray: MIDNIGHT_NEUTRAL, zinc: MIDNIGHT_NEUTRAL, black: '#020617',
  },
  {
    id: 'violet',
    name: '바이올렛',
    description: '보라 강조색',
    accent: VIOLET_ACCENT, slate: VIOLET_NEUTRAL, gray: VIOLET_NEUTRAL, zinc: VIOLET_NEUTRAL, black: '#000000',
  },
];

const CACHE_KEY = 'apexcare.uiTheme';

export function findTheme(id) {
  return THEMES.find(t => t.id === id) || THEMES.find(t => t.id === DEFAULT_THEME_ID);
}

// '#06b6d4' → '6 182 212'  (rgb(var(--x) / <alpha>) 형식에 넣기 위해 채널만 쓴다)
function channels(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

// 테마를 문서에 적용하고 실제로 적용한 테마를 돌려준다. 알 수 없는 id 는 기본 테마로 적용한다.
export function applyTheme(id) {
  const theme = findTheme(id);
  const style = document.documentElement.style;
  for (const family of ['accent', 'slate', 'gray', 'zinc']) {
    theme[family].forEach((hex, i) => style.setProperty(`--${family}-${STEPS[i]}`, channels(hex)));
  }
  style.setProperty('--black', channels(theme.black));
  document.documentElement.dataset.theme = theme.id;
  // 다음 실행 때 백엔드 응답 전에도 같은 색으로 뜨게 한다. 저장소를 못 써도 동작에는 지장 없다.
  try { localStorage.setItem(CACHE_KEY, theme.id); } catch { /* 무시 */ }
  return theme;
}

export function cachedThemeId() {
  try { return localStorage.getItem(CACHE_KEY) || DEFAULT_THEME_ID; } catch { return DEFAULT_THEME_ID; }
}

// 미리보기 견본에 쓸 대표 색
export function swatch(theme) {
  return { bg: theme.black, panel: theme.zinc[9], accent: theme.accent[4], muted: theme.slate[4] };
}

export { STEPS, TW };
