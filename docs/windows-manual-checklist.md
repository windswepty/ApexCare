# 실제 Windows 점검표

`python -m pytest tests` 는 가짜 Windows 위에서 **논리**만 확인합니다. 진짜 전원 API·sc.exe·레지스트리·셸이
기대대로 반응하는지는 이 점검표로 확인합니다. 상업 출시 전과, 시스템을 바꾸는 코드를 고친 뒤에 돌립니다.

원칙: **모든 기능은 "적용 → 되돌리기" 뒤에 상태가 처음과 같아야 합니다.** 눈으로 보지 말고
`tools/snapshot_state.ps1` 로 전후 상태를 떠서 비교합니다.

---

## 자동 점검 (Windows 샌드박스) — 먼저 이것부터

손으로 하는 점검 중 백엔드가 하는 일(성능 모드, 디블로터 정책·앱, 맞춤 튜닝, 시작 프로그램, 게임 부스트 Nagle,
정크 정리 정션·확보 용량, SFC 출력 해독, 설치된 프로그램 폴더를 잔여물로 잡지 않기, 프로세스 우선순위, 제거 전 되돌리기,
원클릭 범위)과 **빌드한 설치 파일로 설치 → 제거 프로그램**
(1-2, 13절의 설치 폴더·프로그램 목록 키·바로 가기 정리와 설치된 exe 의 되돌리기)은 샌드박스에서 자동으로 확인할 수 있습니다.
샌드박스는 닫으면 안의 변경이 전부 사라져 개발 PC 는 바뀌지 않습니다.

1. 한 번만: 관리자 PowerShell 에서 `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All` → 재부팅
   (PowerShell 7 에서 "클래스가 등록되지 않았습니다" 가 나오면 `dism.exe /online /enable-feature /featurename:Containers-DisposableClientVM /all`)
2. `build_all.bat` 로 `dist` 에 최신 설치 파일을 만든 뒤
   `powershell -ExecutionPolicy Bypass -File tools\sandbox\start_sandbox_check.ps1 -Wait`
   (`dist` 가 없으면 설치·제거 점검만 건너뜁니다. 다른 위치면 `-Dist <폴더>`)
3. 샌드박스 창에 "업데이트하지 못했습니다" 가 뜨면 **아니요** 를 눌러야 부팅이 계속됩니다
4. 결과 폴더의 `report.md` 를 봅니다. 실패 항목에는 처음 상태와 달라진 줄이 함께 적힙니다

디블로터 앱 제거·되살리기는 샌드박스에서 확인할 수 없습니다(항상 SKIP). 샌드박스에는 스토어 앱이 없고, 있는 시스템 앱은
모두 제거 불가(NonRemovable)입니다(2026-09-28 확인). 점검은 지워도 되는 앱이 생기면 자동으로 돌도록 남겨 두었습니다.
**앱 제거·되살리기는 5절로 실제 PC(가상 머신)에서 확인합니다.**
화면(APEX CARE 창의 확인 창·목록 표시), 재부팅 뒤 동작, OneDrive 는 자동 점검 범위 밖이라 아래 절차로 확인합니다.

## 0. 준비

- [ ] **개발 PC 에서 하지 않습니다.** Hyper-V·VirtualBox 등의 Windows 11 가상 머신(한국어판 권장)을 쓰고,
      시작 전에 **스냅숏(검사점)** 을 만듭니다. 개발 PC 에는 구버전이 남긴 값이 있어 "원래 값" 비교가 틀립니다.
      Windows 샌드박스도 되지만 재부팅 항목(3-4, 6-5)은 할 수 없습니다.
- [ ] 최신 코드로 설치 파일을 만듭니다: 개발 PC 에서 `build_all.bat` → `dist\APEX CARE Setup 1.0.1.exe`.
      (`dist` 의 파일이 마지막 앱 코드 커밋보다 오래됐으면 반드시 다시 빌드)
- [ ] 가상 머신에 `C:\apex` 폴더를 만들고 설치 파일과 `tools\snapshot_state.ps1` 을 복사합니다.
- [ ] 관리자 PowerShell 을 열고 아래 두 명령을 익혀 둡니다. 이 문서에서 **스냅숏** `이름` 은 첫 줄, **비교** `A` `B` 는 둘째 줄입니다.

