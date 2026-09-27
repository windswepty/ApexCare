# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

범용 개발 지침은 `~/.claude/CLAUDE.md` 에 있습니다. 여기에는 APEX CARE 에만 해당하는 규칙을 둡니다.

## 프로젝트 규칙 (필수)

`.agents/AGENTS.md` 에 정의된 규칙이며 예외 없이 적용합니다.

1. **앱을 고치면 설치 파일을 다시 빌드** — 앱 코드·기능·설치 마법사(`tools/setup_wizard.py`)를 바꿨으면 아래 `build_all.bat` 를 실행합니다.
2. **작업 완료 시 자동 커밋·푸시** — 요청을 끝내면 사용자가 말하지 않아도 커밋하고 `origin main` 에 푸시합니다. 전역 지침의 "요청하지 않은 푸시 금지"보다 이 규칙이 우선합니다. 강제 푸시와 하드 리셋은 여전히 요청이 있을 때만 합니다.
   커밋 메시지는 `type(scope): 한국어 설명` 형식입니다 (예: `fix(safety): 데이터 소실·원격코드 경로 차단`).

## 무엇인가

Windows PC 최적화 데스크톱 앱입니다. Python 백엔드(`backend/`)와 React UI(`src/`)를 pywebview 로 묶습니다.
`main.py` 가 `backend.api.Api` 를 JS API 로 노출하고 `dist_react/index.html` 을 띄웁니다.

**실행 파일은 `uac_admin=True` 라서 관리자 권한으로 돕니다.** 그래서 이 앱의 버그는 곧 사용자 PC 손상입니다.
상업 출시가 목표이고, 사용자 조건은 "컴퓨터에 손상이 가면 안 된다"입니다.

`web/` 는 별도 정적 웹사이트(브라우저 PC 진단 도구)입니다. 앱 작업에서는 건드리지 않습니다.

## 명령어

```bash
npm run build          # React → dist_react/
python main.py         # 개발 실행 (dist_react 가 없으면 localhost:5173 을 띄움)
build_all.bat          # 프론트 → Payload.exe → Uninstaller.exe → Setup (최종: dist\APEX CARE Setup 1.0.1.exe)
python -c "import backend.api"   # 백엔드 전체 import 확인
pip install -r requirements-dev.txt   # 테스트 의존성 (psutil, pytest)
python -m pytest tests                # 안전 규칙 테스트. 가짜 Windows 위에서 돈다 (리눅스·윈도우 모두)
```

`tests/fakewin.py` 가 winreg·전원 API·sc.exe·APPDATA 를 가짜로 바꾸고, ctypes.WinDLL·subprocess·psutil 의
우선순위 변경은 부르는 즉시 예외가 나게 막습니다. `tests/conftest.py` 는 가짜를 끼우기 전에 backend import 를 막는
문지기를 먼저 세우므로, 가짜가 빠지면 테스트는 수집 단계에서 멈춥니다.
안전 규칙을 고치거나 새로 만들면 `tests/` 에 테스트를 더하고, 고친 부분을 되돌리면 그 테스트가 실패하는지 확인합니다.
새로 흉내 내야 하는 Win32 호출이 생기면 테스트에서 진짜를 풀지 말고 `fakewin` 에 가짜를 더합니다.
GitHub Actions(`.github/workflows/tests.yml`)가 main 푸시와 PR 마다 우분투 24.04 와 Windows Server 2025(각각 Python 3.12·3.13)에서 같은 테스트를 돌립니다.
비공개 개인 저장소라 GitHub 규칙(`main-tests` 필수 체크)은 적용되지 않습니다. 대신 `.githooks/pre-push` 가 main 으로
갈 커밋을 임시 폴더에 풀어 테스트하고, 실패하면 푸시를 멈춥니다. 클론마다 `git config core.hooksPath .githooks` 로 켭니다.
훅이 푸시를 막으면 테스트를 고칩니다. `git push --no-verify` 로 건너뛰지 않습니다.

`build_setup.bat` 는 Setup 만 다시 쌉니다. Setup 은 `dist\APEX CARE Payload.exe` 를 그대로 담고, 빌드가 끝나면 그 파일을 지웁니다.
그래서 **앱 코드를 고쳤으면 반드시 `build_all.bat`** 를 씁니다.

## 안전 규칙

