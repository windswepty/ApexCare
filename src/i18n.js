// 화면 언어(한국어·영어).
//
// 화면의 한국어 문장을 그대로 키로 쓴다: tr('정리할 항목을 선택하세요') → 영어면 locales/en.json 에서 찾은 문장.
// 사전에 없는 문장은 한국어 그대로 보인다(빈칸이나 키 이름을 보여 주지 않는다).
// 값이 들어가는 문장은 {0}·{1} 자리에 넣는다: tr('{0}개 항목 정리', [3]).
//
// 백엔드가 돌려주는 결과 문장(정리 결과·오류 이유 등)은 백엔드 사전(locales/en-backend.json)의 문장·문형으로
// 화면에 그려진 뒤 바꾼다(translateDom). 백엔드가 비교·판단에 쓰는 값은 그대로 두고 보이는 글자만 바꾼다.
// 언어를 바꾸면 화면을 다시 불러온다(모듈이 처음 읽힐 때 정해진 문장들도 새 언어로 다시 만들어지게).
import en from './locales/en.json';
import enBackend from './locales/en-backend.json';

export const LANGUAGES = ['ko', 'en'];          // backend/config_manager.py 의 UI_LANGUAGES 와 같아야 한다
const LANG_KEY = 'apexcare.uiLanguage';
const HAN = /[가-힣]/;

let lang = 'ko';
try {
  lang = localStorage.getItem(LANG_KEY) === 'en' ? 'en' : 'ko';
} catch { /* 저장소를 못 쓰면 한국어 */ }

export function getLanguage() {
  return lang;
}

export function cacheLanguage(value) {
  try {
    localStorage.setItem(LANG_KEY, value === 'en' ? 'en' : 'ko');
  } catch { /* 무시 */ }
}

// 날짜·숫자 표기에 쓰는 지역 설정
export function locale() {
  return lang === 'en' ? 'en-US' : 'ko-KR';
}

function fill(text, args) {
  return text.replace(/\{\{|\}\}|\{(\d+)\}/g, (m, i) => {
    if (m === '{{') return '{';
    if (m === '}}') return '}';
    const v = args ? args[Number(i)] : undefined;
    return v === undefined || v === null ? '' : String(v);
  });
}

export function tr(ko, args) {
  const text = lang === 'en' ? (en[ko] ?? ko) : ko;
  return fill(text, args);
}

// ── 백엔드 문장 ─────────────────────────────────────────
const exact = { ...en, ...(enBackend.exact || {}) };
const patterns = (enBackend.patterns || []).map(([ko, out]) => {
  const parts = ko.split(/(\{\d+\})/);
  const order = [];
  const re = parts.map((p) => {
    const m = p.match(/^\{(\d+)\}$/);
    if (m) {
      order.push(Number(m[1]));
      return '([\\s\\S]*?)';
    }
    return p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('');
  // 고정 글자가 많은 문형부터 맞춘다(짧은 문형이 긴 문장을 먼저 먹지 않게)
  return { re: new RegExp(`^${re}$`), order, out, weight: parts.filter((p) => !/^\{\d+\}$/.test(p)).join('').length };
}).sort((a, b) => b.weight - a.weight);

const SEPARATORS = ['\n', ' — ', '; ', ' / ', ': ', ' · ', ', '];

export function translateText(text, depth = 0) {
  if (lang !== 'en' || typeof text !== 'string' || !HAN.test(text) || depth > 6) return text;
  const lead = text.match(/^\s*/)[0];
  const trail = text.match(/\s*$/)[0];
  const core = text.slice(lead.length, text.length - trail.length);
  if (exact[core] !== undefined) return lead + exact[core] + trail;
  for (const p of patterns) {
    const m = p.re.exec(core);
    if (!m) continue;
    const args = [];
    p.order.forEach((idx, k) => { args[idx] = translateText(m[k + 1], depth + 1); });
    return lead + fill(p.out, args) + trail;
  }
  for (const sep of SEPARATORS) {
    if (core.includes(sep)) {
      const pieces = core.split(sep).map((s) => translateText(s, depth + 1));
      const joined = pieces.join(sep);
      if (joined !== core) return lead + joined + trail;
    }
  }
  return text;
}

// 화면에 그려진 글자 중 남은 한국어(대부분 백엔드가 준 문장)를 바꾼다. 영어일 때만 켠다.
const ATTRS = ['title', 'placeholder', 'aria-label'];

function translateNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const v = node.nodeValue;
    if (v && HAN.test(v)) {
      const t = translateText(v);
      if (t !== v) node.nodeValue = t;
    }
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
  for (const a of ATTRS) {
    const v = node.getAttribute(a);
    if (v && HAN.test(v)) {
      const t = translateText(v);
      if (t !== v) node.setAttribute(a, t);
    }
  }
  if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') return;      // 사용자가 쓰는 칸은 건드리지 않는다
  for (const c of node.childNodes) translateNode(c);
}

export function startDomTranslation(root = document.body) {
  if (lang !== 'en' || !root || typeof MutationObserver === 'undefined') return () => {};
  document.documentElement.lang = 'en';
  translateNode(root);
  const obs = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'characterData') translateNode(r.target);
      else if (r.type === 'attributes') translateNode(r.target);
      else r.addedNodes.forEach(translateNode);
    }
  });
  obs.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  // 확인 창·알림 창의 문장도 바꾼다
  const confirm0 = window.confirm.bind(window);
  const alert0 = window.alert.bind(window);
  window.confirm = (m) => confirm0(translateText(String(m ?? '')));
  window.alert = (m) => alert0(translateText(String(m ?? '')));
  return () => obs.disconnect();
}