```powershell
powershell -ExecutionPolicy Bypass -File C:\apex\snapshot_state.ps1 -Out C:\apex\이름.txt
Compare-Object (Get-Content C:\apex\A.txt) (Get-Content C:\apex\B.txt)
```

비교 결과가 **아무것도 안 나오면 같다**는 뜻입니다. `=>` 는 B 에만, `<=` 는 A 에만 있는 줄입니다.

- [ ] `powercfg /list` 로 플랜을 확인해 적어 둡니다. 가상 머신·최신 노트북에는 고성능·절전 플랜이 없을 수 있습니다.
      없으면 게이밍·에코는 "균형 조정 위에 세부 설정만" 적용된다는 안내가 떠야 합니다(3-5).

| 적어 둘 것 | 값 |
|---|---|
| Windows 버전 (`winver`) | |
| 설치 파일 빌드 커밋 | |
| 있는 전원 플랜 | |

---

## 1. 설치와 첫 실행 — 아무것도 바꾸지 않아야 한다

- [ ] 1-1. 설치 전 **스냅숏** `00-before-install`
- [ ] 1-2. 설치 파일 실행 → 설치 경로가 `%LOCALAPPDATA%\APEX CARE`, 바탕화면 바로가기, 설정 → 앱 목록에 "APEX CARE" 가
      크기(약 수십 MB)와 함께 보인다. 진행 막대는 파일 복사량만큼만 움직인다(멈칫거리는 가짜 진행 없음)
- [ ] 1-2a. APEX CARE 를 켜 둔 채 설치 파일을 다시 실행 → "APEX CARE 가 실행 중이라 파일을 바꿀 수 없습니다" 가 나오고
      설치 폴더의 exe 가 깨지지 않는다(반쯤 쓴 파일이 남지 않음)
- [ ] 1-3. APEX CARE 실행 → UAC 창이 뜬다(관리자 권한)
- [ ] 1-3a. 대시보드: 켜자마자 CPU·GPU 는 "측정 중" 이다가 수 초 안에 숫자가 된다. 작업 관리자 성능 탭의 CPU %·GPU '3D'·
      메모리 '사용 중'·'사용 가능' 과 몇 % 안에서 같다. GPU 카운터가 없는 PC(가상 머신 등)는 "측정 불가" 로 보인다(0% 아님)
- [ ] 1-3b. 제목 표시줄의 최대화 버튼 → 창이 작업 표시줄을 **가리지 않고** 화면을 채운다(모니터가 여럿이면 창이 있는 모니터).
      다시 누르면 전의 위치·크기로 돌아간다
- [ ] 1-4. 초기 설정 마법사가 뜬다. 맞춤 튜닝 **미리보기**에 바뀔 항목(SysMain 등)이 보이지만, **적용하지 않고** 닫는다
- [ ] 1-5. 앱을 닫고 **스냅숏** `01-first-run` → **비교** `00-before-install` `01-first-run`
      기대: `[APEX CARE]` 부분(설정 파일 생김, `setup_wizard_done = True`)만 다르다. 전원·레지스트리·서비스는 같다
- [ ] 1-6. 앱을 다시 실행 → 마법사가 **다시 뜨지 않는다**. 닫는다
- [ ] 1-7. **스냅숏** `base` — 이후 모든 비교의 기준

---

## 2. '변경 내역 · 되돌리기' 가 비어 있는 상태

- [ ] 2-1. '변경 내역 · 되돌리기'에 "되돌릴 변경 없음" 으로 나온다
- [ ] 2-2. "전부 원래대로" 를 눌러도 **스냅숏** `02` 가 `base` 와 같다(바꾼 적 없는 것을 추측해 쓰지 않는다)

---

## 3. 성능 모드

