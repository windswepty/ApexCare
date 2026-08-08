import React, { useState, useEffect } from 'react';
import { Sparkles, X, Loader2 } from 'lucide-react';

// 간단한 마크다운 파서 (볼드, 줄바꿈)
const parseMarkdown = (text) => {
  if (!text) return null;
  // \n\n -> p tag 분리
  const paragraphs = text.split('\n\n');
  return paragraphs.map((para, i) => {
    // \n -> br
    const lines = para.split('\n');
    return (
      <p key={i} className="mb-4 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
        {lines.map((line, j) => {
          // **text** -> bold
          const boldParts = line.split(/\*\*(.*?)\*\*/g);
          return (
            <React.Fragment key={j}>
              {boldParts.map((part, k) => (
                k % 2 === 1 ? <strong key={k} className="text-gray-900 dark:text-white font-bold">{part}</strong> : part
              ))}
              {j < lines.length - 1 && <br />}
            </React.Fragment>
          );
        })}
      </p>
    );
  });
};

export default function AIProblemSolverModal({ isOpen, onClose, errorLog, systemState, userMessage = "" }) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [apiKeyMissing, setApiKeyMissing] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    
    const fetchAiAnalysis = async () => {
      setLoading(true);
      setResult(null);
      setApiKeyMissing(false);
      
      try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.askAiSolver === 'function') {
          const res = await window.pywebview.api.askAiSolver(errorLog, systemState, userMessage);
          if (res.success) {
            setResult(res.answer);
          } else {
            if (res.error && res.error.includes("API 키가 설정되지")) {
              setApiKeyMissing(true);
            }
            setResult(`**[분석 실패]**\n${res.error}`);
          }
        } else {
          // Fallback for dev mode
          setTimeout(() => {
            setResult("**[모의 분석 결과]**\n\n**에러 원인:**\n현재 시스템 리소스가 부족하여 작업이 취소되었습니다. 윈도우 캐시 메모리가 가득 차 발생한 현상으로 보입니다.\n\n**해결 방법:**\n1. `APEX CARE`의 **RAM 부스터** 기능으로 대기 캐시를 먼저 비워주세요.\n2. 그런 다음 작업을 재시도하십시오.");
            setLoading(false);
          }, 2000);
          return;
        }
      } catch (e) {
        setResult(`**[시스템 에러]**\nAI 분석 중 치명적인 에러가 발생했습니다: ${String(e)}`);
      }
      setLoading(false);
    };

    fetchAiAnalysis();
  }, [isOpen, errorLog, systemState, userMessage]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[90%] max-w-2xl overflow-hidden border border-gray-200 dark:border-slate-700 flex flex-col max-h-[85vh]">
        <div className="p-4 border-b border-gray-100 dark:border-slate-800 flex justify-between items-center bg-gradient-to-r from-blue-50/50 to-purple-50/50 dark:from-blue-900/10 dark:to-purple-900/10">
          <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400">
            <Sparkles className="w-5 h-5" />
            <h2 className="font-bold text-lg">AI 문제 해결사</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors">
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>
        
        <div className="p-6 overflow-y-auto flex-1 custom-scrollbar">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500 dark:text-slate-400">
              <Loader2 className="w-12 h-12 mb-4 animate-spin text-indigo-500" />
              <p className="text-lg font-medium text-gray-800 dark:text-slate-200">AI가 시스템 로그를 분석 중입니다...</p>
              <p className="text-sm mt-2 text-center max-w-sm">"수만 건의 최적화 데이터를 바탕으로<br/>가장 정확한 해결책을 찾고 있습니다."</p>
            </div>
          ) : (
            <div className="animate-in slide-in-from-bottom-4 duration-300">
              <div className="bg-gray-50 dark:bg-slate-800/50 p-4 rounded-lg mb-4 text-xs font-mono text-gray-500 overflow-hidden text-ellipsis whitespace-nowrap">
                <strong>분석 대상:</strong> {errorLog.substring(0, 100)}...
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                {parseMarkdown(result)}
              </div>
              
              {apiKeyMissing && (
                <div className="mt-6 p-4 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-700/50 rounded-lg">
                  <p className="text-sm text-yellow-800 dark:text-yellow-200">
                    <strong>API 키가 필요합니다!</strong> 우측 상단의 톱니바퀴 아이콘(설정)을 클릭하여 OpenAI API 키를 입력해 주세요.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
        
        <div className="p-4 border-t border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/30 flex justify-end">
          <button 
            onClick={onClose}
            className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors shadow-sm shadow-indigo-500/20"
          >
            확인 및 닫기
          </button>
        </div>
      </div>
    </div>
  );
}
