import { Minus, Square, X, Settings } from 'lucide-react';
import AppLogo from './AppLogo';

export default function TitleBar({ onOpenSettings }) {
  const handleMinimize = () => {
    if (window.pywebview?.api) window.pywebview?.api.minimizeWindow();
  };

  const handleMaximize = () => {
    if (window.pywebview?.api) window.pywebview?.api.maximizeWindow();
  };

  /**
   * 창 닫기.
   *
   * 백엔드가 진행 중인 작업을 확인해 busy 를 돌려준다. 예전에는 즉시
   * os._exit(0) 으로 프로세스를 죽여서, 파일을 지우는 중이거나 시스템 변경
   * 기록을 디스크에 쓰기 직전이었다면 그대로 끊겼다.
   */
  const handleClose = async () => {
    const api = window.pywebview?.api;
    if (!api?.closeWindow) return;
    try {
      const res = await api.closeWindow();
      if (res?.busy) {
        const ok = window.confirm(
          `${res.reason} 작업이 진행 중입니다.\n\n` +
          '지금 종료하면 작업이 중간에 끊기고, 되돌리기 정보가 저장되지 않을 수 있습니다.\n\n' +
          '그래도 종료할까요?'
        );
        if (ok) await api.closeWindow(true);
      }
    } catch (e) {
      console.error('종료 실패:', e);
    }
  };

  return (
    <header className="pywebview-drag-region h-9 bg-white dark:bg-black border-b border-black/10 dark:border-white/10 flex items-center justify-between px-3 select-none z-50 sticky top-0 w-full" style={{ WebkitAppRegion: 'drag' }}>
      {/* App Branding title */}
      <div className="flex items-center gap-2 text-xs font-bold text-black dark:text-white transition-colors duration-300">
        <AppLogo className="w-4 h-4" />
        <span className="tracking-wide">APEX CARE - Desktop PC Optimizer</span>
      </div>

      {/* Window Controls */}
      <div className="flex items-center" style={{ WebkitAppRegion: 'no-drag' }}>
        <button
          onClick={onOpenSettings}
          className="w-10 h-9 hover:bg-black/5 dark:hover:bg-white/10 text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-white flex items-center justify-center transition-colors duration-300"
          title="환경 설정"
          aria-label="환경 설정"
        >
          <Settings className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={handleMinimize}
          className="w-10 h-9 hover:bg-black/5 dark:hover:bg-white/10 text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-white flex items-center justify-center transition-colors duration-300"
          title="최소화"
          aria-label="최소화"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={handleMaximize}
          className="w-10 h-9 hover:bg-black/5 dark:hover:bg-white/10 text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-white flex items-center justify-center transition-colors duration-300"
          title="최대화 / 이전 크기"
          aria-label="최대화 / 이전 크기"
        >
          <Square className="w-3 h-3" />
        </button>
        <button
          onClick={handleClose}
          className="w-10 h-9 hover:bg-rose-500 text-gray-500 dark:text-gray-400 hover:text-white dark:hover:text-white flex items-center justify-center transition-colors duration-300"
          title="닫기"
          aria-label="닫기"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