- [ ] 3-1. **게이밍** 적용 → 결과 화면에 항목별 성공/실패가 나온다. **스냅숏** `03-gaming`, **비교** `base` `03-gaming`
      기대 차이만 있어야 한다:
      - 활성 플랜 `8c5e7fda-…`(고성능)
      - 고성능 플랜의 CPU 최소·최대·코어 파킹 `AC=0x00000064 DC=0x00000064`, USB 선택적 절전 `AC=0x00000000 DC=0x00000000`
      - 고성능 플랜의 CPU 부스트 모드 `0x00000002`(공격적), EPP `0x00000000`, PCIe 절전 `0x00000000`(끔)
        (원래 그 값이었으면 차이가 없다. 이 PC 에 없는 항목은 결과 화면에 '건너뜀' 으로 나온다)
      - 헤더의 **CPU 실제 속도** 가 기본 클럭보다 높게(부스트) 나온다
      - `SystemResponsiveness = 10`, `NetworkThrottlingIndex = 4294967295`
      - 저널 항목(group=perf_mode), 설정 `optimization_mode = gaming`
      - **HwSchMode 는 바뀌지 않는다**
- [ ] 3-2. **표준** 적용 → **스냅숏** `03-standard` → **비교** `base` `03-standard`
      기대: `[APEX CARE]` 의 `optimization_mode`·`user_set` 줄만 다르다. 전원 플랜·레지스트리는 `base` 와 같다
- [ ] 3-3. **게이밍 → 에코**(표준을 거치지 않고) → 에코 기대값만 있어야 하고 게이밍이 남긴 값이 없어야 한다:
      활성 플랜 `a1841308-…`(절전), 절전 플랜의 최소 `0x00000005`·최대 `0x00000046`(70)·코어 `0x00000032`(50),
      부스트 모드 `0x00000000`(끔)·EPP `0x00000050`(80)·PCIe 절전 `0x00000002`, 헤더의 **CPU 실제 속도** 가 기본 클럭보다 낮다,
      `SystemResponsiveness`·`NetworkThrottlingIndex` 는 `base` 값. 그다음 **표준** → 3-2 와 같은 결과
- [ ] 3-4. **게이밍** 적용 → 가상 머신 **재부팅** → 앱 실행 → 여전히 게이밍(값 유지), '변경 내역 · 되돌리기'에 항목이 보인다 →
      **표준** → `base` 와 같다(3-2 기준)
- [ ] 3-5. (고성능 플랜이 없는 경우) 게이밍 적용 시 "균형 조정 위에 세부 설정만 적용" 안내가 뜨고, 표준으로 되돌리면 `base` 와 같다
- [ ] 3-6. **게이밍** 상태에서 앱 밖으로 전원 플랜을 바꾼 뒤(`powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e`)
      성능 모드 화면을 다시 열면 모드가 실제 상태와 다르다는 안내가 나온다. 앱에서 **표준** → `base` 와 같다
      (표준은 특정 플랜이 정답이 아니라서, 표준 상태에서 플랜을 바꾸면 안내가 나오지 않는 것이 맞다)
- [ ] 3-7. 제조사·직접 만든 전원 플랜을 쓰는 PC 에서 3-6 처럼 플랜을 바꾸면, 안내에 그 플랜의 **실제 이름** 이 나온다('알 수 없음' 이 아니다)

---

## 4. 맞춤 튜닝 (마법사 · 설정에서 다시 열기)

가상 머신 사양이 코어 4개 이하이거나 RAM 8GB 미만이면 "저사양", 아니면 "고사양" 입니다. 둘 다 보려면 가상 머신 사양을 바꿔 가며 합니다.

- [ ] 4-1. 미리보기만 하고 닫기 → **스냅숏** 이 `base` 와 같다
- [ ] 4-2. **저사양** 적용 → 기대 차이: `SysMain: Start=4` 와 저널(group=hw_tuning)만. **WSearch·전원 플랜은 그대로**
- [ ] 4-3. **고사양** 적용 → SysMain·WSearch 가 자동 시작(이미 "자동(지연된 시작)" 이면 그대로). 전원 플랜은 그대로
- [ ] 4-4. '변경 내역 · 되돌리기' "전부 원래대로" → `base` 와 같다
- [ ] 4-5. 서비스 시작 유형 변경은 **다음 부팅부터** 라는 안내가 나오고, 실행 중인 SysMain 을 즉시 멈추지 않는다
      (`Get-Service SysMain` 의 Status 가 그대로)

---

## 5. 디블로터

