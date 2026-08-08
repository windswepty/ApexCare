import React, { useState } from 'react';
import { Search, HardDrive, Files, Trash2, CheckSquare, Square, Loader2, AlertTriangle } from 'lucide-react';
import { playSound } from '../utils/audio';

export default function FileFinder({ addToast }) {
  const [activeTab, setActiveTab] = useState('large'); // 'large' or 'duplicates'
  const [loading, setLoading] = useState(false);
  const [largeFiles, setLargeFiles] = useState([]);
  const [duplicates, setDuplicates] = useState([]);
  const [selectedPaths, setSelectedPaths] = useState(new Set());
  const [deleting, setDeleting] = useState(false);

  const handleScanLarge = async () => {
    setLoading(true);
    playSound('click');
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.findLargeFiles === 'function') {
        const data = await window.pywebview.api.findLargeFiles(500);
        setLargeFiles(Array.isArray(data) ? data : []);
        if (addToast) addToast(`대용량 파일 스캔이 완료되었습니다. (${Array.isArray(data) ? data.length : 0}개 발견)`, 'success');
      }
    } catch (e) {
      console.error('Error scanning large files:', e);
      if (addToast) addToast('스캔 중 오류가 발생했습니다.', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleScanDuplicates = async () => {
    setLoading(true);
    playSound('click');
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.findDuplicateFiles === 'function') {
        const data = await window.pywebview.api.findDuplicateFiles();
        setDuplicates(Array.isArray(data) ? data : []);
        if (addToast) addToast(`중복 파일 스캔이 완료되었습니다. (${Array.isArray(data) ? data.length : 0}개 발견)`, 'success');
      }
    } catch (e) {
      console.error('Error scanning duplicates:', e);
      if (addToast) addToast('스캔 중 오류가 발생했습니다.', 'error');
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (path) => {
    const newSet = new Set(selectedPaths);
    if (newSet.has(path)) {
      newSet.delete(path);
    } else {
      newSet.add(path);
    }
    setSelectedPaths(newSet);
  };

  const selectAll = (files) => {
    const newSet = new Set(selectedPaths);
    let allSelected = true;
    files.forEach(f => {
      if (!newSet.has(f.path)) allSelected = false;
    });

    if (allSelected) {
      files.forEach(f => newSet.delete(f.path));
    } else {
      files.forEach(f => newSet.add(f.path));
    }
    setSelectedPaths(newSet);
  };

  // Helper to select duplicates intelligently (keeps one copy of each)
  const selectDuplicatesSmart = () => {
    const newSet = new Set(selectedPaths);
    const groups = {};
    
    // Group duplicates
    duplicates.forEach(d => {
      if (!groups[d.groupId]) groups[d.groupId] = [];
      groups[d.groupId].push(d);
    });

    Object.values(groups).forEach(group => {
      // Keep the first item unselected, select the rest
      for (let i = 1; i < group.length; i++) {
        newSet.add(group[i].path);
      }
    });
    setSelectedPaths(newSet);
  };

  const handleDelete = async () => {
    if (selectedPaths.size === 0 || !window.pywebview?.api) return;
    playSound('click');
    setDeleting(true);
    
    const pathsArray = Array.from(selectedPaths);
    const result = await window.pywebview.api.deleteFiles(pathsArray);
    
    setDeleting(false);
    setSelectedPaths(new Set());
    
    if (result.success) {
      playSound('success');
      if (addToast) addToast(`성공적으로 삭제되었습니다. 확보된 용량: ${result.freedMB}MB`, 'success');
      // Rescan
      if (activeTab === 'large') handleScanLarge();
      else handleScanDuplicates();
    }
  };

  return (
    <div className="h-full flex flex-col glass-panel rounded-2xl p-6 relative overflow-hidden">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-black dark:text-white flex items-center gap-2">
            <Search className="w-6 h-6 text-indigo-400" />
            대용량 및 중복 파일 탐색기
          </h2>
          <p className="text-gray-500 dark:text-slate-400 mt-1">
            디스크 공간을 차지하는 불필요한 큰 파일이나 중복된 파일을 찾아내어 제거합니다.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex bg-white dark:bg-slate-900/50 p-1 rounded-xl mb-6 w-max border border-black/10 dark:border-slate-700/50">
        <button
          onClick={() => { setActiveTab('large'); setSelectedPaths(new Set()); }}
          className={`flex items-center gap-2 px-6 py-2 rounded-lg font-medium transition-all ${
            activeTab === 'large' ? 'bg-indigo-500/20 text-indigo-300' : 'text-gray-500 dark:text-slate-400 hover:text-gray-800 dark:text-slate-200'
          }`}
        >
          <HardDrive className="w-4 h-4" />
          대용량 파일 (500MB+)
        </button>
        <button
          onClick={() => { setActiveTab('duplicates'); setSelectedPaths(new Set()); }}
          className={`flex items-center gap-2 px-6 py-2 rounded-lg font-medium transition-all ${
            activeTab === 'duplicates' ? 'bg-indigo-500/20 text-indigo-300' : 'text-gray-500 dark:text-slate-400 hover:text-gray-800 dark:text-slate-200'
          }`}
        >
          <Files className="w-4 h-4" />
          중복 파일
        </button>
      </div>

      <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-slate-900/30 rounded-xl border border-black/10 dark:border-slate-700/30 p-4">
        
        {/* Action Bar */}
        <div className="flex justify-between items-center mb-4">
          <div className="flex gap-2">
            {activeTab === 'large' ? (
              <button onClick={handleScanLarge} disabled={loading} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-black dark:text-white rounded-lg flex items-center gap-2 text-sm font-medium transition-colors disabled:opacity-50">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                대용량 파일 스캔 시작
              </button>
            ) : (
              <button onClick={handleScanDuplicates} disabled={loading} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-black dark:text-white rounded-lg flex items-center gap-2 text-sm font-medium transition-colors disabled:opacity-50">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                중복 파일 스캔 시작
              </button>
            )}
            
            {activeTab === 'duplicates' && duplicates.length > 0 && (
              <button onClick={selectDuplicatesSmart} className="px-4 py-2 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300 rounded-lg text-sm font-medium transition-colors border border-black/10 dark:border-slate-700">
                스마트 선택 (원본 1개 남기기)
              </button>
            )}
          </div>

          {selectedPaths.size > 0 && (
            <button onClick={handleDelete} disabled={deleting} className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-black dark:text-white rounded-lg flex items-center gap-2 text-sm font-medium transition-colors disabled:opacity-50 shadow-lg shadow-rose-500/20 animate-fade-in">
              {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              선택한 파일 삭제 ({selectedPaths.size}개)
            </button>
          )}
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-slate-400 gap-4">
              <Loader2 className="w-10 h-10 animate-spin text-indigo-500" />
              <p>디스크를 심층 스캔하는 중입니다. 잠시만 기다려주세요...</p>
            </div>
          ) : activeTab === 'large' ? (
            largeFiles.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3 opacity-50">
                <HardDrive className="w-12 h-12" />
                <p>스캔을 시작하거나 대용량 파일이 존재하지 않습니다.</p>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center p-2 px-4 bg-gray-50 dark:bg-slate-800/80 rounded-t-lg text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider">
                  <div className="w-8" onClick={() => selectAll(largeFiles)} style={{cursor: 'pointer'}}>
                    {largeFiles.every(f => selectedPaths.has(f.path)) ? <CheckSquare className="w-4 h-4 text-indigo-400" /> : <Square className="w-4 h-4" />}
                  </div>
                  <div className="flex-1">파일 이름 및 경로</div>
                  <div className="w-24 text-right">크기</div>
                </div>
                {largeFiles.map((file, i) => (
                  <div key={i} className="flex items-center p-3 bg-white dark:bg-slate-900/50 hover:bg-gray-50 dark:bg-slate-800 border-b border-black/10 dark:border-slate-700/30 transition-colors group">
                    <div className="w-8 cursor-pointer" onClick={() => toggleSelect(file.path)}>
                      {selectedPaths.has(file.path) ? <CheckSquare className="w-5 h-5 text-indigo-400" /> : <Square className="w-5 h-5 text-slate-500 group-hover:text-gray-500 dark:text-slate-400" />}
                    </div>
                    <div className="flex-1 min-w-0 pr-4">
                      <div className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate">{file.name}</div>
                      <div className="text-xs font-mono text-slate-500 truncate mt-0.5" title={file.path}>{file.path}</div>
                    </div>
                    <div className="w-24 text-right text-sm font-medium text-rose-400/90 flex-shrink-0">
                      {file.sizeMB} MB
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : (
            duplicates.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3 opacity-50">
                <Files className="w-12 h-12" />
                <p>스캔을 시작하거나 중복 파일이 존재하지 않습니다.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Group by groupId */}
                {Object.entries(
                  duplicates.reduce((acc, curr) => {
                    if (!acc[curr.groupId]) acc[curr.groupId] = [];
                    acc[curr.groupId].push(curr);
                    return acc;
                  }, {})
                ).map(([groupId, groupFiles]) => (
                  <div key={groupId} className="bg-white dark:bg-slate-900/60 border border-black/10 dark:border-slate-700/50 rounded-xl overflow-hidden">
                    <div className="bg-gray-50 dark:bg-slate-800/80 p-2 px-4 text-xs font-medium text-gray-700 dark:text-slate-300 flex justify-between items-center border-b border-black/10 dark:border-slate-700/50">
                      <span className="flex items-center gap-2">
                        <AlertTriangle className="w-3 h-3 text-amber-500" />
                        중복 그룹 #{groupId} (동일 파일 {groupFiles.length}개)
                      </span>
                      <span className="text-amber-400">{groupFiles[0].sizeMB} MB</span>
                    </div>
                    {groupFiles.map((file, i) => (
                      <div key={i} className="flex items-center p-3 hover:bg-gray-50 dark:bg-slate-800/60 border-b border-black/10 dark:border-slate-700/30 transition-colors group last:border-b-0">
                        <div className="w-8 cursor-pointer" onClick={() => toggleSelect(file.path)}>
                          {selectedPaths.has(file.path) ? <CheckSquare className="w-5 h-5 text-indigo-400" /> : <Square className="w-5 h-5 text-slate-500 group-hover:text-gray-500 dark:text-slate-400" />}
                        </div>
                        <div className="flex-1 min-w-0 pr-4">
                          <div className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate">{file.name}</div>
                          <div className="text-xs font-mono text-slate-500 truncate mt-0.5" title={file.path}>{file.path}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}
