import React, { useState, useEffect, useRef } from 'react';
import { Settings, X, Check, Palette, Pipette, AlertTriangle, Wand2, RotateCcw } from 'lucide-react';
import {
  THEMES, HEX_RE, applyTheme, swatch, findTheme, composeTheme,
  accentProblems, readableAccent, resemblesWarningColor,
} from '../theme';

// 키보드로 갈 수 있는 것(Tab 이 창 안에서만 돌게 할 때 쓴다)
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

// 예전 '저장하기' 버튼은 아무것도 저장하지 않고 "설정이 저장되었습니다" 를 띄웠다.
// 이제 고르면 바로 적용하고, 백엔드가 저장에 성공했을 때만 성공을 알린다.
// 저장에 실패하면 화면도 이전 색으로 되돌린다. 다음 실행 때 보일 색과 어긋나지 않게.
export default function SettingsModal({ isOpen, onClose, addToast, themeId, accent, onAppearanceChange, onOpenSetupWizard }) {
  const [saving, setSaving] = useState(null);   // 'theme:<id>' | 'accent'
  const [draft, setDraft] = useState('');       // 편집 중인 강조색
  const [hexText, setHexText] = useState('');   // 직접 입력 칸

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

  // 창을 열 때 현재 강조색으로 초기화한다
  useEffect(() => {
    if (!isOpen) return;
    const current = accent || findTheme(themeId).accent[5];
    setDraft(current);
    setHexText(current);
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const api = window.pywebview && window.pywebview.api;

  // 적용 → 저장 → 실패 시 되돌림. next/prev: { id, accent }
  const commit = async (key, next, prev, save, okMessage) => {
    if (!api || typeof save !== 'function') {
      if (addToast) addToast('API가 준비되지 않아 색 설정을 저장할 수 없습니다.', 'error');
      return;
    }
    applyTheme(next.id, next.accent);
    onAppearanceChange(next);
    setSaving(key);
    try {
      const res = await save();
      if (!res?.success) throw new Error(res?.message || '저장 실패');
      if (addToast) addToast(okMessage, 'success');
    } catch (e) {
      applyTheme(prev.id, prev.accent);
      onAppearanceChange(prev);
      if (addToast) addToast(`색 설정을 저장하지 못했습니다: ${e.message || e}`, 'error');
    } finally {
      setSaving(null);
    }
  };

  const chooseTheme = (id) => {
    if (saving || id === themeId) return;
    commit(`theme:${id}`, { id, accent }, { id: themeId, accent },
      api && (() => api.setUiTheme(id)), '색 조합을 저장했습니다.');
  };

  const saveAccent = (value) => {
    if (saving) return;
    commit('accent', { id: themeId, accent: value }, { id: themeId, accent },
      api && (() => api.setUiAccent(value || '')),
      value ? '강조색을 저장했습니다.' : '색 조합의 기본 강조색으로 되돌렸습니다.');
  };

  if (!isOpen) return null;

  const draftValid = HEX_RE.test(draft);
  const problems = draftValid ? accentProblems(themeId, draft) : [];
  const preview = composeTheme(themeId, draftValid ? draft : null);
  const fixed = draftValid && problems.length ? readableAccent(themeId, draft) : null;
  // 저장된 강조색이 지금 색 조합에서는 읽기 어려워 쓰이지 않는 경우
  const savedButUnused = accent && accentProblems(themeId, accent).length > 0;
  const isStored = draftValid && accent === draft.toLowerCase();
  // '적용됨' 은 지금 화면에 실제로 쓰이고 있을 때만. 저장은 됐지만 이 색 조합에서는 쓰이지 않으면 그렇게 말한다.
  const isSaved = isStored && problems.length === 0;

  const setBoth = (hex) => { setDraft(hex); setHexText(hex); };

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
                고르면 바로 적용되고 다음 실행 때도 유지됩니다. 경고·위험을 알리는 빨강·주황은 색 조합과 관계없이 그대로입니다.
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
                    <span className="text-[10px] text-gray-500 dark:text-slate-400">
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
                <ul className="text-[11px] text-gray-600 dark:text-slate-300 space-y-0.5 font-mono">
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