- [ ] 5-1. **원격 분석 줄이기** 만 선택해 실행 → 기대 차이: `AllowTelemetry = 0`, `DiagTrack: Start=4`, 저널(group=debloat).
      DiagTrack 이 **지금 멈추지는 않는다**(`Get-Service DiagTrack`)
- [ ] 5-2. **Cortana 끄기** → `AllowCortana = 0`
- [ ] 5-3. '변경 내역 · 되돌리기' "전부 원래대로" → `base` 와 같다(원래 없던 정책 값은 **지워져야** 함)
- [ ] 5-4. 앱 제거 항목에 "이 계정에서 제거 · 아래 '제거한 앱' 에서 되살리기" 표시가 있고, 실행 전에 패키지 이름과 함께 확인을 받는다
- [ ] 5-5. **Bing 앱**·**영화 및 TV** 제거 → `[Appx]` 에서 `Microsoft.BingNews`·`BingWeather`·`ZuneVideo` 만 사라지고
      `Microsoft.ZuneMusic`(미디어 플레이어)·`XboxGamingOverlay`(게임 바)·`GamingApp`(새 Xbox 앱)은 남는다.
      화면 아래 '제거한 앱' 에 지운 패키지가 나오고 `%APPDATA%\APEX_CARE_DATA\debloat_removed.json` 에 기록이 있다
- [ ] 5-6. 다른 계정에서는 그대로다: 두 번째 로컬 계정으로 로그인하면 Bing 앱이 남아 있다(현재 계정에서만 제거)
- [ ] 5-7. '모두 되살리기' → 결과에 되살린 개수가 나오고, **스냅숏** 의 `[Appx]` 가 제거 전과 같다. 시작 메뉴에서 앱이 열린다.
      '제거한 앱' 목록이 비고 `debloat_removed.json` 의 `apps` 가 빈 목록이다
- [ ] 5-8. 설치돼 있지 않은 항목(예: 3D Builder)을 고르면 "완료" 가 아니라 "설치돼 있지 않아 변경 없음" 으로 나온다
- [ ] 5-9. 표준 사용자 계정 `kim` 에 로그인한 채 UAC 창에서 **다른 관리자 계정**으로 APEX CARE 를 실행하면, 앱 제거가
      "다른 계정으로 실행 중" 이유로 거부되고 아무것도 지워지지 않는다
- [ ] 5-10. 실패한 항목이 있으면 "완료" 가 아니라 무엇이 왜 실패했는지 나온다
- [ ] 5-11. 앱 제거·되살리기 도중 창을 닫으려 하면 "기본 앱 제거·되살리기 진행 중" 안내가 나오고 닫히지 않는다
- [ ] 5-12. 화면을 열면 앱 항목마다 "설치됨"·"설치되어 있지 않음" 이 `Get-AppxPackage -Name <패키지>` 결과와 같게 보이고,
      설치되어 있지 않은 앱은 고를 수 없다('전체 선택' 에도 들어가지 않는다)

---

## 6. 게임 부스트

가짜 게임: 관리자 PowerShell 에서

```powershell
mkdir C:\apex\game; copy C:\Windows\System32\PING.EXE C:\apex\game\cs2.exe
C:\apex\game\cs2.exe -t 127.0.0.1      # 게임이 켜진 상태. Ctrl+C 로 끝낸다
```

- [ ] 6-1. 부스트 설정 기본값: 타이머 해상도·바쁜 앱 양보 **켜짐**, Nagle 끄기·게이밍 전원 모드 자동 전환 **꺼짐**.
      Windows 10 2004(빌드 19041) 이후에서는 타이머 해상도 항목 아래에 "이 Windows 에서는 … 적용하지 않습니다" 가 보이고,
      게임을 감지해도 부스트 상태에 '타이머 해상도' 가 나오지 않는다
- [ ] 6-2. 게임 부스트 켬, 기본 설정 그대로 → `cs2.exe` 실행 → 수 초 안에 감지('Counter-Strike 2 (cs2.exe)' 로 보인다).
      `Get-Process cs2 | select PriorityClass` 가 `High`.
      **스냅숏** 이 `base` 와 같다(기본 설정은 레지스트리·전원을 바꾸지 않는다) → Ctrl+C → 우선순위 기록이 사라진다
