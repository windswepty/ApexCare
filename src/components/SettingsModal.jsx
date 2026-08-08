import React, { useState, useEffect } from 'react';
import { Settings, X, Key, Save } from 'lucide-react';
import { playSound } from '../utils/audio';

export default function SettingsModal({ isOpen, onClose, addToast }) {
  const [apiKey, setApiKey] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (isOpen) {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getAiApiKey === 'function') {
        window.pywebview.api.getAiApiKey().then(key => {
          if (key) setApiKey(key);
        }).catch(e => console.error(e));
      }
    }
  }, [isOpen]);

  const handleSave = async () => {
    playSound('click');
    setIsSaving(true);
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.setAiApiKey === 'function') {
      try {
        await window.pywebview.api.setAiApiKey(apiKey);
        if (addToast) addToast("설정이 저장되었습니다.", "success");
        onClose();
      } catch (e) {
        if (addToast) addToast("설정 저장에 실패했습니다.", "error");
      }
    } else {
      setTimeout(() => {
        if (addToast) addToast("설정이 저장되었습니다 (모의).", "success");
        onClose();
      }, 500);
    }
    setIsSaving(false);
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
          <div className="mb-6">
            <label className="flex items-center gap-2 text-sm font-bold text-gray-700 dark:text-gray-300 mb-2">
              <Key className="w-4 h-4 text-indigo-500" />
              Gemini API Key
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              AI 문제 해결사(AI Problem Solver) 기능을 사용하기 위해 필요한 키입니다. 키는 로컬 환경에만 안전하게 저장됩니다.
            </p>
            <input 
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full bg-gray-50 dark:bg-slate-950 border border-gray-300 dark:border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white transition-all"
            />
          </div>
          
          <button 
            onClick={handleSave}
            disabled={isSaving}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg font-bold transition-all shadow-md shadow-indigo-500/20"
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
