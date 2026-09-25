import React, { useState } from 'react';
import { Settings, X, Check, Palette } from 'lucide-react';
import { THEMES, applyTheme, swatch } from '../theme';

// 예전 '저장하기' 버튼은 아무것도 저장하지 않고 "설정이 저장되었습니다" 를 띄웠다.
// 이제 색 조합을 고르면 바로 적용하고, 백엔드가 저장에 성공했을 때만 성공을 알린다.
export default function SettingsModal({ isOpen, onClose, addToast, themeId, onThemeChange }) {
  const [savingId, setSavingId] = useState(null);

  const chooseTheme = async (id) => {
    if (savingId || id === themeId) return;
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.setUiTheme !== 'function') {
      if (addToast) addToast('API가 준비되지 않아 색 조합을 저장할 수 없습니다.', 'error');
      return;
    }

    const previous = themeId;
    applyTheme(id);           // 바로 보여준다
    onThemeChange(id);
    setSavingId(id);
    try {
      const res = await api.setUiTheme(id);
      if (!res?.success) throw new Error(res?.message || '저장 실패');
      if (addToast) addToast('색 조합을 저장했습니다.', 'success');
    } catch (e) {
      // 저장하지 못했으면 화면도 이전 색으로 되돌린다. 다음 실행 때 보일 색과 어긋나지 않게.
      applyTheme(previous);
      onThemeChange(previous);
      if (addToast) addToast(`색 조합을 저장하지 못했습니다: ${e.message || e}`, 'error');
    } finally {
      setSavingId(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[90%] max-w-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-gray-100 dark:border-slate-800 flex justify-between items-center bg-gray-50 dark:bg-slate-800/30">
          <div className="flex items-center gap-2 text-gray-800 dark:text-gray-200">
            <Settings className="w-5 h-5" />
            <h2 className="font-bold">환경 설정</h2>
          </div>
          <button onClick={onClose} aria-label="닫기" className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        <div className="p-6 space-y-4">
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
                  disabled={savingId !== null}
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
                    {savingId === theme.id ? '저장 중…' : theme.description}
                  </span>
                </button>
              );
            })}
          </div>

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