- [ ] 6-3. **Nagle 끄기**·**게이밍 전원 모드** 켬 → 앱에서 **에코** 모드 적용 → **스냅숏** `06-eco` → `cs2.exe` 실행 →
      모든 어댑터 `TcpAckFrequency=1 TCPNoDelay=1`, 활성 플랜 고성능, 설정 `optimization_mode = eco`(저장된 모드는 그대로),
      `boost_restore_mode = eco` → Ctrl+C → 몇 초 뒤 **스냅숏** `06-after` → **비교** `06-eco` `06-after` 가 같다
      (Nagle 원래 값 복원, 에코 모드로 복귀)
- [ ] 6-4. 게임 도중 앱을 **정상 종료**(창 닫기) → 부스트가 바꾼 것이 되돌아가 `06-eco` 와 같다.
      다시 실행하면 게임 부스트가 **여전히 켜져** 있다
- [ ] 6-5. 게임 도중 작업 관리자에서 `APEX CARE.exe` **강제 종료** → Nagle·전원 모드가 남아 있다(정상) →
      게임도 끝낸다(Ctrl+C. 켜 둔 채 앱을 열면 부스트가 다시 걸린다) → 앱을 다시 실행 → 몇 초 안에 `06-eco` 와 같아진다
      (지난 세션 잔여물 정리). 강제 종료 뒤 재부팅하고 실행해도 같아야 한다
- [ ] 6-6. 게임 도중 사용자가 성능 모드를 직접 **표준** 으로 고른 뒤 게임 종료 → 표준이 유지된다(게임 전 모드로 덮어쓰지 않음)
- [ ] 6-7. 게임 도중 부스트 설정에서 Nagle 끄기를 **새로 켠** 경우, 게임이 끝날 때 적용한 적 없는 Nagle 값을 지우지 않는다
- [ ] 6-8. 게임 도중(6-3 설정) **자동 감지 꺼짐** 을 누른다 → 알림이 "되돌렸습니다" 라고 할 때 이미 `06-eco` 와 같다
      (예전에는 알림 뒤 최대 2초 동안 되돌리지 않은 상태였다). 게임 우선순위도 원래대로(`Normal`)
- [ ] 6-9. `javaw.exe` 로 게임이 아닌 자바 프로그램을 실행해도 게임으로 감지하지 않는다(Minecraft 는 감지)
- [ ] 6-10. 끝나면 에코 → 표준, 부스트 설정 원래대로 → `base` 와 같다

---

## 7. 프로세스 (게이밍 탭 · 메모리 탭)

- [ ] 7-1. 메모장 두 개 실행. 하나를 "높음" 으로 → `Get-Process notepad | select Id,PriorityClass` 로 확인 →
      "모두 원래대로" → `Normal`
- [ ] 7-2. `explorer.exe`, `csrss.exe`, `svchost.exe` 의 우선순위 변경·종료가 **거부**되고 이유가 나온다
- [ ] 7-3. APEX CARE 자신과 그 WebView 프로세스는 종료할 수 없다
- [ ] 7-4. 메모장 종료는 된다

---

## 8. 정크 정리

준비(관리자 PowerShell):

```powershell
mkdir C:\apex\docs
'x' > C:\apex\docs\important.log; 'x' > C:\apex\docs\notes; 'x' > C:\apex\docs\photo.bak
cmd /c mklink /J "%TEMP%\apex_junction" C:\apex\docs
'x' > "$env:TEMP\apex_junk.tmp"
$lock = [IO.File]::Open("$env:TEMP\apex_locked.tmp", 'OpenOrCreate', 'ReadWrite', 'None')   # 잠긴 파일
```

- [ ] 8-1. 스캔 → 휴지통 비우기는 **기본 선택 해제**, "되돌릴 수 없음" 표시. Windows Update 다운로드 캐시·Prefetch 도 기본 해제
- [ ] 8-2. 임시 파일만 선택해 정리 → `apex_junk.tmp` 는 사라지고 **`C:\apex\docs` 의 세 파일은 그대로**, 정션도 그대로
- [ ] 8-3. 잠긴 `apex_locked.tmp` 는 건너뛰고, 그 기록이 `%APPDATA%\APEX_CARE_DATA\skipped_files.log` 에 있다.
      **바탕화면에 로그 파일이 생기지 않는다**. 결과 화면이 확보 용량(실제로 지운 파일 크기)과
      건너뛴 파일 수·용량을 보여준다. 정리 도중 다른 프로그램이 파일을 받아도 확보 용량이 0 으로 보이지 않는다
