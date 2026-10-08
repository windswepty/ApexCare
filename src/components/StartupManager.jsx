import { useState, useEffect, useRef } from 'react';
import {
  Rocket,
  Power
} from 'lucide-react';
import { tr } from '../i18n';

// 백엔드 get_startup_apps() 의 location 값 → 화면 표시 (백엔드가 locationLabel 을 주면 그것을 쓴다)
const LOCATION_LABEL = {
  HKCU: tr('현재 사용자'),
  HKLM: tr('모든 사용자'),
  HKLM32: tr('모든 사용자 (32비트)'),
  FOLDER: tr('시작프로그램 폴더 (현재 사용자)'),
  FOLDER_ALL: tr('시작프로그램 폴더 (모든 사용자)'),
  LEGACY: tr('예전 버전에서 끔'),
};

export default function StartupManager({ addToast, active = true }) {
  const [startupApps, setStartupApps] = useState([]);
  // 'loading' → 'ok' | 'error'. 읽기 전에는 '0개' 라고 말하지 않는다(예전에는 읽기 전에도 0개로 보였다).
  const [loadState, setLoadState] = useState('loading');
  // 요청 중인 항목. 결과를 받기 전에는 스위치를 바꾸지 않는다.
  const [pendingId, setPendingId] = useState(null);

  const reload = async () => {
    try {
      const apps = await window.pywebview.api.getStartupApps();
      if (Array.isArray(apps)) setStartupApps(apps);
    } catch (e) {
      console.error('Error reloading startup apps:', e);
    }
  };

  useEffect(() => {
    const fetchStartup = async () => {
      try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getStartupApps === 'function') {
          const apps = await window.pywebview.api.getStartupApps();
          if (apps && Array.isArray(apps)) {
            setStartupApps(apps);
            setLoadState('ok');
          } else {
            setStartupApps([]);
            setLoadState('error');
          }
        }
      } catch (e) {
        console.error('Error fetching startup apps:', e);
        setStartupApps([]);
        setLoadState('error');
      }
    };

    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getStartupApps === 'function') {
      fetchStartup();
    } else {
      window.addEventListener('pywebviewready', fetchStartup);
      return () => window.removeEventListener('pywebviewready', fetchStartup);
    }
  }, []);

  // 탭을 다시 열면 다시 읽는다. '변경 내역 · 되돌리기' 의 전부 원래대로가 켜고 끈 상태를 바꿨을 수 있다.
  // 예전에는 처음 열 때만 읽어, 되돌린 뒤에도 '꺼짐' 으로 보였다. 요청 중인 항목이 있으면 그 결과를 기다린다.
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current && pendingId === null && loadState === 'ok') reload();
    wasActive.current = active;
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleApp = async (id, appName) => {
    const app = startupApps.find(a => a.id === id);
    if (!app || pendingId !== null) return;
    const newEnabled = !app.enabled;

    if (!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.toggleStartupApp === 'function')) {
      if (addToast) addToast(tr("API가 준비되지 않았습니다."), "error");
      return;
    }

    setPendingId(id);
    try {
      // 이름이 아니라 id(위치:이름)로 부른다. 같은 이름이 여러 위치에 있어도 정확히 하나만 바뀐다.
      const res = await window.pywebview.api.toggleStartupApp(id, newEnabled);
      if (res?.success) {
        // 결과는 레지스트리에서 다시 읽는다(예전 버전에서 끈 항목은 켜면 원래 위치로 옮겨 간다)
        await reload();
        if (addToast) addToast(res.message || tr("[{0}] 시작 프로그램 상태가 변경되었습니다.", [appName]), 'success');
      } else {
        if (addToast) addToast(res?.message || tr("시작 프로그램({0}) 상태 변경에 실패했습니다.", [appName]), 'error');
      }
    } catch (e) {
      console.error('Error toggling startup app:', e);
      if (addToast) addToast(tr("시작 프로그램({0}) 상태 변경에 실패했습니다.", [appName]), 'error');
    } finally {
      setPendingId(null);
    }
  };

  const enabledCount = startupApps.filter(a => a.enabled).length;
  const disabledCount = startupApps.length - enabledCount;
  const countText = (n) => (loadState === 'loading' ? '…' : loadState === 'error' ? '-' : tr("{0}개", [n]));

  return (
    <div className="space-y-6">
      {/* Header Overview Card */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold mb-1">
            <Rocket className="w-4 h-4" />
            WINDOWS STARTUP PROGRAMS
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">{tr("시작 프로그램 관리")}</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            {tr("Windows 로그인 시 자동으로 실행되도록 레지스트리(Run 키)와 시작프로그램 폴더에 등록된 프로그램을 켜고 끕니다. 작업 관리자와 같은 방식이라 등록 정보와 바로 가기 파일은 그대로 두고 켜짐/꺼짐만 바꿉니다. 끈 항목도 작업 관리자·Windows 설정에 그대로 보이고, '변경 내역 · 되돌리기' 의 '전부 원래대로' 로도 되돌릴 수 있습니다. 다음 로그인부터 적용됩니다.")}
          </p>
        </div>
      </div>

      {/* Counts — 레지스트리에서 읽은 값만 보여준다 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="glass-panel p-4 text-center">
          <span className="text-xs text-gray-500 dark:text-slate-400">{tr("켜진 시작 프로그램")}</span>
          <div className="text-3xl font-black font-mono text-cyan-400 my-1">{countText(enabledCount)}</div>
        </div>

        <div className="glass-panel p-4 text-center">
          <span className="text-xs text-gray-500 dark:text-slate-400">{tr("꺼진 시작 프로그램")}</span>
          <div className="text-3xl font-black font-mono text-slate-400 my-1">{countText(disabledCount)}</div>
        </div>
      </div>

      {/* Startup Applications List */}
      <div className="glass-panel p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-900 dark:text-slate-100 text-sm">
            {tr("등록된 시작 프로그램 목록")}{loadState === 'ok' ? ` (${startupApps.length})` : ''}
          </h3>
          <span className="text-xs text-gray-500 dark:text-slate-400">{tr("이름 순")}</span>
        </div>
        <p className="text-[0.6875rem] text-gray-500 dark:text-slate-400">
          {tr("각 프로그램이 부팅 시간에 주는 영향은 측정하지 않으므로 표시하지 않습니다. 작업 스케줄러·서비스로 시작되는 프로그램은 이 목록에 나오지 않습니다.")}
        </p>

        <div className="space-y-2">
          {loadState === 'loading' && (
            <p className="text-sm text-gray-500 py-6 text-center">{tr("시작 프로그램 목록을 읽는 중…")}</p>
          )}
          {loadState === 'error' && (
            <p className="text-sm text-rose-400 py-6 text-center">{tr("시작 프로그램 목록을 읽지 못했습니다.")}</p>
          )}
          {loadState === 'ok' && startupApps.length === 0 && (
            <p className="text-sm text-gray-500 py-6 text-center">{tr("등록된 시작 프로그램이 없습니다.")}</p>
          )}
          {startupApps.map((app) => (
            <div
              key={app.id}
              className={`p-4 rounded-xl border transition-all duration-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 ${
                app.enabled
                  ? 'bg-white dark:bg-slate-900/60 border-black/10 dark:border-slate-800'
                  : 'bg-gray-100 dark:bg-slate-950/40 border-black/10 dark:border-slate-900 opacity-60'
              }`}
            >
              <div className="flex items-center gap-3.5 min-w-0 flex-1">
                <div className={`p-2.5 rounded-lg flex-shrink-0 font-mono text-xs ${
                  app.enabled ? 'bg-cyan-500/10 text-cyan-400' : 'bg-gray-50 dark:bg-slate-800 text-slate-500'
                }`}>
                  <Power className="w-4 h-4" />
                </div>

                <div className="min-w-0 flex-1 pr-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900 dark:text-slate-100 text-sm truncate">{app.name}</span>
                    {(app.locationLabel || LOCATION_LABEL[app.location]) && (
                      <span className="text-[0.625rem] font-mono flex-shrink-0 px-1.5 py-0.5 rounded bg-black/5 dark:bg-slate-800 text-gray-600 dark:text-slate-400">
                        {app.locationLabel || LOCATION_LABEL[app.location]}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 truncate w-full font-mono" title={app.command}>
                    {app.command}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4 self-end sm:self-center">
                {/* Enable/Disable Toggle — 결과를 받은 뒤에만 바뀐다 */}
                <button
                  type="button"
                  role="switch"
                  aria-checked={app.enabled}
                  aria-label={tr("{0} 시작 프로그램 {1}", [app.name, app.enabled ? tr('끄기') : tr('켜기')])}
                  disabled={pendingId !== null}
                  onClick={() => toggleApp(app.id, app.name)}
                  className={`toggle-switch ${app.enabled ? 'active' : ''} ${pendingId === app.id ? 'opacity-50 cursor-wait' : ''} disabled:cursor-not-allowed`}
                >
                  <div className="toggle-thumb"></div>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
