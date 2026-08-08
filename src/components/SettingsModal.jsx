import React, { useState, useEffect } from 'react';
import { Settings, X, Key, Save } from 'lucide-react';

export default function SettingsModal({ isOpen, onClose, addToast }) {
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    // 향후 설정 저장 로직 위치
    setTimeout(() => {
      if (addToast) addToast("설정이 저장되었습니다.", "success");
      onClose();
      setIsSaving(false);
    }, 500);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[90%] max-w-md border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-gray-100 dark:border-slate-800 flex justify-between items-center bg-gray-50 dark:bg-slate-800/30">
          <div className="flex items-center gap-2 text-gray-800 dark:text-gray-200">
            <Settings className="w-5 h-5" />
            <h2 className="font-bold">환경 설정</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>
        
        <div className="p-6">
          <div className="mb-6 flex flex-col items-center justify-center py-8 text-gray-500">
            <Settings className="w-12 h-12 mb-2 opacity-20" />
            <p>현재 변경할 수 있는 설정 항목이 없습니다.</p>
          </div>
          
          <button 
            onClick={handleSave}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-bold transition-all shadow-md shadow-indigo-500/20"
          >
            {isSaving ? '저장 중...' : (
              <>
                <Save className="w-4 h-4" />
                저장하기
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