- [ ] 8-3a. 브라우저 캐시 항목 이름에 설치된 브라우저(Chrome·Edge·Whale)가 보이고, 크기가 각 브라우저의
      `%LOCALAPPDATA%\…\User Data\<Default|Profile N>\Cache·Code Cache·GPUCache` 합계와 같다. 정리 뒤에도
      브라우저의 로그인·쿠키·방문 기록·북마크는 그대로다(브라우저를 열어 확인)
- [ ] 8-4. `$lock.Close()` 로 잠금을 푼다
- [ ] 8-5. 정리 도중 창을 닫으려 하면 "진행 중" 안내가 나온다
- [ ] 8-6. 대시보드 **원클릭 최적화** → 시작 전에 확인 창이 뜨고 4단계(임시 파일·브라우저 캐시, 대기 메모리, DNS, 디스크 최적화)와
      "하지 않는 것: Windows Update 다운로드 캐시, Prefetch, 휴지통" 이 보인다. **취소** 하면 아무것도 하지 않는다
- [ ] 8-7. 원클릭을 실행해도 `C:\Windows\SoftwareDistribution\Download`·`C:\Windows\Prefetch` 의 파일 수가 그대로다
      (`(Get-ChildItem C:\Windows\Prefetch).Count` 전후 비교). 결과 화면의 단계 이름이 확인 창과 같다

---

## 9. 시작 프로그램

준비: `reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ApexTestUser /d "C:\Windows\System32\notepad.exe"` 와
`reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run /v ApexTestMachine /d "C:\Windows\System32\notepad.exe"` →
**스냅숏** `09-before`

- [ ] 9-1. 두 항목을 앱에서 끔 → **Run 값은 그대로** 남고 `Explorer\StartupApproved\Run` 에 `hex:03...` 값이 생긴다.
      작업 관리자 '시작 앱' 탭과 설정 → 앱 → 시작 프로그램에도 **사용 안 함** 으로 보인다. '변경 내역 · 되돌리기' 에 '시작 프로그램 켜기·끄기' 로 두 항목이 나온다
- [ ] 9-2. 앱에서 다시 켬 → **비교** `09-before` 와 같다(StartupApproved 값까지 원래대로)
- [ ] 9-3. 다시 끈 뒤 '변경 내역 · 되돌리기' 의 "전부 원래대로" → 두 항목이 켜지고 `09-before` 와 같다
- [ ] 9-4. 작업 관리자에서 끈 항목을 앱에서 켰다가 다시 끄면 `StartupApproved` 값이 작업 관리자가 쓴 값과 **같은 바이트** 로 돌아간다
- [ ] 9-5. 예전 버전 흉내: `reg add HKCU\Software\APEXCARE\DisabledStartup /v ApexOld /d "C:\Windows\System32\notepad.exe"` 와
      `reg add HKCU\Software\APEXCARE\DisabledStartup\_origin /v ApexOld /d "HKLM|SOFTWARE\Microsoft\Windows\CurrentVersion\Run"` →
      목록에 '예전 버전에서 끔' 으로 보인다 → 켬 → `HKLM\...\Run` 에 되살아나 켜지고 `APEXCARE` 의 기록이 사라진다
- [ ] 9-5a. 시작프로그램 폴더(`shell:startup`)에 메모장 바로 가기를 넣는다 → 목록에 '시작프로그램 폴더 (현재 사용자)' 로
      이름만(.lnk 없이) 보인다 → 끔 → **바로 가기 파일은 그대로** 있고 `Explorer\StartupApproved\StartupFolder` 에 꺼짐 값이 생긴다.
      작업 관리자 '시작 앱' 에도 사용 안 함으로 보인다 → 켬 → **비교** `09-before` 와 같다. 끝나면 바로 가기를 지운다
