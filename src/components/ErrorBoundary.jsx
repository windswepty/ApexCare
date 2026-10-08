import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { tr } from '../i18n';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ error, errorInfo });
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  closeApp = async () => {
    // 창 테두리가 없어(frameless) 이 화면에서는 창을 닫을 방법이 없었다. 진행 중인 작업이 있으면 알리고 묻는다.
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.closeWindow !== 'function') return;
    try {
      const r = await api.closeWindow();
      if (r && r.busy && window.confirm(tr("{0}\n\n그래도 닫을까요?", [r.message]))) await api.closeWindow(true);
    } catch (e) {
      console.error('창을 닫지 못했습니다:', e);
    }
  };

  render() {
    if (this.state.hasError && this.props.compact) {
      // 탭 하나의 오류. 사이드바·다른 탭(특히 '변경 내역 · 되돌리기')은 그대로 쓸 수 있게 이 자리에만 보여 준다.
      // 예전에는 한 탭이 오류를 내면 앱 전체가 오류 화면으로 바뀌어 되돌리기 화면에도 갈 수 없었다.
      return (
        <div className="glass-panel p-6 flex flex-col items-center text-center gap-3">
          <AlertTriangle className="w-10 h-10 text-red-500" />
          <h2 className="text-lg font-bold text-black dark:text-white">{tr("이 화면을 표시하는 중 오류가 발생했습니다")}</h2>
          <p className="text-sm text-gray-600 dark:text-slate-400">
            {tr("진행 중이던 작업과 시스템 설정은 그대로입니다. 다른 탭은 계속 쓸 수 있습니다. 문제가 계속되면 아래 오류 내용을 함께 알려 주세요.")}
          </p>
          <div className="w-full max-w-2xl text-left bg-gray-100 dark:bg-slate-900 p-3 rounded-lg text-xs font-mono border border-gray-300 dark:border-slate-800 select-text overflow-auto max-h-40">
            <div className="text-red-500 font-bold">{this.state.error && this.state.error.toString()}</div>
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null, errorInfo: null })}
            className="px-5 py-2.5 bg-cyan-500 hover:bg-cyan-400 text-black rounded-lg font-bold text-sm transition-colors"
          >
            {tr("이 화면 다시 열기")}
          </button>
        </div>
      );
    }
    if (this.state.hasError) {
      // 예전에는 'F12 로 개발자 도구를 열어 보라' 고 안내했다. 설치된 앱에서는 개발자 도구가 꺼져 있어 할 수 없는 일이다.
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-white dark:bg-slate-950 text-black dark:text-white p-6 relative">
          {/* 창을 옮길 수 있게 맨 위에 끌기 영역을 둔다 */}
          <div className="pywebview-drag-region absolute top-0 left-0 right-0 h-9" style={{ WebkitAppRegion: 'drag' }} />
          <AlertTriangle className="w-16 h-16 text-red-500 mb-4" />
          <h1 className="text-2xl font-bold mb-2">{tr("화면을 표시하는 중 오류가 발생했습니다")}</h1>
          <p className="text-gray-600 dark:text-slate-400 mb-6 text-center">
            {tr("진행 중이던 작업과 시스템 설정은 이 오류와 관계없이 그대로입니다.")}<br />
            {tr("'다시 불러오기' 를 누르거나 앱을 닫았다가 다시 실행해 주세요. 문제가 계속되면 아래 오류 내용을 함께 알려 주세요.")}
          </p>
          <div className="bg-gray-100 dark:bg-slate-900 p-4 rounded text-left w-full max-w-2xl overflow-auto max-h-64 text-sm font-mono border border-gray-300 dark:border-slate-800 select-text">
            <div className="text-red-500 font-bold mb-2">{this.state.error && this.state.error.toString()}</div>
            <div className="text-gray-500 whitespace-pre-wrap">{this.state.errorInfo && this.state.errorInfo.componentStack}</div>
          </div>

          <div className="flex gap-4 mt-6">
            <button
              onClick={() => window.location.reload()}
              className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black rounded font-bold transition-colors shadow-lg"
            >
              {tr("다시 불러오기")}
            </button>
            <button
              onClick={this.closeApp}
              className="px-6 py-3 border border-gray-300 dark:border-slate-700 hover:border-red-500 rounded font-bold transition-colors"
            >
              {tr("앱 닫기")}
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