감사에서 치명적인 문제가 13건 나왔습니다. 언인스톨러가 Adobe 폴더 22.8GB와 Steam 게임 라이브러리를 "잔여물"로 잡았고,
성능 모드는 원래 값을 기록하지 않고 레지스트리와 전원 설정을 덮어썼습니다. 아래 규칙은 이런 사고가 다시 나지 않게 하려고 둡니다.

### 삭제

- 사용자 파일은 `safe_delete.to_recycle_bin()` 으로만 지웁니다 (휴지통 경유). 사용자 파일에 `shutil.rmtree` / `os.remove` / `os.unlink` 를 직접 쓰지 않습니다.
- 경로 경계는 `safe_delete.norm()` 으로 정규화(realpath)한 뒤 `is_protected()` / `is_inside()` 로 판단합니다. 문자열 부분 일치로 판단하지 않습니다.
- 영구 삭제는 임시 파일·캐시 정리와 휴지통 비우기뿐입니다. 휴지통 비우기는 기본으로 선택 해제하고, 되돌릴 수 없다는 확인을 받은 뒤에만 실행합니다.
- 이름으로 폴더를 추정해서 지우지 않습니다. 언인스톨러 잔여물은 `InstallLocation` 을 기준으로 찾고, 이름은 정규화 후 정확히 일치할 때만 후보로 올립니다.

### 시스템 변경 (레지스트리·전원·서비스)

- 반드시 `backend/system_state` 를 거칩니다: `set_registry()`, `set_active_plan()`, `set_power_value()`, `set_service_start()`.
  이 함수들은 바꾸기 전에 원래 값을 한 번만 기록하고, 쓴 뒤 다시 읽어 확인합니다. 되돌릴 때는 `restore_group()` 을 씁니다.
  원래 값을 읽지 못했거나 저널 저장에 실패하면 바꾸지 않습니다(되돌릴 수 없는 변경이 되므로).
- 서비스는 시작 유형만 바꿉니다(`set_service_start(서비스, 'auto'|'delayed-auto'|'demand'|'disabled', group)`, sc.exe 인자 리스트).
  실행 중인 서비스를 즉시 시작·중지하지 않습니다. 그 상태는 기록·복구할 수 없어서입니다.
- 추측한 "기본값"을 쓰는 것은 복구가 아닙니다. 원래 값이 없었으면 값을 삭제하는 것이 복구입니다.
- 복구가 실패하면 백업이나 저널 기록을 지우지 않습니다. 그래야 다시 시도할 수 있습니다.
- 성능 모드 전환은 `perf_modes.apply_mode()` 한 곳에서만 합니다. 새 모드를 적용하기 전에 이전 모드를 먼저 되돌립니다.
  '표준' 은 되돌리기만 하고 전원 플랜을 바꾸지 않습니다. 게임 부스트는 `persist=False` 로 게임 동안만 게이밍 모드를 쓰고 끝나면 게임 전 모드로 돌아갑니다.
- 구버전이 `settings.json` 에 남긴 백업(`network_tweak_backup`, `service_start_backup`)은 있을 때만 그 값으로 복구합니다. 없으면 아무것도 쓰지 않습니다.
- 저널 위치: `%APPDATA%\APEX_CARE_DATA\system_state.json`. 설정 파일: 같은 폴더의 `settings.json`.

### 프로세스

- 우선순위 변경은 `backend/process_boost` 로만 합니다 (원래 값 기록 → 복구). 건드려도 되는 프로세스인지는 `process_guard.check_controllable()` 한 곳에서 판정합니다.
- 앱을 닫을 때 우선순위와 게임 부스트를 되돌립니다 (`Api._cleanup` → `game_booster.shutdown()`). `os._exit` 로 정리 없이 끝내지 않습니다.
  종료 경로에서 `toggle_booster(False)` 를 부르지 않습니다. 사용자 설정(부스터 켜짐)이 꺼짐으로 저장됩니다.
- `process_boost.set_priority()` 에는 `owner`('user'·'boost'·'eco')를 넘깁니다. 게임이 끝날 때 부스트가 바꾼 것만 되돌리고,
  사용자가 직접 바꾼 것은 남깁니다. PID 재사용은 프로세스 생성 시각으로 걸러집니다.

### 명령 실행과 외부 자원

