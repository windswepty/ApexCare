import React from 'react';
import { AlertTriangle } from 'lucide-react';

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

  render() {
    if (this.state.hasError) {
      // 예전에는 'F12 로 개발자 도구를 열어 보라' 고 안내했다. 설치된 앱에서는 개발자 도구가 꺼져 있어 할 수 없는 일이다.
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-white dark:bg-slate-950 text-black dark:text-white p-6 relative">
          <AlertTriangle className="w-16 h-16 text-red-500 mb-4" />
          <h1 className="text-2xl font-bold mb-2">화면을 표시하는 중 오류가 발생했습니다</h1>
          <p className="text-gray-600 dark:text-slate-400 mb-6 text-center">
            진행 중이던 작업과 시스템 설정은 이 오류와 관계없이 그대로입니다.<br />
            '다시 불러오기' 를 누르거나 앱을 닫았다가 다시 실행해 주세요. 문제가 계속되면 아래 오류 내용을 함께 알려 주세요.
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
              다시 불러오기
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
