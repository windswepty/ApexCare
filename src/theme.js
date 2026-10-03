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
// 무채색을 테마 색으로 물들인다. 예전에는 배경·패널이 거의 같은 검정·회색이라 색 조합을 바꿔도 강조색 말고는
// 달라 보이지 않았다. 배경·패널·테두리에 쓰는 어두운 단계는 많이, 글자에 쓰는 밝은 단계는 조금만 섞는다.
const TINT_WEIGHT = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.16, 0.24, 0.30, 0.34, 0.38];
function tinted(neutral, hue, k = 1) {
  return neutral.map((hex, i) => mix(hex, hue[i], TINT_WEIGHT[i] * k));
}
const AMBER = ['#fffbeb', '#fef3c7', '#fde68a', '#fcd34d', '#fbbf24', '#f59e0b', '#d97706', '#b45309', '#92400e', '#78350f', '#451a03'];
const STONE_NEUTRAL = withStep(tinted(TW.stone, AMBER, 0.7), '500', '#867d76');
// 파랑 500(#3b82f6)은 남색 패널 위 글자로 대비가 모자라 조금 밝게 당긴다.
const MIDNIGHT_ACCENT = withStep(TW.blue, '500', '#4d8ef7');
const MIDNIGHT_NEUTRAL = withStep(tinted(TW.slate, TW.blue, 0.8), '500', '#6f80a0');
const VIOLET_NEUTRAL = withStep(tinted(TW.zinc, TW.violet, 0.9), '500', '#7f7896');

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
    accent: STONE_ACCENT, slate: STONE_NEUTRAL, gray: STONE_NEUTRAL, zinc: STONE_NEUTRAL, black: '#120e0b',
  },
  {
    id: 'midnight',
    name: '미드나잇 블루',
    description: '남색 배경과 파란 강조색',
    accent: MIDNIGHT_ACCENT, slate: MIDNIGHT_NEUTRAL, gray: MIDNIGHT_NEUTRAL, zinc: MIDNIGHT_NEUTRAL, black: '#040a1e',
  },
  {
    id: 'violet',
    name: '바이올렛',
    description: '보라 배경과 보라 강조색',
    accent: VIOLET_ACCENT, slate: VIOLET_NEUTRAL, gray: VIOLET_NEUTRAL, zinc: VIOLET_NEUTRAL, black: '#0b0616',
  },
];

const CACHE_KEY = 'apexcare.uiTheme';
const ACCENT_CACHE_KEY = 'apexcare.uiAccent';
const BG_CACHE_KEY = 'apexcare.uiBackground';
const SCALE_CACHE_KEY = 'apexcare.uiScale';
const MOTION_CACHE_KEY = 'apexcare.uiReduceMotion';
export const HEX_RE = /^#[0-9a-f]{6}$/i;

export function findTheme(id) {
  return THEMES.find(t => t.id === id) || THEMES.find(t => t.id === DEFAULT_THEME_ID);
}

// ── 색 계산 ─────────────────────────────────────────────

