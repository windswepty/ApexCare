import React from 'react';
import { AlertTriangle } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({
      error: error,
      errorInfo: errorInfo
    });
    console.error("ErrorBoundary caught an error:", error, errorInfo);
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      const errorLog = `${this.state.error && this.state.error.toString()}\n${this.state.errorInfo && this.state.errorInfo.componentStack}`;
      
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-white dark:bg-slate-950 text-black dark:text-white p-6 relative">
          <AlertTriangle className="w-16 h-16 text-red-500 mb-4 animate-pulse" />
          <h1 className="text-2xl font-bold mb-2">렌더링 중 치명적인 에러가 발생했습니다</h1>
          <p className="text-gray-600 dark:text-slate-400 mb-6 text-center">
            UI를 표시하는 도중 예기치 않은 오류가 발생했습니다.<br/>
            F12 키 또는 Ctrl+Shift+I 키를 눌러 개발자 도구를 열고 콘솔(Console) 탭을 확인해 주세요.
          </p>
          <div className="bg-gray-100 dark:bg-slate-900 p-4 rounded text-left w-full max-w-2xl overflow-auto text-sm font-mono border border-gray-300 dark:border-slate-800">
            <div className="text-red-500 font-bold mb-2">{this.state.error && this.state.error.toString()}</div>
            <div className="text-gray-500 whitespace-pre-wrap">{this.state.errorInfo && this.state.errorInfo.componentStack}</div>
          </div>
          
          <div className="flex gap-4 mt-6">
            <button 
              onClick={() => window.location.reload()} 
              className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black rounded font-bold transition-colors shadow-lg"
            >
              앱 새로고침
            </button>
          </div>
        </div>
      );
    }

    return this.props.children; 
  }
}