- `subprocess` 는 `shell=False` 와 인자 리스트로 부릅니다. 설정 파일·레지스트리·UI 에서 온 문자열을 명령줄에 끼워 넣지 않습니다.
- 관리자 권한 창이므로 외부 CDN·웹폰트·원격 스크립트를 쓰지 않습니다. Tailwind 는 로컬에서 빌드합니다.

### UI 는 사실만 말합니다

- 백엔드는 항목별 성패(`steps`, `failed`)를 돌려주고, UI 는 그것을 그대로 보여줍니다. 결과를 받기 전에 성공 토스트를 띄우지 않습니다. 부분 실패는 성공이 아닙니다.
- 되돌릴 수 없는 동작은 대상 목록을 보여주고 확인을 받습니다. 기본 선택은 안전한 쪽으로 둡니다.

## 개발 중 하지 말 것

- **시스템을 바꾸는 코드를 개발 PC 에서 실행하지 않습니다.** 모드 적용, 정크 정리, 디블로터, 서비스·네트워크 변경이 모두 해당됩니다.
  로직은 `python -m pytest tests`(가짜 Windows)로 검증하고, 실제 적용 후 되돌리기까지 확인하는 테스트는 사용자가 관리자 권한으로 실행하도록 안내합니다.
- 테스트에서 fakewin 을 우회하지 않습니다. `fakewin.REAL` 의 진짜 객체는 문지기 자가 테스트(별도 파이썬 프로세스)에만 씁니다.
  backend 를 직접 부르는 스크립트를 `tests/` 밖에 새로 만들지 않습니다. 성능 모드를 바꾸고 대기 메모리를 비우던 옛 스크립트
  (`test_performance.py`, `test_standby.py`, `tools/test_full.py`, `tools/test_backend.py`)는 그래서 지웠습니다.
  남은 `tools/test_logic.py`, `tools/test_comprehensive.py` 는 읽기만 합니다.
- 개발 PC 에는 구버전이 남긴 설정(`NetworkThrottlingIndex=0xFFFFFFFF`, `HwSchMode=2`)이 남아 있습니다. 이 값을 "원래 값"으로 가정하지 않습니다.
- 초기 설정 마법사는 `settings.json` 의 `setup_wizard_done` 이 없을 때만 뜹니다. 마법사를 닫는 것(`markSetupWizardDone`)은 시스템을 바꾸지 않습니다.

## 빌드 함정

- `backend/` 모듈 상당수는 순환 import 를 피하려고 함수 안에서 import 됩니다. PyInstaller 가 이런 모듈을 찾지 못하므로,
  **새 백엔드 모듈은 `APEX CARE Payload.spec` 의 `hiddenimports` 에 반드시 추가합니다.** 빠뜨리면 개발 실행은 멀쩡하고 설치 파일에서만 실패합니다.
- `package.json` 이 `"type": "commonjs"` 라서 PostCSS·Tailwind 설정 파일은 `.cjs` 여야 합니다.
- 프론트가 부르는 `window.pywebview.api.X` 는 `backend/api.py` 의 `Api` 메서드 이름과 같아야 합니다.

## 구조

| 백엔드 | 역할 |
|---|---|
| `api.py` | UI 가 부르는 모든 것의 진입점 |
| `safe_delete.py` | 휴지통 삭제, 보호 경로 판정 |
| `system_state.py` | 시스템 변경 저널 (원래 값 기록·확인·복구) |
| `perf_modes.py` | 성능 모드 (표준·게이밍·에코) |
| `process_boost.py` · `process_guard.py` | 프로세스 우선순위 변경·복구, 건드려도 되는지 판정 |
| `game_booster.py` | 게임 감지, 부스트, 에코 억제 |
| `optimizer.py` | 정크 정리, 시작 프로그램, 원클릭 최적화, 하드웨어 맞춤 튜닝 |
| `storage.py` · `file_finder.py` | 드라이브 현황, 대용량·중복 파일 |
| `uninstaller.py` · `debloater.py` | 앱 제거·잔여물, 기본 앱 제거 |
| `system_repair.py` · `system_monitor.py` | TRIM·SFC·DISM·네트워크, 시스템 상태·프로세스 목록 |
| `config_manager.py` | 설정 파일 |

UI 탭은 `src/components/Sidebar.jsx` 에 정의되고 `src/App.jsx` 가 라우팅합니다.
설치·제거 프로그램 소스는 `tools/setup_wizard.py` 와 `tools/uninstall.py` 입니다.