- [ ] 9-6. 목록에 "영향도"·"부팅 +1.4s" 같은 지어낸 수치가 없다
- [ ] 9-7. 끝나면 테스트 항목(ApexTestUser·ApexTestMachine·ApexOld)을 `reg delete` 로 지운다

---

## 10. 저장공간 (대용량·중복 파일)

준비: `fsutil file createnew C:\apex\big1.bin 600000000` → `copy C:\apex\big1.bin C:\apex\big2.bin`

- [ ] 10-1. 대용량 파일(500MB 이상)에 두 파일이 보이고, `C:\Windows`·`Program Files` 아래 파일은 나오지 않는다
- [ ] 10-2. 중복 파일에 두 파일이 한 묶음(묶음 1 · 같은 파일 2개)으로 나온다. 둘 다 고르면 "모든 사본 선택됨" 과
      삭제 확인 창의 경고가 보인다
- [ ] 10-3. `big2.bin` 삭제 → **휴지통**에 들어간다(휴지통에서 복원 가능)
- [ ] 10-4. 검사 전후로 `(Get-Item C:\apex\big1.bin).LastWriteTime` 이 같다(검사는 파일을 쓰기로 열지 않는다)
- [ ] 10-5. OneDrive 에 로그인하고 600MB 파일 두 개(같은 내용)를 OneDrive 폴더에 넣어 동기화한 뒤, 하나를
      우클릭 → **공간 확보**(구름 아이콘) → `(Get-Item 경로).Attributes` 에 `RecallOnDataAccess`(또는 `Offline`)가 보인다 →
      대용량·중복 검사 → 구름 아이콘 파일은 **목록에 없고, 내려받아지지 않는다**(아이콘 그대로, OneDrive 전송 없음).
      로컬에 있는 다른 하나는 대용량 목록에 나온다. 속성에 두 표시가 모두 없으면 이 판별이 이 Windows 에서 통하지 않는 것이니 알린다
- [ ] 10-6. 끝나면 휴지통에서 지우고 `big1.bin` 도 지운다

---

## 11. 다른 프로그램 제거와 잔여물

- [ ] 11-1. 작은 프로그램(예: 7-Zip)을 설치하고 앱의 제거 기능으로 제거 창을 띄운 뒤 **취소** → "남은 폴더 찾기" →
      "아직 설치된 프로그램 목록에 있습니다" 안내가 나오고 폴더를 찾지 않는다(설치 폴더가 그대로다)
- [ ] 11-2. 다시 제거를 끝까지 마친 뒤 "남은 폴더 찾기" → 후보는 그 프로그램의 설치 경로·정확히 같은 이름의 폴더뿐이다.
      `Microsoft`·`Common Files`·다른 회사 폴더, 다른 프로그램이 설치된 폴더가 **나오지 않는다**. 폴더마다 잡힌 이유가 보인다
- [ ] 11-3. 잔여물 정리 → 고른 폴더만 **휴지통** 으로 간다(선택을 해제한 폴더는 그대로)
- [ ] 11-4. 정션 잔여물: 명령 프롬프트에서 `mkdir %LOCALAPPDATA%\RealData`, 그 안에 아무 파일 하나,
      `mklink /J %LOCALAPPDATA%\FooLeft %LOCALAPPDATA%\RealData` → `reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FooLeft`
      에 `DisplayName=FooLeft`, `UninstallString=notepad.exe`, `InstallLocation=%LOCALAPPDATA%\FooLeft` 를 넣고 앱의 프로그램 목록을 연 뒤
      그 키를 지운다 → "남은 폴더 찾기" 에 `FooLeft` 가 **나오지 않고**, `RealData` 의 파일이 그대로다
      (자동 점검 '삭제 안전: 정션은 휴지통으로 보내지 않고…' 가 같은 것을 확인한다)

---

## 12. 시스템 복구 도구 (선택, 오래 걸림)

