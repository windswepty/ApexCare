import React from 'react';
import { Minus, Square, X, Sparkles } from 'lucide-react';
import { playSound } from '../utils/audio';

export default function TitleBar() {
  const handleMinimize = () => {
    playSound('click');
    if (window.pywebview?.api) window.pywebview?.api.minimizeWindow();
  };

  const handleMaximize = () => {
    playSound('click');
    if (window.pywebview?.api) window.pywebview?.api.maximizeWindow();
  };

  const handleClose = () => {
    playSound('click');
    if (window.pywebview?.api) window.pywebview?.api.closeWindow();
  };

  return (
    <header className="pywebview-drag-region h-9 bg-white dark:bg-black border-b border-black/10 dark:border-white/10 flex items-center justify-between px-3 select-none z-50 sticky top-0 w-full" style={{ WebkitAppRegion: 'drag' }}>
      {/* App Branding title */}
      <div className="flex items-center gap-2 text-xs font-bold text-black dark:text-white transition-colors duration-300">
        <img src="/icon.png" alt="logo" className="w-4 h-4 rounded-sm dark:invert" />
        <span className="tracking-wide">APEX CARE - Desktop PC Optimizer</span>
        <span className="text-[10px] font-mono text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 px-1.5 py-0.2 rounded transition-colors duration-300">
          NATIVE GUI
        </span>
      </div>

      {/* Window Controls */}
      <div className="flex items-center" style={{ WebkitAppRegion: 'no-drag' }}>
        <button
          onClick={handleMinimize}
          className="w-10 h-9 hover:bg-black/5 dark:hover:bg-white/10 text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-black dark:text-white flex items-center justify-center transition-colors duration-300"
          title="최소화"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={handleMaximize}
          className="w-10 h-9 hover:bg-black/5 dark:hover:bg-white/10 text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-black dark:text-white flex items-center justify-center transition-colors duration-300"
          title="최대화 / 이전 크기"
        >
          <Square className="w-3 h-3" />
        </button>
        <button
          onClick={handleClose}
          className="w-10 h-9 hover:bg-rose-500 hover:text-black dark:text-white text-gray-500 dark:text-gray-400 flex items-center justify-center transition-colors duration-300"
          title="닫기"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
