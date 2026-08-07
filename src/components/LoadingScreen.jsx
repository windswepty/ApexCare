import React, { useState, useEffect } from 'react';

export default function LoadingScreen({ isAppReady, onComplete, isDarkMode }) {
  const [progress, setProgress] = useState(0);
  const [loadingText, setLoadingText] = useState('엔진 가동 준비 중...');

  useEffect(() => {
    const texts = [
      '시스템 환경 분석 중...',
      '백그라운드 통신 엔진 초기화...',
      'UI 렌더링 최적화 중...',
      '하드웨어 상태 스캔 중...'
    ];

    let currentProgress = 0;
    const interval = setInterval(() => {
      if (currentProgress < 90) {
        currentProgress += Math.random() * 12;
        if (currentProgress > 90) currentProgress = 90;
        setProgress(currentProgress);
        
        const textIndex = Math.min(Math.floor(currentProgress / 25), texts.length - 1);
        setLoadingText(texts[textIndex]);
      }
    }, 200);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (isAppReady) {
      setProgress(100);
      setLoadingText('모든 준비 완료!');
      const tm = setTimeout(() => {
        onComplete();
      }, 600);
      return () => clearTimeout(tm);
    }
  }, [isAppReady, onComplete]);

  return (
    <div className={`fixed inset-0 z-50 flex flex-col items-center justify-center ${isDarkMode ? 'bg-[#09090b] text-black dark:text-white' : 'bg-white text-black'}`}>
      <div className="w-64 flex flex-col items-center">
        <img 
          src="/icon.png" 
          alt="APEX CARE" 
          className={`w-16 h-16 mb-8 image-reveal-animation ${isDarkMode ? 'invert' : ''}`} 
        />
        <h2 className="text-2xl font-black tracking-tight mb-6 flex items-center gap-2">
          APEX <span className="text-gray-500">CARE</span>
        </h2>
        
        <div className="w-full h-2 bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 rounded-full overflow-hidden mb-3">
          <div 
            className="h-full bg-black dark:bg-white transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          ></div>
        </div>
        
        <div className="flex justify-between w-full px-1">
          <p className="text-[11px] font-mono text-gray-500 dark:text-gray-400">
            {loadingText}
          </p>
          <p className="text-[11px] font-mono font-bold text-black dark:text-white">
            {Math.round(progress)}%
          </p>
        </div>
      </div>
    </div>
  );
}
