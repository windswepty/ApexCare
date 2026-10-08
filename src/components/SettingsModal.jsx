import React, { useState, useEffect, useRef } from 'react';
import { Settings, X, Check, Palette, Pipette, AlertTriangle, Wand2, RotateCcw, PaintBucket, Monitor, Sparkles, ShieldCheck } from 'lucide-react';
import AppLogo from './AppLogo';
import {
  THEMES, HEX_RE, DEFAULT_THEME_ID, UI_SCALES, applyTheme, applyDisplay, swatch, findTheme, composeTheme,
  accentProblems, readableAccent, resemblesWarningColor, fitBackground,
  ICON_PRESETS, iconColors, applyIcon, syncWindowIcon,
} from '../theme';

// 키보드로 갈 수 있는 것(Tab 이 창 안에서만 돌게 할 때 쓴다)
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

// 예전 '저장하기' 버튼은 아무것도 저장하지 않고 "설정이 저장되었습니다" 를 띄웠다.
// 이제 고르면 바로 적용하고, 백엔드가 저장에 성공했을 때만 성공을 알린다.
// 저장에 실패하면 화면도 이전 색으로 되돌린다. 다음 실행 때 보일 색과 어긋나지 않게.
export default function SettingsModal({ isOpen, onClose, addToast, appearance, onAppearanceChange, onOpenSetupWizard }) {
  const { id: themeId, accent = null, background = null, scale = 100, reduceMotion = false, icon = '' } = appearance || {};
  const [saving, setSaving] = useState(null);   // 'theme:<id>' | 'accent' | 'background' | 'scale' | 'motion' | 'reset'
  const [draft, setDraft] = useState('');       // 편집 중인 강조색
  const [hexText, setHexText] = useState('');   // 직접 입력 칸
  const [bgDraft, setBgDraft] = useState('');   // 편집 중인 배경색
  const [bgText, setBgText] = useState('');
  const [iconDraft, setIconDraft] = useState('#22d3ee');   // 아이콘 바탕색 직접 고르기
  // 시스템을 바꾸기 전 Windows 복원 지점 만들기(null = 아직 읽지 못함)
  const [rpEnabled, setRpEnabled] = useState(null);
  const [rpSaving, setRpSaving] = useState(false);

  // 대화상자: 열면 닫기 버튼으로 초점을 옮기고, Tab 은 창 안에서만 돌고, Esc 로 닫는다. 닫으면 열었던 곳으로 돌려준다.
  // 예전에는 초점이 오버레이 뒤에 남아 Tab 이 가려진 창 닫기 버튼으로 갔다.
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);          // App 이 렌더마다 새 함수를 넘겨도 초점을 다시 옮기지 않게
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!isOpen) return undefined;
    const before = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !dialogRef.current) return;
      const items = [...dialogRef.current.querySelectorAll(FOCUSABLE)]
        .filter((el) => !el.disabled && el.getClientRects().length > 0);
      if (!items.length) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const inside = dialogRef.current.contains(document.activeElement);
      if (e.shiftKey ? (!inside || document.activeElement === first) : (!inside || document.activeElement === last)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (before && typeof before.focus === 'function') before.focus();
    };
  }, [isOpen]);

  // 창을 열 때와 색 조합을 바꿨을 때 지금 쓰는 강조색으로 맞춘다(색 조합을 바꾸면 직접 지정한 색은 해제된다)
  useEffect(() => {
    if (!isOpen) return;
    const current = accent || composeTheme(themeId, null, background).accent[5];
    setDraft(current);
    setHexText(current);
    const bg = background || findTheme(themeId).zinc[9];
    setBgDraft(bg);
    setBgText(bg);
    if (icon && HEX_RE.test(icon)) setIconDraft(icon);
  }, [isOpen, themeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const api = window.pywebview && window.pywebview.api;
  const current = { id: themeId, accent, background, scale, reduceMotion, icon };

  useEffect(() => {
    if (!isOpen || !api?.getRestorePointSetting) return;
    api.getRestorePointSetting().then((r) => setRpEnabled(r?.enabled !== false)).catch(() => setRpEnabled(null));
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleRestorePoint = async () => {
    if (rpEnabled === null || rpSaving || !api?.setRestorePointSetting) return;
    const next = !rpEnabled;
    setRpSaving(true);
    try {
      const r = await api.setRestorePointSetting(next);
      if (r?.success) {
        setRpEnabled(next);
        addToast?.(next ? '시스템을 바꾸기 전에 Windows 복원 지점을 만듭니다.' : '복원 지점을 만들지 않습니다.', 'success');
      } else {
        addToast?.(r?.message || '설정을 저장하지 못했습니다.', 'error');
      }
    } catch (e) {
      addToast?.(`설정을 저장하지 못했습니다: ${e}`, 'error');
    }
    setRpSaving(false);
  };

  // 적용 → 저장 → 실패 시 되돌림. patch: 바꿀 화면 설정 일부
  const commit = async (key, patch, save, okMessage) => {
    if (!api || typeof save !== 'function') {
      if (addToast) addToast('API가 준비되지 않아 화면 설정을 저장할 수 없습니다.', 'error');
      return;
    }
    const prev = current;
    const next = { ...prev, ...patch };
    const show = (a) => {
      const applied = applyTheme(a.id, a.accent, a.background);
      // 아이콘 색(강조색을 따르는 경우가 있어 색 조합이 바뀔 때마다 다시 칠한다)과 작업 표시줄의 창 아이콘
      const colors = applyIcon(a.icon, applied.id, a.accent, a.background);
      if (a.icon || prev.icon) {
        syncWindowIcon(a.icon, colors).then((r) => {
          if (r && r.success === false && addToast) addToast(`작업 표시줄 고정 단추: ${r.message}`, 'error');
        });
      }
      onAppearanceChange({ ...a, id: applied.id, ...applyDisplay(a) });
    };
    show(next);
    setSaving(key);
    try {
      const res = await save();
      if (!res?.success) throw new Error(res?.message || '저장 실패');
      if (addToast) addToast(okMessage, 'success');
    } catch (e) {
      show(prev);
      if (addToast) addToast(`화면 설정을 저장하지 못했습니다: ${e.message || e}`, 'error');
    } finally {
      setSaving(null);
    }
  };

  // 색 조합을 고르면 직접 지정한 강조색·배경색은 해제한다. 예전에는 강조색이 남아 모든 색 조합에 덮어씌워져,
  // 색 조합을 바꿔도 화면이 거의 그대로였다.
  const chooseTheme = (id) => {
    if (saving || id === themeId) return;
    const cleared = [accent && '강조색', background && '배경색'].filter(Boolean);
    commit(`theme:${id}`, { id, accent: null, background: null },
      api && (async () => {
        const res = await api.setUiTheme(id);
        if (!res?.success) return res;
        for (const [has, clear, what] of [[accent, () => api.setUiAccent(''), '강조색'],
          [background, () => api.setUiBackground(''), '배경색']]) {
          if (!has) continue;
          const r = await clear();
          if (!r?.success) {
            return { success: false, message: `색 조합은 저장했지만 직접 지정한 ${what}을 해제하지 못했습니다(${r?.message || '저장 실패'})` };
          }
        }
        return res;
      }),
      cleared.length ? `색 조합을 저장했습니다. 직접 지정했던 ${cleared.join('·')}은 해제했습니다.` : '색 조합을 저장했습니다.');
  };

  const saveAccent = (value) => {
    if (saving) return;
    commit('accent', { accent: value }, api && (() => api.setUiAccent(value || '')),
      value ? '강조색을 저장했습니다.' : '색 조합의 기본 강조색으로 되돌렸습니다.');
  };

  const saveBackground = (value) => {
    if (saving) return;
    commit('background', { background: value }, api && (() => api.setUiBackground(value || '')),
      value ? '배경색을 저장했습니다.' : '색 조합의 기본 배경색으로 되돌렸습니다.');
  };

  const saveScale = (value) => {
    if (saving || value === scale) return;
    commit('scale', { scale: value }, api && (() => api.setUiScale(value)), `글자·화면 크기를 ${value}% 로 저장했습니다.`);
  };

  const saveMotion = (value) => {
    if (saving) return;
    commit('motion', { reduceMotion: value }, api && (() => api.setUiReduceMotion(value)),
      value ? '움직임 줄이기를 켰습니다.' : '움직임 줄이기를 껐습니다.');
  };

  const saveIcon = (value) => {
    if (saving || value === icon) return;
    commit('icon', { icon: value }, api && (() => api.setUiIcon(value)),
      value ? '앱 아이콘 색을 저장했습니다.' : '앱 아이콘을 기본 색으로 되돌렸습니다.');
  };

  const resetAll = () => {
    if (saving) return;
    commit('reset', { id: DEFAULT_THEME_ID, accent: null, background: null, scale: 100, reduceMotion: false, icon: '' },
      api && (() => api.resetUiAppearance()), '화면 설정을 모두 기본값으로 되돌렸습니다.');
  };

  if (!isOpen) return null;

  const draftValid = HEX_RE.test(draft);
  const problems = draftValid ? accentProblems(themeId, draft, background) : [];
  const preview = composeTheme(themeId, draftValid ? draft : null, background);
  const fixed = draftValid && problems.length ? readableAccent(themeId, draft, background) : null;
  // 저장된 강조색이 지금 색 조합·배경에서는 읽기 어려워 쓰이지 않는 경우
  const savedButUnused = accent && accentProblems(themeId, accent, background).length > 0;
  const isStored = draftValid && accent === draft.toLowerCase();
  // '적용됨' 은 지금 화면에 실제로 쓰이고 있을 때만. 저장은 됐지만 이 색 조합에서는 쓰이지 않으면 그렇게 말한다.
  const isSaved = isStored && problems.length === 0;

  const setBoth = (hex) => { setDraft(hex); setHexText(hex); };

  const bgValid = HEX_RE.test(bgDraft);
  const bgFit = bgValid ? fitBackground(themeId, bgDraft) : null;
  const bgPreview = composeTheme(themeId, accent, bgValid ? bgDraft : null);
  const bgSaved = bgValid && background === bgDraft.toLowerCase();
  const setBg = (hex) => { setBgDraft(hex); setBgText(hex); };
  const isDefault = themeId === DEFAULT_THEME_ID && !accent && !background && scale === 100 && !reduceMotion && !icon;
  // 지금 화면의 색(아이콘 미리보기에 쓴다). 저장됐지만 읽기 어려워 쓰지 않는 강조색은 빼야 실제 아이콘과 같다.
  const shown = composeTheme(themeId, savedButUnused ? null : accent, background);
  const iconCustom = Boolean(icon) && HEX_RE.test(icon);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
      role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div ref={dialogRef} className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[90%] max-w-lg max-h-[90vh] flex flex-col border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-gray-100 dark:border-slate-800 flex justify-between items-center bg-gray-50 dark:bg-slate-800/30 flex-shrink-0">
          <div className="flex items-center gap-2 text-gray-800 dark:text-gray-200">
            <Settings className="w-5 h-5" />
            <h2 id="settings-title" className="font-bold">환경 설정</h2>
          </div>
          <button ref={closeRef} onClick={onClose} aria-label="닫기" className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar">
          {/* ── 색 조합 ── */}
          <section className="space-y-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
                <Palette className="w-4 h-4 text-cyan-400" />
                색 조합
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                고르면 배경·패널·강조색이 함께 바뀌고 다음 실행 때도 유지됩니다. 직접 지정한 강조색·배경색은 해제됩니다.
                경고·위험을 알리는 빨강·주황은 색 조합과 관계없이 그대로입니다.
              </p>
            </div>

            <div role="radiogroup" aria-label="색 조합" className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {THEMES.map((theme) => {
                const s = swatch(theme);
                const selected = theme.id === themeId;
                return (
                  <button
                    key={theme.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={saving !== null}
                    onClick={() => chooseTheme(theme.id)}
                    className={`text-left rounded-xl border p-2 transition-colors disabled:cursor-wait ${
                      selected
                        ? 'border-cyan-400 ring-1 ring-cyan-400'
                        : 'border-black/10 dark:border-slate-700 hover:border-slate-500'
                    }`}
                  >
                    {/* 견본: 배경 / 패널 / 강조색 / 보조 글자 */}
                    <div className="h-14 rounded-lg p-2 flex flex-col justify-between" style={{ background: s.bg }}>
                      <div className="h-2 w-2/3 rounded-full" style={{ background: s.accent }} />
                      <div className="rounded-md p-1.5 space-y-1" style={{ background: s.panel }}>
                        <div className="h-1 w-3/4 rounded-full" style={{ background: s.muted }} />
                        <div className="h-1 w-1/2 rounded-full" style={{ background: s.muted, opacity: 0.6 }} />
                      </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-1">
                      <span className="text-xs font-bold text-gray-900 dark:text-slate-100 truncate">{theme.name}</span>
                      {selected && <Check className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />}
                    </div>
                    <span className="text-[0.625rem] text-gray-500 dark:text-slate-400">
                      {saving === `theme:${theme.id}` ? '저장 중…' : theme.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* ── 강조색 직접 지정 ── */}
          <section className="space-y-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
                <Pipette className="w-4 h-4 text-cyan-400" />
                강조색 직접 지정
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                글자를 읽기 어려운 색(대비 4.5:1 미만)은 적용할 수 없습니다. 이럴 때는 읽을 수 있는 가장 가까운 색을 제안합니다.
              </p>
            </div>

            {savedButUnused && (
              <p className="text-xs text-amber-400 flex gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                저장된 강조색 {accent} 은 지금 색 조합에서 읽기 어려워 기본 강조색을 쓰고 있습니다.
              </p>
            )}

            <div className="flex items-center gap-3">
              <input
                type="color"
                aria-label="강조색 고르기"
                value={draftValid ? draft : '#000000'}
                onChange={(e) => setBoth(e.target.value)}
                className="w-11 h-11 rounded-lg border border-black/10 dark:border-slate-700 bg-transparent cursor-pointer p-0.5"
              />
              <input
                type="text"
                aria-label="강조색 코드"
                value={hexText}
                maxLength={7}
                spellCheck={false}
                onChange={(e) => {
                  const v = e.target.value.trim();
                  setHexText(v);
                  if (HEX_RE.test(v)) setDraft(v.toLowerCase());
                }}
                className={`w-28 px-3 py-2 rounded-lg font-mono text-sm bg-gray-50 dark:bg-slate-800 border text-gray-900 dark:text-slate-100 ${
                  HEX_RE.test(hexText) ? 'border-black/10 dark:border-slate-700' : 'border-rose-500'
                }`}
              />
              {/* 미리보기: 지금 색 조합의 패널 위에 강조 글자와 강조 버튼 */}
              <div className="flex-1 min-w-0 rounded-lg px-3 py-2 flex items-center justify-between gap-2" style={{ background: preview.zinc[9] }}>
                <span className="text-xs font-bold truncate" style={{ color: preview.accent[4] }}>강조 글자</span>
                <span className="text-xs font-bold px-2.5 py-1 rounded-md flex-shrink-0" style={{ background: preview.accent[5], color: preview.black }}>버튼</span>
              </div>
            </div>
            {!HEX_RE.test(hexText) && (
              <p className="text-xs text-rose-400">#과 16진수 6자리로 입력하세요. 예: #22d3ee</p>
            )}

            {problems.length > 0 && (
              <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-3 space-y-2">
                <p className="text-xs font-bold text-rose-400 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  이 색은 지금 색 조합에서 읽기 어렵습니다
                </p>
                <ul className="text-[0.6875rem] text-gray-600 dark:text-slate-300 space-y-0.5 font-mono">
                  {problems.map(p => (
                    <li key={p.name}>{p.name}: {p.ratio.toFixed(2)}:1 (필요 {p.floor.toFixed(1)}:1)</li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => setBoth(fixed)}
                  className="text-xs font-bold px-3 py-1.5 rounded-md bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 flex items-center gap-1.5"
                >
                  <Wand2 className="w-3.5 h-3.5" />
                  읽을 수 있게 조정
                  <span className="inline-block w-3 h-3 rounded-sm border border-white/20" style={{ background: fixed }} />
                  <span className="font-mono">{fixed}</span>
                </button>
              </div>
            )}

            {draftValid && problems.length === 0 && resemblesWarningColor(draft) && (
              <p className="text-xs text-amber-400 flex gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                빨강·주황 계열이라 경고·위험 표시와 헷갈릴 수 있습니다. 적용은 할 수 있습니다.
              </p>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                disabled={!draftValid || problems.length > 0 || isSaved || saving !== null}
                onClick={() => saveAccent(draft.toLowerCase())}
                className="flex-1 px-4 py-2 rounded-lg font-bold text-sm bg-cyan-500 hover:bg-cyan-400 text-black disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {saving === 'accent' ? '저장 중…' : isSaved ? '적용됨' : isStored ? '저장됨 (이 색 조합에서는 쓰지 않음)' : '이 강조색 적용'}
              </button>
              {accent && (
                <button
                  type="button"
                  disabled={saving !== null}
                  onClick={() => { saveAccent(null); setBoth(findTheme(themeId).accent[5]); }}
                  className="px-4 py-2 rounded-lg font-bold text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 disabled:opacity-40 flex items-center gap-1.5 transition-colors"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  기본 강조색
                </button>
              )}
            </div>
          </section>

          {/* ── 배경색 직접 지정 ── */}
          <section className="space-y-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
                <PaintBucket className="w-4 h-4 text-cyan-400" />
                배경색 직접 지정
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                고른 색으로 배경·패널·테두리를 물들입니다. 글자가 잘 보이도록 밝기는 어두운 화면에 맞추고, 색만 반영합니다.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="color"
                aria-label="배경색 고르기"
                value={bgValid ? bgDraft : '#000000'}
                onChange={(e) => setBg(e.target.value)}
                className="w-11 h-11 rounded-lg border border-black/10 dark:border-slate-700 bg-transparent cursor-pointer p-0.5"
              />
              <input
                type="text"
                aria-label="배경색 코드"
                value={bgText}
                maxLength={7}
                spellCheck={false}
                onChange={(e) => {
                  const v = e.target.value.trim();
                  setBgText(v);
                  if (HEX_RE.test(v)) setBgDraft(v.toLowerCase());
                }}
                className={`w-28 px-3 py-2 rounded-lg font-mono text-sm bg-gray-50 dark:bg-slate-800 border text-gray-900 dark:text-slate-100 ${
                  HEX_RE.test(bgText) ? 'border-black/10 dark:border-slate-700' : 'border-rose-500'
                }`}
              />
              {/* 미리보기: 배경 위의 패널, 그 안의 본문·흐린 글자·강조 글자 */}
              <div className="flex-1 min-w-0 rounded-lg p-1.5" style={{ background: bgPreview.black }}>
                <div className="rounded-md px-2.5 py-1.5 border" style={{ background: bgPreview.zinc[9], borderColor: bgPreview.zinc[8] }}>
                  <div className="text-xs font-bold truncate" style={{ color: bgPreview.slate[2] }}>본문 글자</div>
                  <div className="text-[0.625rem] truncate" style={{ color: bgPreview.slate[5] }}>
                    흐린 글자 · <span style={{ color: bgPreview.accent[4] }}>강조</span>
                  </div>
                </div>
              </div>
            </div>
            {!HEX_RE.test(bgText) && (
              <p className="text-xs text-rose-400">#과 16진수 6자리로 입력하세요. 예: #2e1065</p>
            )}
            {bgFit?.softened && (
              <p className="text-xs text-amber-400 flex gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                이 색 그대로는 글자를 읽기 어려워 조금 옅게(채도를 낮춰) 적용합니다.
              </p>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                disabled={!bgValid || !bgFit || bgSaved || saving !== null}
                onClick={() => saveBackground(bgDraft.toLowerCase())}
                className="flex-1 px-4 py-2 rounded-lg font-bold text-sm bg-cyan-500 hover:bg-cyan-400 text-black disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {saving === 'background' ? '저장 중…' : bgSaved ? '적용됨' : '이 배경색 적용'}
              </button>
              {background && (
                <button
                  type="button"
                  disabled={saving !== null}
                  onClick={() => { saveBackground(null); setBg(findTheme(themeId).zinc[9]); }}
                  className="px-4 py-2 rounded-lg font-bold text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 disabled:opacity-40 flex items-center gap-1.5 transition-colors"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  기본 배경색
                </button>
              )}
            </div>
          </section>

          {/* ── 앱 아이콘 색 ── */}
          <section className="space-y-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
                <Sparkles className="w-4 h-4 text-cyan-400" />
                앱 아이콘 색
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
                사이드바·제목 표시줄·로딩 화면의 로고와 작업 표시줄 아이콘(이 계정에서 고정해 둔 단추 포함)이 함께 바뀝니다.
                바탕화면·시작 메뉴 바로 가기는 이 PC 의 모든 계정이 함께 쓰는 것이라 그대로 둡니다.
              </p>
            </div>
            <div role="radiogroup" aria-label="앱 아이콘 색" className="grid grid-cols-4 gap-2">
              {ICON_PRESETS.map((p) => {
                const c = iconColors(p.id, shown);
                const selected = icon === p.id;
                return (
                  <button
                    key={p.id || 'default'}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={saving !== null}
                    onClick={() => saveIcon(p.id)}
                    className={`flex flex-col items-center gap-1.5 rounded-xl border p-2.5 transition-colors disabled:cursor-wait ${
                      selected ? 'border-cyan-400 ring-1 ring-cyan-400' : 'border-black/10 dark:border-slate-700 hover:border-slate-500'
                    }`}
                  >
                    <AppLogo className="w-9 h-9" tile={c.tile} glyph={c.glyph} />
                    <span className="text-[0.6875rem] font-bold text-gray-900 dark:text-slate-100">{p.name}</span>
                  </button>
                );
              })}
              <div className={`flex flex-col items-center gap-1.5 rounded-xl border p-2.5 ${
                iconCustom ? 'border-cyan-400 ring-1 ring-cyan-400' : 'border-black/10 dark:border-slate-700'
              }`}>
                <AppLogo className="w-9 h-9" tile={iconColors(iconDraft, shown).tile} glyph={iconColors(iconDraft, shown).glyph} />
                <div className="flex items-center gap-1">
                  <input
                    type="color"
                    aria-label="아이콘 바탕색 고르기"
                    value={iconDraft}
                    onChange={(e) => setIconDraft(e.target.value)}
                    className="w-5 h-5 rounded border border-black/10 dark:border-slate-700 bg-transparent cursor-pointer p-0"
                  />
                  <button
                    type="button"
                    disabled={saving !== null || icon === iconDraft.toLowerCase()}
                    onClick={() => saveIcon(iconDraft.toLowerCase())}
                    className="text-[0.6875rem] font-bold text-cyan-400 disabled:opacity-40"
                  >
                    {icon === iconDraft.toLowerCase() ? '적용됨' : '직접 지정'}
                  </button>
                </div>
              </div>
            </div>
          </section>

          {/* ── 화면 (크기·움직임) ── */}
          <section className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
              <Monitor className="w-4 h-4 text-cyan-400" />
              화면
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-semibold text-gray-700 dark:text-slate-300">글자·화면 크기</div>
              <div role="radiogroup" aria-label="글자·화면 크기" className="grid grid-cols-4 gap-2">
                {UI_SCALES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={scale === s}
                    disabled={saving !== null}
                    onClick={() => saveScale(s)}
                    className={`py-2 rounded-lg text-sm font-bold border transition-colors disabled:cursor-wait ${
                      scale === s
                        ? 'border-cyan-400 bg-cyan-500/10 text-cyan-400'
                        : 'border-black/10 dark:border-slate-700 text-gray-700 dark:text-slate-300 hover:border-slate-500'
                    }`}
                  >
                    {s}%{s === 100 ? ' (기본)' : ''}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              role="switch"
              aria-checked={reduceMotion}
              disabled={saving !== null}
              onClick={() => saveMotion(!reduceMotion)}
              className="w-full flex items-center justify-between gap-3 rounded-lg border border-black/10 dark:border-slate-700 px-3 py-2.5 text-left hover:border-slate-500 transition-colors disabled:cursor-wait"
            >
              <span>
                <span className="block text-xs font-semibold text-gray-700 dark:text-slate-300">움직임 줄이기</span>
                <span className="block text-[0.6875rem] text-gray-500 dark:text-slate-400">화면 전환 애니메이션과 부드러운 스크롤을 끕니다</span>
              </span>
              <span className={`relative w-10 h-6 rounded-full flex-shrink-0 transition-colors ${reduceMotion ? 'bg-cyan-500' : 'bg-gray-300 dark:bg-slate-700'}`}>
                <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${reduceMotion ? 'left-5' : 'left-1'}`} />
              </span>
            </button>

            <button
              type="button"
              disabled={isDefault || saving !== null}
              onClick={resetAll}
              className="w-full px-4 py-2 rounded-lg font-bold text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 disabled:opacity-40 flex items-center justify-center gap-1.5 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {saving === 'reset' ? '되돌리는 중…' : isDefault ? '화면 설정이 모두 기본값입니다' : '화면 설정 모두 기본값으로'}
            </button>
          </section>

          {/* ── 안전 ── */}
          <section className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
              <ShieldCheck className="w-4 h-4 text-cyan-400" />
              안전
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={rpEnabled === true}
              disabled={rpEnabled === null || rpSaving}
              onClick={toggleRestorePoint}
              className="w-full flex items-center justify-between gap-3 rounded-lg border border-black/10 dark:border-slate-700 px-3 py-2.5 text-left hover:border-slate-500 transition-colors disabled:cursor-wait"
            >
              <span>
                <span className="block text-xs font-semibold text-gray-700 dark:text-slate-300">바꾸기 전에 Windows 복원 지점 만들기</span>
                <span className="block text-[0.6875rem] text-gray-500 dark:text-slate-400">
                  성능 모드·기본 앱 정리·맞춤 튜닝 전에 만듭니다. Windows 는 24시간에 한 번만 만들고, 시스템 보호가 꺼져 있으면 만들 수 없습니다(그때도 결과를 알려 드립니다).
                  {rpEnabled === null && ' 설정을 읽지 못했습니다.'}
                </span>
              </span>
              <span className={`relative w-10 h-6 rounded-full flex-shrink-0 transition-colors ${rpEnabled ? 'bg-cyan-500' : 'bg-gray-300 dark:bg-slate-700'}`}>
                <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${rpEnabled ? 'left-5' : 'left-1'}`} />
              </span>
            </button>
          </section>

          {/* ── 초기 설정 마법사 ── 첫 실행 때만 뜨므로 사양별 설정을 다시 보려면 여기서 연다 */}
          {onOpenSetupWizard && (
            <section className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-bold text-gray-900 dark:text-slate-100">
                <Wand2 className="w-4 h-4 text-cyan-400" />
                초기 설정 마법사
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400">
                PC 사양에 맞는 서비스 설정을 다시 확인합니다. 여는 것만으로는 아무것도 바뀌지 않습니다.
              </p>
              <button
                type="button"
                onClick={onOpenSetupWizard}
                className="px-4 py-2 rounded-lg font-bold text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 transition-colors"
              >
                마법사 다시 열기
              </button>
            </section>
          )}

          <button
            onClick={onClose}
            className="w-full px-4 py-2.5 rounded-lg font-bold text-sm bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-slate-100 transition-colors"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