- [ ] 12-1. 디스크 최적화(TRIM) → 끝난 뒤에만 "완료" 가 뜬다. HDD 가 있으면 조각 모음이 5분을 넘어도 끊기지 않는다
- [ ] 12-2. SFC·DISM → 실행 중 표시, 끝나면 도구가 쓴 결과 문장(예: "무결성 위반을 찾지 못했습니다")이 한국어로 깨지지 않고
      그대로 보인다. 실패하면 실제 오류 내용이 보인다. 끝난 뒤 "다시 실행" 버튼이 있다. 도중에 창을 닫으려 하면 안내가 나온다

---

## 13. APEX CARE 제거 — 지우기 전에 바꾼 것을 되돌린다

제거 프로그램(`tools/uninstall.py`)은 설치 폴더를 지우기 전에 `APEX CARE.exe --revert-for-uninstall` 로
앱을 창 없이 불러(`backend/uninstall_prep.py`) '변경 내역 · 되돌리기'의 "전부 원래대로" 와 꺼 둔 시작 프로그램 되켜기를 한다.
결과는 `%APPDATA%\APEX_CARE_DATA\uninstall_revert.json` 에 남는다.

준비: 게이밍 모드 + 원격 분석 줄이기 적용, 9번의 테스트 시작 프로그램 두 개(HKCU·HKLM)를 앱에서 꺼 둔 상태.
`base` 에는 9번 준비의 두 테스트 항목이 없으니, 이 절은 **스냅숏** `13-base` 를 먼저 뜬다(두 항목을 추가한 직후, 적용 전).

- [ ] 13-1. APEX CARE 를 **켜 둔 채** 설정 → 앱에서 제거 → "실행 중이니 닫고 다시" 안내가 나오고 **아무것도 지우지 않는다**
      (강제 종료하지 않는다)
- [ ] 13-2. APEX CARE 를 닫고 다시 제거 → 확인 창 → 잠시 뒤 제거 완료. 설치 폴더·바로가기·앱 목록 항목이 사라진다
      (5절에서 제거한 앱이 남아 있으면, 확인 창에 "디블로터로 제거한 앱 N개는 다시 설치하지 않습니다" 가 함께 나온다)
- [ ] 13-3. **스냅숏** `13-after` → **비교** `13-base` `13-after` 가 같다. 게이밍 모드·원격 분석 정책이 되돌아가고,
      꺼 둔 두 시작 프로그램이 **원래 Run 키**(HKCU 는 HKCU, HKLM 은 HKLM)에 돌아오고, `HKCU\Software\APEXCARE` 키가 없다.
      `[APEX CARE]` 부분은 달라도 된다(`optimization_mode = standard`, 저널 항목 0개)
- [ ] 13-4. `uninstall_revert.json` 의 `success` 가 `true`, `failed` 가 빈 목록이다
- [ ] 13-5. 되돌리기 실패 경로: 재설치 → 게이밍 적용 → 앱을 닫고 `%LOCALAPPDATA%\APEX CARE\APEX CARE.exe` 이름을
      잠깐 `APEX CARE.exe.bak` 으로 바꾼다 → 제거 → "설정을 되돌리지 못했습니다" 와 함께 **기본 선택이 '아니요'** 인 질문이 뜬다 →
      Enter('아니요') → 설치 폴더가 그대로다 → 이름을 되돌리고 앱을 열면 '변경 내역 · 되돌리기'에 게이밍 모드 항목이 남아 있다
- [ ] 13-6. 서비스 `DelayedAutostart` 가 `<없음>` 에서 `0` 으로 바뀐 것만 보이면 같은 뜻(지연 시작 아님)이다. 4·5절도 같다

---

## 결과 기록

| 절 | 통과 | 실패·메모 |
|---|---|---|
| 1 설치·첫 실행 | | |
| 2 빈 '변경 내역 · 되돌리기' | | |
| 3 성능 모드 | | |
| 4 맞춤 튜닝 | | |
| 5 디블로터 | | |
| 6 게임 부스트 | | |
| 7 프로세스 | | |
| 8 정크 정리 | | |
| 9 시작 프로그램 | | |
| 10 저장공간 | | |
| 11 프로그램 제거 | | |
| 12 복구 도구 | | |
| 13 APEX CARE 제거 | | |

실패하면 그 절의 스냅숏 두 개와 비교 결과, 앱 화면 캡처를 남깁니다. 고친 뒤에는 그 부분의 pytest 테스트도 추가합니다.
