import { useState, useEffect, useRef } from 'react';
import { Trash2, Search, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

// 잔여물로 잡힌 이유. 백엔드 uninstaller.find_leftovers 의 confidence 값.
const CONFIDENCE_LABEL = {
  certain: '프로그램이 등록한 설치 폴더',
  likely: '프로그램 이름과 같은 폴더 — 설정·저장 데이터일 수 있습니다(다시 설치해 쓸 거면 그대로 두세요)',
};

// 1024 MB 이상은 GB 로
const mbText = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Number(mb).toFixed(1)} MB`);
// 너무 큰 폴더는 백엔드가 끝까지 세지 않는다(sizeCapped). 그 값은 '이 이상' 이다.
const leftoverSize = (l) => `${mbText(l.sizeMB || 0)}${l.sizeCapped ? ' 이상' : ''}`;

export default function Uninstaller({ addToast }) {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [leftovers, setLeftovers] = useState([]);
  const [chosen, setChosen] = useState(new Set());
  const [isCleaning, setIsCleaning] = useState(false);
  const [activeApp, setActiveApp] = useState(null);
  const [step, setStep] = useState('list'); // 'list' -> 'wait_uninstall' -> 'leftovers'
  const launchingRef = useRef(false);
  const [viaSettings, setViaSettings] = useState(false);   // Windows 설정 → 앱에서 제거하도록 안내했다     // 제거 프로그램을 띄우는 중(두 번 눌러 두 개가 뜨지 않게)

  const [cleanElapsed, setCleanElapsed] = useState(0);

  // 잔여물 찾기·정리는 진행률을 알 수 없다. 예전에는 1초마다 33%씩 올려 지어낸 진행률을 보였다. 경과 시간만 센다.
  useEffect(() => {
    let interval;
    if (isCleaning) {
      interval = setInterval(() => setCleanElapsed(t => t + 1), 1000);
    } else {
      setCleanElapsed(0);
    }
    return () => clearInterval(interval);
  }, [isCleaning]);

  const fetchApps = async () => {
    setLoading(true);
    try {
      const a = api();
      if (a?.getUninstallerApps) {
        const data = await a.getUninstallerApps();
        setApps(Array.isArray(data) ? data : []);
      } else {
        setApps([]);
      }
    } catch (e) {
      console.error('Error fetching uninstaller apps:', e);
      setApps([]);
      addToast?.('설치된 프로그램 목록을 읽지 못했습니다.', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (api()?.getUninstallerApps) {
      fetchApps();
      return undefined;
    }
    const onReady = () => fetchApps();
    window.addEventListener('pywebviewready', onReady);
    return () => window.removeEventListener('pywebviewready', onReady);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleUninstall = async (app) => {
    const a = api();
    if (!a?.uninstallApp) {
      addToast?.('제거 기능이 준비되지 않았습니다.', 'error');
      return;
    }
    if (launchingRef.current) return;
    // 일부 프로그램(Discord 처럼 Update.exe --uninstall 을 쓰는 것)은 확인 창 없이 바로 지워진다. 줄에 마우스를
    // 올리면 나타나는 버튼이라 잘못 누르기 쉬워, 무엇을 지우는지 보여 주고 확인을 받는다.
    if (!window.confirm(
      `'${app.name}'${app.publisher ? ` (${app.publisher})` : ''} 의 제거 프로그램을 실행합니다.\n\n` +
      '일부 프로그램은 확인 창 없이 바로 제거되며, 되돌리려면 다시 설치해야 합니다.\n\n계속할까요?'
    )) return;
    launchingRef.current = true;
    try {
      // 이름만 넘긴다. 실행할 제거 명령은 백엔드가 레지스트리에서 직접 찾는다.
      const res = await a.uninstallApp(app.name);
      if (res?.needsSettings) {
        // 사용자 폴더에 설치된 프로그램: Windows 설정 → 앱에서 제거한 뒤 여기서 남은 폴더를 찾는다
        addToast?.(res.message, 'info');
        setViaSettings(true);
        setActiveApp(app);
        setStep('wait_uninstall');
        return;
      }
      if (!res?.success) {
        addToast?.(res?.message || '제거 프로그램을 실행하지 못했습니다.', 'error');
        return;
      }
      setViaSettings(false);
      setActiveApp(app);
      setStep('wait_uninstall');
    } catch (e) {
      console.error('IPC Error launching uninstaller:', e);
      addToast?.('제거 프로그램을 실행하는 중 오류가 발생했습니다.', 'error');
    } finally {
      launchingRef.current = false;
    }
  };

  const handleScanLeftovers = async () => {
    const a = api();
    if (!a?.findAppLeftovers || !activeApp) return;
    setIsCleaning(true);
    try {
      const res = await a.findAppLeftovers(activeApp.name);
      if (res?.stillInstalled) {
        // 아직 설치돼 있으면 찾지 않는다. 쓰고 있는 프로그램 폴더가 '잔여물' 로 잡히지 않게.
        addToast?.(res.message, 'info');
        return;
      }
      if (!res?.success) {
        addToast?.(res?.message || '남은 폴더를 찾지 못했습니다.', 'error');
        return;
      }
      const items = Array.isArray(res.items) ? res.items : [];
      setLeftovers(items);
      // 프로그램이 등록한 설치 폴더만 미리 고른다. 이름만 같은 AppData·ProgramData 폴더는 설정·저장 데이터일 수 있어
      // (예: OBS 의 장면·프로필) 사용자가 직접 고르게 한다. 예전에는 전부 골라 둔 채 '설치 폴더 잔여물' 처럼 보였다.
      setChosen(new Set(items.filter((l) => l.confidence === 'certain').map((l) => l.path)));
      setStep('leftovers');
    } catch (e) {
      console.error('IPC Error scanning leftovers:', e);
      addToast?.('남은 폴더를 찾는 중 오류가 발생했습니다.', 'error');
    } finally {
      setIsCleaning(false);
    }
  };

  const toggleLeftover = (path) => setChosen((s) => {
    const n = new Set(s);
    if (n.has(path)) n.delete(path); else n.add(path);
    return n;
  });

  const backToList = () => {
    setStep('list');
    setActiveApp(null);
    setLeftovers([]);
    setChosen(new Set());
    fetchApps();
  };

  const handleCleanLeftovers = async () => {
    const a = api();
    if (!a?.cleanAppLeftovers || !chosen.size) return;
    setIsCleaning(true);
    let res = null;
    try {
      res = await a.cleanAppLeftovers([...chosen]);
      // 결과 그대로 알린다. 일부를 건너뛰었는데 '완벽 삭제' 라고 하지 않는다.
      const failedCount = Array.isArray(res?.failed) ? res.failed.length : 0;
      if (!res || res.success === false) {
        const why = res?.failed?.[0]?.reason ? ` (${res.failed[0].reason})` : '';
        addToast?.((res?.message || '남은 폴더를 정리하지 못했습니다.') + why, 'error');
      } else if (failedCount > 0) {
        addToast?.(`[${activeApp.name}] ${res.message}`, 'info');
      } else {
        addToast?.(`[${activeApp.name}] ${res.message || '남은 폴더를 휴지통으로 보냈습니다.'}`, 'success');
      }
    } catch (e) {
      console.error('IPC Error cleaning leftovers:', e);
      addToast?.('남은 폴더를 정리하는 중 오류가 발생했습니다.', 'error');
    } finally {
      setIsCleaning(false);
    }
    const failed = Array.isArray(res?.failed) ? res.failed : null;
    if (res && res.success !== false && failed && failed.length === 0) {
      backToList();
      return;
    }
    // 실패·일부 실패면 이 화면에 머문다. 제거가 끝난 프로그램은 목록에서 사라져, 돌아가면 다시 찾을 길이 없었다.
    // 휴지통으로 보낸 것만 빼고, 남은 것에는 이유를 붙여 다시 시도할 수 있게 한다.
    if (failed) {
      // 백엔드가 돌려주는 경로는 모양이 다를 수 있다(끝의 역슬래시, 대소문자). 같은 정규화로 맞춘다.
      // 어느 항목인지 맞추지 못한 실패가 있으면 고른 항목을 하나도 빼지 않는다(보내지 못한 폴더가 사라져 보이지 않게).
      const key = (p) => String(p || '').replace(/[\\/]+$/, '').toLowerCase();
      const why = new Map(failed.filter((f) => f && f.path).map((f) => [key(f.path), f.reason || '']));
      const matched = new Set(leftovers.map((l) => key(l.path)).filter((k) => why.has(k)));
      const unmatched = failed.length > matched.size;
      const left = leftovers.filter((l) => !chosen.has(l.path) || why.has(key(l.path)) || unmatched)
        .map((l) => (why.has(key(l.path)) ? { ...l, failReason: why.get(key(l.path)) } : l));
      setLeftovers(left);
      setChosen(new Set(left.filter((l) => chosen.has(l.path)).map((l) => l.path)));
    }
  };

  const q = searchQuery.trim().toLowerCase();
  const filteredApps = apps.filter(app =>
    !q || app.name.toLowerCase().includes(q) || (app.publisher || '').toLowerCase().includes(q)
  );
  const chosenList = leftovers.filter((l) => chosen.has(l.path));
  const chosenMB = chosenList.reduce((s, l) => s + (l.sizeMB || 0), 0);
  // 너무 커서 끝까지 세지 않은 폴더가 있으면 합계도 '이상' 이다
  const chosenCapped = chosenList.some((l) => l.sizeCapped);

  return (
    <div className="h-full flex flex-col glass-panel rounded-2xl p-6 relative overflow-hidden">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-black dark:text-white flex items-center gap-2">
            <Trash2 className="w-6 h-6 text-rose-400" />
            프로그램 삭제
          </h2>
          <p className="text-gray-500 dark:text-slate-400 mt-1">
            프로그램의 제거 프로그램을 실행한 뒤, 설치 폴더와 AppData·ProgramData 의 같은 이름 폴더(설정·저장 데이터일 수 있음)를 찾아 보여 줍니다. 고른 폴더만 휴지통으로 보냅니다(휴지통에서 되살릴 수 있습니다).
            레지스트리는 건드리지 않습니다.
          </p>
        </div>
      </div>

      {step === 'list' && (
        <>
          <div className="relative mb-6">
            <Search className="w-5 h-5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 dark:text-slate-400" />
            <input
              type="text"
              placeholder="프로그램 이름이나 게시자로 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-white dark:bg-slate-900/50 border border-black/10 dark:border-slate-700/50 rounded-xl py-3 pl-10 pr-4 text-gray-800 dark:text-slate-200 focus:outline-none focus:border-rose-500/50 transition-colors"
            />
          </div>

          {!loading && apps.length > 0 && (
            <p className="text-xs text-gray-500 mb-2">
              {q ? `${apps.length}개 중 ${filteredApps.length}개` : `설치된 프로그램 ${apps.length}개`}
            </p>
          )}

          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
            {loading ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-slate-400">
                <Loader2 className="w-8 h-8 animate-spin text-rose-500 mb-4" />
                <p>설치된 프로그램 목록을 읽는 중입니다...</p>
              </div>
            ) : filteredApps.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-slate-500">
                <Trash2 className="w-12 h-12 mb-4 opacity-20" />
                <p>{apps.length === 0 ? '설치된 프로그램을 찾지 못했습니다.' : '검색된 프로그램이 없습니다.'}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredApps.map((app) => (
                  <div key={app.id} className="flex items-center justify-between p-4 bg-white dark:bg-slate-900/40 hover:bg-gray-50 dark:hover:bg-slate-800/60 border border-black/10 dark:border-slate-700/30 rounded-xl transition-colors group">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-gray-800 dark:text-slate-200 font-medium truncate">{app.name}</h3>
                      <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                        <span>{app.publisher || '게시자 알 수 없음'}</span>
                        {app.sizeMB > 0 && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                            <span className="text-rose-400/80" title="프로그램이 등록한 예상 크기">
                              {app.sizeMB >= 1024 ? `${(app.sizeMB / 1024).toFixed(1)} GB` : `${app.sizeMB} MB`}
                            </span>
                          </>
                        )}
                        {app.installDate && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                            <span>설치일: {app.installDate}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => handleUninstall(app)}
                      className="ml-4 px-4 py-2 bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500 hover:text-white rounded-lg transition-all duration-300 font-medium text-sm flex-shrink-0 flex items-center gap-2 opacity-0 group-hover:opacity-100 focus:opacity-100"
                    >
                      <Trash2 className="w-4 h-4" />
                      삭제
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {step === 'wait_uninstall' && (
        <div className="flex-1 flex flex-col items-center justify-center text-center max-w-lg mx-auto">
          <div className="w-20 h-20 rounded-full bg-amber-500/10 flex items-center justify-center mb-6 border border-amber-500/20">
            <Trash2 className="w-10 h-10 text-amber-500" />
          </div>
          <h3 className="text-xl font-bold text-black dark:text-white mb-2">
            {viaSettings ? `[${activeApp?.name}] 은(는) Windows 설정에서 제거해 주세요` : `[${activeApp?.name}] 제거 프로그램을 실행했습니다`}
          </h3>
          <p className="text-gray-500 dark:text-slate-400 mb-8">
            {viaSettings
              ? '사용자 폴더에 설치된 프로그램이라 관리자 권한인 이 앱이 제거 프로그램을 실행하지 않습니다. 열린 Windows 설정 → 앱에서 제거를 마친 뒤 아래 버튼으로 남은 폴더를 찾습니다.'
              : '화면에 뜬 제거 프로그램의 안내에 따라 제거를 끝까지 마쳐 주세요. 제거가 끝나면 아래 버튼으로 남은 폴더를 찾습니다.'}
            {' '}아직 설치돼 있으면 찾지 않습니다.
          </p>

          <div className="flex gap-4">
            <button
              onClick={backToList}
              disabled={isCleaning}
              className="px-6 py-3 bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 rounded-xl hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors font-medium text-sm disabled:opacity-40"
            >
              건너뛰기
            </button>
            <button
              onClick={handleScanLeftovers}
              disabled={isCleaning}
              className="px-6 py-3 bg-rose-500 text-white rounded-xl hover:bg-rose-600 shadow-lg shadow-rose-500/20 transition-all font-medium text-sm flex items-center gap-2 disabled:opacity-60"
            >
              {isCleaning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {isCleaning ? `찾는 중... (${cleanElapsed}초)` : '제거를 마쳤습니다 — 남은 폴더 찾기'}
            </button>
          </div>
        </div>
      )}

      {step === 'leftovers' && (
        <div className="flex-1 flex flex-col items-center justify-center bg-white dark:bg-slate-900/30 rounded-xl border border-black/10 dark:border-slate-700/30 p-8 text-center">
          {isCleaning ? (
            <div className="flex flex-col items-center w-full max-w-md mx-auto">
              <Loader2 className="w-16 h-16 text-rose-500 animate-spin mb-6" />
              <h3 className="text-xl font-bold text-black dark:text-white mb-2">남은 폴더를 휴지통으로 보내는 중...</h3>
              <p className="text-gray-500 dark:text-slate-400 font-mono text-sm">경과 {cleanElapsed}초</p>
            </div>
          ) : (
            <div className="w-full max-w-2xl text-left">
              <div className="flex items-center justify-center gap-3 mb-6">
                {leftovers.length > 0 ? (
                  <AlertTriangle className="w-10 h-10 text-amber-500" />
                ) : (
                  <CheckCircle className="w-10 h-10 text-emerald-500" />
                )}
                <h3 className="text-2xl font-bold text-black dark:text-white">
                  {leftovers.length > 0 ? `남은 폴더 ${leftovers.length}개를 찾았습니다` : '남은 폴더가 없습니다.'}
                </h3>
              </div>

              {leftovers.length > 0 && (
                <div className="bg-gray-100 dark:bg-slate-950/50 rounded-xl border border-amber-500/30 p-4 mb-6 max-h-[300px] overflow-y-auto custom-scrollbar">
                  <p className="text-amber-500 text-sm mb-3">휴지통으로 보낼 폴더를 고르세요. 다른 프로그램이 쓰는 폴더라면 선택을 해제하세요.</p>
                  <ul className="space-y-2">
                    {leftovers.map((l) => (
                      <li key={l.path}>
                        <button
                          type="button"
                          aria-pressed={chosen.has(l.path)}
                          onClick={() => toggleLeftover(l.path)}
                          className={`w-full text-left text-xs bg-white dark:bg-slate-900 p-2 rounded border flex items-center gap-3 ${
                            chosen.has(l.path) ? 'border-rose-500/50' : 'border-black/10 dark:border-slate-800 opacity-60'}`}
                        >
                          <span className={`w-4 h-4 rounded shrink-0 border ${chosen.has(l.path) ? 'bg-rose-500 border-rose-500' : 'border-gray-400'}`} />
                          <span className="min-w-0 flex-1">
                            <span className="block font-mono text-gray-700 dark:text-slate-300 truncate" title={l.path}>{l.path}</span>
                            <span className={`block text-[0.6875rem] ${l.confidence === 'likely' ? 'text-amber-500' : 'text-gray-500'}`}>{CONFIDENCE_LABEL[l.confidence] || l.reason}</span>
                            {l.failReason && <span className="block text-[0.6875rem] text-rose-400">보내지 못함: {l.failReason}</span>}
                          </span>
                          <span className="text-rose-400 flex-shrink-0 font-mono">{leftoverSize(l)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-center gap-4">
                <button
                  onClick={backToList}
                  className="px-6 py-2.5 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-300 rounded-xl transition-colors font-medium"
                >
                  돌아가기
                </button>
                {leftovers.length > 0 && (
                  <button
                    onClick={handleCleanLeftovers}
                    disabled={!chosen.size}
                    className="px-6 py-2.5 bg-gradient-to-r from-rose-600 to-rose-500 hover:from-rose-500 hover:to-rose-400 text-white rounded-xl transition-all shadow-lg shadow-rose-500/25 font-medium flex items-center gap-2 disabled:opacity-40"
                  >
                    <Trash2 className="w-4 h-4" />
                    {chosen.size ? `선택한 ${chosen.size}개를 휴지통으로 (${mbText(chosenMB)}${chosenCapped ? ' 이상' : ''})` : '폴더를 선택하세요'}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