function rgbOf(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function hexOf(rgb) {
  return '#' + rgb.map(v => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('');
}
// t=0 이면 hex, t=1 이면 target
export function mix(hex, target, t) {
  const a = rgbOf(hex), b = rgbOf(target);
  return hexOf(a.map((v, i) => v + (b[i] - v) * t));
}
function luminance(hex) {
  const [r, g, b] = rgbOf(hex).map(v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
// WCAG 대비. 1 ~ 21
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// 고른 색 하나로 강조색 11단계를 만든다. 고른 색이 500(강조 버튼 배경)이 된다.
const TOWARD_WHITE = { 50: 0.92, 100: 0.84, 200: 0.68, 300: 0.5, 400: 0.28 };
const TOWARD_BLACK = { 600: 0.18, 700: 0.34, 800: 0.5, 900: 0.62, 950: 0.76 };
export function accentScale(hex) {
  const base = hex.toLowerCase();
  return STEPS.map(s => s === '500' ? base
    : s in TOWARD_WHITE ? mix(base, '#ffffff', TOWARD_WHITE[s])
    : mix(base, '#000000', TOWARD_BLACK[s]));
}

// ── 대비 검사 ───────────────────────────────────────────
// 컴포넌트에서 실제로 많이 쓰는 글자색/배경색 짝. accent: 강조색이 들어가는 짝.
const I = Object.fromEntries(STEPS.map((s, i) => [s, i]));
export const CONTRAST_PAIRS = [
  { name: '강조 글자 / 페이지 배경', fg: t => t.accent[I[400]], bg: t => t.black, accent: true },
  { name: '강조 글자 / 패널', fg: t => t.accent[I[400]], bg: t => t.zinc[I[900]], accent: true },
  { name: '강조 글자 / 카드', fg: t => t.accent[I[400]], bg: t => t.slate[I[800]], accent: true },
  { name: '진한 강조 글자 / 패널', fg: t => t.accent[I[500]], bg: t => t.zinc[I[900]], accent: true },
  { name: '강조 버튼의 검은 글자', fg: t => t.black, bg: t => t.accent[I[500]], accent: true },
  { name: '강조 버튼(마우스 올림)의 검은 글자', fg: t => t.black, bg: t => t.accent[I[400]], accent: true },
  { name: '보조 글자 / 패널', fg: t => t.gray[I[400]], bg: t => t.zinc[I[900]] },
  { name: '보조 글자 / 카드(900)', fg: t => t.slate[I[400]], bg: t => t.slate[I[900]] },
  { name: '보조 글자 / 카드(800)', fg: t => t.slate[I[400]], bg: t => t.slate[I[800]] },
  { name: '흐린 글자 / 페이지 배경', fg: t => t.slate[I[500]], bg: t => t.black },
  { name: '본문 / 카드', fg: t => t.slate[I[200]], bg: t => t.slate[I[900]] },
];

// 기준: 본문 글자 4.5:1. 기본 테마가 이미 그보다 낮은 짝은 기본보다 나빠지지 않으면 통과.
export function checkContrast(theme, { accentOnly = false } = {}) {
  const base = findTheme(DEFAULT_THEME_ID);
  return CONTRAST_PAIRS.filter(p => !accentOnly || p.accent).map(p => {
    const ratio = contrast(p.fg(theme), p.bg(theme));
    const floor = Math.min(4.5, contrast(p.fg(base), p.bg(base)));
    return { name: p.name, ratio, floor, ok: ratio + 1e-9 >= floor };
  });
}

// ── 직접 고른 배경색 ────────────────────────────────────
// 고른 색의 색상·채도로 배경·패널·테두리·흐린 글자(무채색 11단계)를 다시 만든다. 밝기는 기본 무채색(zinc)의 단계별
// 밝기를 그대로 써서 어두운 화면의 명암 구조와 글자 대비를 유지한다. 그래서 밝은 색을 골라도 화면이 밝아지지는 않는다.
// 어두운 단계(배경·패널)일수록 채도를 많이, 글자에 쓰는 밝은 단계는 조금만 준다.
const ZINC_L = TW.zinc.map(h => hslOf(h)[2]);
const BG_SAT = [0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.85, 0.9, 0.95];
const BG_SAT_CAPS = [0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0];
const BG_LIFTS = [0, 0.02, 0.04, 0.06, 0.08];

function backgroundScale(hex, satCap, lift) {
  const [h, s] = hslOf(hex);
  const sat = Math.min(s, satCap);
  // lift: 흐린 글자(400·500)가 물든 배경 위에서 대비가 모자랄 때만 조금 밝힌다
  const scale = STEPS.map((_, i) => hexOfHsl(h, sat * BG_SAT[i], Math.min(1, ZINC_L[i] + (i === 4 || i === 5 ? lift : 0))));
  return { scale, black: hexOfHsl(h, sat * 0.9, 0.03) };
}

function withBackground(theme, bg) {
  return { ...theme, slate: bg.scale, gray: bg.scale, zinc: bg.scale, black: bg.black };
}

// 고른 배경색을 이 색 조합(의 기본 강조색)에서 모든 글자 대비를 통과하도록 맞춘다.
// 채도를 줄이고, 그래도 모자라면 흐린 글자만 밝힌다. softened: 채도를 고른 색보다 줄였는지. 끝까지 안 되면 null.
const fitCache = new Map();
export function fitBackground(id, bgHex) {
  if (!bgHex || !HEX_RE.test(bgHex)) return null;
  const key = `${id}|${bgHex.toLowerCase()}`;
  if (fitCache.has(key)) return fitCache.get(key);
  const theme = findTheme(id);
  const wanted = Math.min(hslOf(bgHex.toLowerCase())[1], BG_SAT_CAPS[0]);
  let found = null;
  for (const cap of BG_SAT_CAPS) {
    for (const lift of BG_LIFTS) {
      const bg = backgroundScale(bgHex.toLowerCase(), cap, lift);
      if (checkContrast(withBackground(theme, bg)).every(r => r.ok)) {
        found = { ...bg, softened: cap < wanted - 1e-9 };
        break;
      }
    }
    if (found) break;
  }
  fitCache.set(key, found);
  return found;
}

// 테마 + 직접 고른 배경색 + 직접 고른 강조색
export function composeTheme(id, accentHex, bgHex = null) {
  let theme = findTheme(id);
  const bg = fitBackground(theme.id, bgHex);
  if (bg) theme = withBackground(theme, bg);
  if (!accentHex || !HEX_RE.test(accentHex)) return theme;
  return { ...theme, accent: accentScale(accentHex) };
}

// 이 테마(와 배경색)에서 읽기 어려운 짝 목록. 비어 있으면 써도 된다.
export function accentProblems(id, accentHex, bgHex = null) {
  return checkContrast(composeTheme(id, accentHex, bgHex), { accentOnly: true }).filter(r => !r.ok);
}

// HSL 변환. h: 0~360, s·l: 0~1
function hslOf(hex) {
  const [r, g, b] = rgbOf(hex).map(v => v / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}
function hexOfHsl(h, s, l) {
  const a = s * Math.min(l, 1 - l);
  const f = n => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return hexOf([f(0), f(8), f(4)].map(v => v * 255));
}

// 고른 색의 색상·채도는 두고 밝기만 올려, 처음으로 모든 짝을 통과하는 색을 찾는다.
// 검사하는 짝은 모두 '강조색이 밝을수록 좋아지는' 짝이고 밝기 1 은 흰색이라 반드시 통과한다.
export function readableAccent(id, accentHex, bgHex = null) {
  const hex = accentHex.toLowerCase();
  if (accentProblems(id, hex, bgHex).length === 0) return hex;
  const [h, s, l] = hslOf(hex);
  for (let step = Math.ceil(l * 100) + 1; step <= 100; step++) {
    const candidate = hexOfHsl(h, s, step / 100);
    if (accentProblems(id, candidate, bgHex).length === 0) return candidate;
  }
  return '#ffffff';
}

// 빨강·주황 계열이면 경고·위험 표시와 헷갈릴 수 있다(막지는 않고 알린다).
export function resemblesWarningColor(hex) {
  const [hue, sat] = hslOf(hex);
  return sat >= 0.35 && (hue <= 50 || hue >= 330);
}

// ── 적용 ────────────────────────────────────────────────

// '#06b6d4' → '6 182 212'  (rgb(var(--x) / <alpha>) 형식에 넣기 위해 채널만 쓴다)
function channels(hex) {
  return rgbOf(hex).join(' ');
}

// 테마(와 직접 고른 배경색·강조색)를 문서에 적용한다. 알 수 없는 id 는 기본 테마로 적용한다.
// 배경색은 읽을 수 있게 맞춰 쓰고(fitBackground), 강조색이 이 배경에서 읽기 어려우면 쓰지 않고 테마 기본 강조색을 쓴다.
// 돌려주는 값: { id, accent(실제로 쓴 강조색 또는 null), rejectedAccent, background(실제로 쓴 배경색 또는 null) }
export function applyTheme(id, accentHex = null, bgHex = null) {
  const base = findTheme(id);
  const wantedBg = bgHex && HEX_RE.test(bgHex) ? bgHex.toLowerCase() : null;
  const usableBg = wantedBg && fitBackground(base.id, wantedBg) ? wantedBg : null;
  const wanted = accentHex && HEX_RE.test(accentHex) ? accentHex.toLowerCase() : null;
  const usable = wanted && accentProblems(base.id, wanted, usableBg).length === 0 ? wanted : null;
  const theme = composeTheme(base.id, usable, usableBg);

  const style = document.documentElement.style;
  for (const family of ['accent', 'slate', 'gray', 'zinc']) {
    theme[family].forEach((hex, i) => style.setProperty(`--${family}-${STEPS[i]}`, channels(hex)));
  }
  style.setProperty('--black', channels(theme.black));
  document.documentElement.dataset.theme = base.id;
  // 다음 실행 때 백엔드 응답 전에도 같은 색으로 뜨게 한다. 저장소를 못 써도 동작에는 지장 없다.
  try {
    localStorage.setItem(CACHE_KEY, base.id);
    if (wanted) localStorage.setItem(ACCENT_CACHE_KEY, wanted);
    else localStorage.removeItem(ACCENT_CACHE_KEY);
    if (wantedBg) localStorage.setItem(BG_CACHE_KEY, wantedBg);
    else localStorage.removeItem(BG_CACHE_KEY);
  } catch { /* 무시 */ }
  return { id: base.id, accent: usable, rejectedAccent: wanted && !usable ? wanted : null, background: usableBg };
}

// ── 글자·화면 크기, 움직임 줄이기 ─────────────────────────
// 크기는 문서 글자 크기(rem 기준)를 바꾼다. 화면의 글자·여백·아이콘 대부분이 rem 이라 함께 커진다.
export const UI_SCALES = [90, 100, 110, 125];     // backend/config_manager.py 의 UI_SCALES 와 같아야 한다

export function applyDisplay({ scale = 100, reduceMotion = false } = {}) {
  const s = UI_SCALES.includes(Number(scale)) ? Number(scale) : 100;
  const root = document.documentElement;
  root.style.fontSize = s === 100 ? '' : `${s}%`;
  root.classList.toggle('reduce-motion', Boolean(reduceMotion));
  try {
    localStorage.setItem(SCALE_CACHE_KEY, String(s));
    localStorage.setItem(MOTION_CACHE_KEY, reduceMotion ? '1' : '0');
  } catch { /* 무시 */ }
  return { scale: s, reduceMotion: Boolean(reduceMotion) };
}

export function cachedAppearance() {
  try {
    return {
      id: localStorage.getItem(CACHE_KEY) || DEFAULT_THEME_ID,
      accent: localStorage.getItem(ACCENT_CACHE_KEY) || null,
      background: localStorage.getItem(BG_CACHE_KEY) || null,
      scale: Number(localStorage.getItem(SCALE_CACHE_KEY)) || 100,
      reduceMotion: localStorage.getItem(MOTION_CACHE_KEY) === '1',
    };
  } catch {
    return { id: DEFAULT_THEME_ID, accent: null, background: null, scale: 100, reduceMotion: false };
  }
}

// 미리보기 견본에 쓸 대표 색
export function swatch(theme) {
  return { bg: theme.black, panel: theme.zinc[9], accent: theme.accent[4], muted: theme.slate[4] };
}

export { STEPS, TW };
