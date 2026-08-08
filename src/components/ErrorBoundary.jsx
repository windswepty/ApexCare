import React from 'react';
import { AlertTriangle, Sparkles } from 'lucide-react';
import AIProblemSolverModal from './AIProblemSolverModal';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null, isAiModalOpen: false, systemState: "" };
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
    
    // Attempt to grab minimal system state if available
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getSystemStats === 'function') {
      window.pywebview.api.getSystemStats().then(stats => {
        if (stats) {
          this.setState({ systemState: JSON.stringify(stats, null, 2) });
        }
      }).catch(e => console.error(e));
    }
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
              onClick={() => this.setState({ isAiModalOpen: true })} 
              className="px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded font-bold transition-all shadow-lg flex items-center gap-2"
            >
              <Sparkles className="w-5 h-5" />
              AI에게 원인 및 해결 방법 묻기
            </button>
            
            <button 
              onClick={() => window.location.reload()} 
              className="px-6 py-3 bg-cyan-500 hover:bg-cyan-600 text-white rounded font-bold transition-colors shadow-lg"
            >
              앱 새로고침
            </button>
          </div>

          <AIProblemSolverModal 
            isOpen={this.state.isAiModalOpen}
            onClose={() => this.setState({ isAiModalOpen: false })}
            errorLog={errorLog}
            systemState={this.state.systemState || "System state not available."}
            userMessage="앱 실행 도중 이 오류가 발생해서 화면이 하얗게 변했습니다. 어떻게 조치해야 하는지 알려주세요."
          />
        </div>
      );
    }

    return this.props.children; 
  }
}
