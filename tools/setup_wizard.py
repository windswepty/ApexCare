"""APEX CARE 설치 마법사.

- 관리자만 쓸 수 있는 %ProgramFiles%\\APEX CARE 에 설치한다(Setup spec uac_admin=True).
  앱은 관리자 권한으로 도는데, 사용자 쓰기 가능한 폴더에 두면 권한 없는 프로그램이
  실행 파일을 바꿔치기해 관리자 권한을 얻을 수 있다.
- 제거 정보는 HKLM(64비트 보기)에, 바로 가기는 모든 사용자의 시작 메뉴·바탕 화면에 만든다.
- 옛 %LOCALAPPDATA%\\APEX CARE 설치는 우리 파일(APEX CARE.exe, APEX CARE Uninstaller.exe),
  HKCU 제거 정보, 옛 바로 가기만 정리한다. 폴더에 다른 파일이 있으면 폴더는 남긴다.
- 각 단계의 성패를 완료 화면에 그대로 보여 준다.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
import winreg
from ctypes import wintypes

from PyQt6.QtWidgets import (QApplication, QWizard, QWizardPage, QVBoxLayout,
                             QLabel, QRadioButton, QTextEdit, QMessageBox,
                             QProgressBar, QCheckBox)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QIcon

# 버전은 여기 한 곳에서만 정한다. 'APEX CARE Setup 1.0.1.spec' 이 이 줄을 읽어
# 설치 파일 이름을 정하고 package.json 의 version 과 다르면 빌드를 멈춘다.
APP_VERSION = '1.0.1'

APP_NAME = 'APEX CARE'
PUBLISHER = 'APEX CARE Team'
APP_EXE = 'APEX CARE.exe'
UNINSTALLER_EXE = 'APEX CARE Uninstaller.exe'
PAYLOAD_EXE = 'APEX CARE Payload.exe'          # 번들 안의 이름
SHORTCUT_NAME = 'APEX CARE.lnk'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE'
PENDING_OPS_KEY = r'SYSTEM\CurrentControlSet\Control\Session Manager'

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_kernel32.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD)]
_kernel32.K32EnumProcesses.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


# ─────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────

def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _is_inside(path, root):
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip('\\') + '\\')


def program_files_dir():
    # 32비트 프로세스에서도 64비트 Program Files 를 가리킨다
    return os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'


def install_dir():
    return os.path.join(program_files_dir(), APP_NAME)


def legacy_dir():
    local = os.environ.get('LOCALAPPDATA')
    return os.path.join(local, APP_NAME) if local else None


def target_files():
    d = install_dir()
    files = [os.path.join(d, APP_EXE), os.path.join(d, UNINSTALLER_EXE)]
    ld = legacy_dir()
    if ld:
        files += [os.path.join(ld, APP_EXE), os.path.join(ld, UNINSTALLER_EXE)]
    return files


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ─────────────────────────────────────────────
# 설치 전 확인 (읽기만 한다)
# ─────────────────────────────────────────────

def _image_path(pid):
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        _kernel32.CloseHandle(h)


def running_targets(paths):
    """paths 중 지금 실행 중인 파일 경로 목록. 이름이 아니라 전체 경로로 판정한다."""
    targets = {_norm(p): p for p in paths}
    names = {os.path.basename(p).lower() for p in paths}
    count = 4096
    while True:
        arr = (wintypes.DWORD * count)()
        needed = wintypes.DWORD(0)
        if not _kernel32.K32EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            return []
        if needed.value < ctypes.sizeof(arr):
            break
        count *= 2
    found = []
    own = os.getpid()
    for i in range(needed.value // ctypes.sizeof(wintypes.DWORD)):
        pid = arr[i]
        if pid in (0, 4, own):
            continue
        img = _image_path(pid)
        if not img or os.path.basename(img).lower() not in names:
            continue
        key = _norm(img)
        if key in targets and targets[key] not in found:
            found.append(targets[key])
    return found


def pending_reboot_deletes(paths):
    """이전 제거가 '재시작 때 삭제' 로 예약해 둔 파일 중 이번에 설치할 파일. 있으면 재시작 전에는 설치하면 안 된다.
    (재시작하면 새로 설치한 파일이 지워진다)"""
    wanted = {_norm(p) for p in paths}
    hits = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PENDING_OPS_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            for value_name in ('PendingFileRenameOperations', 'PendingFileRenameOperations2'):
                try:
                    ops, _ = winreg.QueryValueEx(k, value_name)
                except FileNotFoundError:
                    continue
                if not isinstance(ops, list):
                    continue
                for i in range(0, len(ops) - 1, 2):
                    src, dst = ops[i], ops[i + 1]
                    if dst:
                        continue            # 이름 바꾸기는 상관없다. 삭제만 본다.
                    src = src[4:] if src.startswith('\\??\\') else src
                    if src.startswith('!'):
                        src = src[1:]
                    try:
                        if _norm(src) in wanted:
                            hits.append(src)
                    except Exception:
                        continue
    except OSError:
        pass
    return hits


# ─────────────────────────────────────────────
# 설치 단계
# ─────────────────────────────────────────────

def _dir_size_kb(files):
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return max(1, total // 1024)


def register_uninstall(app_path, uninstaller_path):
    """HKLM(64비트 보기)에 제거 정보를 등록하고 되읽어 확인한다. 실패하면 이유를 돌려준다."""
    folder = os.path.dirname(app_path)
    values = {
        'DisplayName': (winreg.REG_SZ, APP_NAME),
        'DisplayVersion': (winreg.REG_SZ, APP_VERSION),
        'Publisher': (winreg.REG_SZ, PUBLISHER),
        'InstallLocation': (winreg.REG_SZ, folder),
        'DisplayIcon': (winreg.REG_SZ, app_path),
        'UninstallString': (winreg.REG_SZ, f'"{uninstaller_path}"'),
        'InstallDate': (winreg.REG_SZ, time.strftime('%Y%m%d')),
        'EstimatedSize': (winreg.REG_DWORD, _dir_size_kb([app_path, uninstaller_path])),
        'NoModify': (winreg.REG_DWORD, 1),
        'NoRepair': (winreg.REG_DWORD, 1),
    }
    access = winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
    try:
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, access) as k:
            for name, (vtype, data) in values.items():
                winreg.SetValueEx(k, name, 0, vtype, data)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            for name, (_vtype, data) in values.items():
                got, _ = winreg.QueryValueEx(k, name)
                if got != data:
                    return f'{name} 값이 기록되지 않았습니다.'
        return None
    except OSError as e:
        return str(e)


def create_shortcut(shell, folder, target):
    """바로 가기를 만들고 파일이 생겼는지 확인한다. 실패하면 이유를 돌려준다."""
    try:
        if not folder or not os.path.isdir(folder):
            return f'폴더가 없습니다: {folder}'
        path = os.path.join(folder, SHORTCUT_NAME)
        sc = shell.CreateShortCut(path)
        sc.TargetPath = target
        sc.WorkingDirectory = os.path.dirname(target)
        sc.IconLocation = f'{target},0'
        sc.Description = APP_NAME
        sc.save()
        if not os.path.isfile(path):
            return '바로 가기 파일이 만들어지지 않았습니다.'
        return None
    except Exception as e:
        return str(e)


def cleanup_legacy(shell):
    """옛 %LOCALAPPDATA%\\APEX CARE 설치를 정리한다. [(성공 여부, 설명)] 을 돌려준다."""
    ld = legacy_dir()
    if not ld or _norm(ld) == _norm(install_dir()):
        return []
    results = []

    # HKCU 제거 정보는 InstallLocation 이 옛 폴더일 때만 대상이다(정션을 거친 경로도 풀어서 비교)
    key_matches = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_READ) as k:
            loc, _ = winreg.QueryValueEx(k, 'InstallLocation')
            key_matches = bool(loc) and _norm(loc) == _norm(ld)
    except OSError:
        key_matches = False

    has_files = os.path.isdir(ld)
    if not has_files and not key_matches:
        return []

    removed, failed = [], []
    if has_files:
        for name in (APP_EXE, UNINSTALLER_EXE):
            p = os.path.join(ld, name)
            if not os.path.isfile(p):
                continue
            try:
                os.remove(p)
                removed.append(name)
            except OSError as e:
                failed.append(f'{name}: {e}')
    if removed:
        results.append((True, f"이전 설치의 {', '.join(removed)} 를 지웠습니다."))
    for f in failed:
        results.append((False, f'이전 설치 파일을 지우지 못했습니다 — {f}'))

    # 옛 바로 가기(대상이 옛 폴더인 것만)
    sc_removed = 0
    if shell is None:
        results.append((False, '이전 바로 가기가 있는지 확인하지 못했습니다.'))
    for special in (('Desktop', 'Programs') if shell is not None else ()):
        try:
            folder = shell.SpecialFolders(special)
            path = os.path.join(folder, SHORTCUT_NAME)
            if os.path.isfile(path):
                target = shell.CreateShortCut(path).TargetPath
                if target and _is_inside(target, ld):
                    os.remove(path)
                    sc_removed += 1
        except Exception as e:
            results.append((False, f'이전 바로 가기를 지우지 못했습니다 — {e}'))
    if sc_removed:
        results.append((True, f'이전 바로 가기 {sc_removed}개를 지웠습니다.'))

    # 우리 파일을 다 지웠을 때만 옛 제거 정보를 지운다(남은 파일을 가리키는 항목을 없애지 않는다)
    if key_matches:
        if failed:
            results.append((False, "이전 설치 파일이 남아 있어 이전 '앱 및 기능' 항목은 남겨 두었습니다."))
        else:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
                results.append((True, "이전 설치의 '앱 및 기능' 항목을 지웠습니다."))
            except OSError as e:
                results.append((False, f"이전 '앱 및 기능' 항목을 지우지 못했습니다 — {e}"))

    # 폴더는 비어 있을 때만 지운다
    if has_files:
        try:
            rest = os.listdir(ld)
        except OSError:
            rest = None
        if rest == []:
            try:
                os.rmdir(ld)
            except OSError:
                pass
        elif rest:
            shown = ', '.join(rest[:4]) + (' 등' if len(rest) > 4 else '')
            results.append((True, f'이전 설치 폴더에 다른 파일({shown})이 있어 폴더는 남겨 두었습니다: {ld}'))
    return results


class InstallWorker(QThread):
    progress_update = pyqtSignal(int)
    status_update = pyqtSignal(str)
    finished_install = pyqtSignal(dict)

    def __init__(self, resource_path_func, want_desktop):
        super().__init__()
        self.resource_path_func = resource_path_func
        self.want_desktop = want_desktop

    def _fail(self, message, steps):
        self.finished_install.emit({'ok': False, 'error': message, 'steps': steps})

    def run(self):
        steps = []          # (성공 여부, 설명)
        try:
            payload = self.resource_path_func(PAYLOAD_EXE)
            uninstaller = self.resource_path_func(UNINSTALLER_EXE)
            missing = [os.path.basename(p) for p in (payload, uninstaller) if not os.path.isfile(p)]
            if missing:
                # 제거 프로그램 없이 설치하면 정상적으로 지울 방법이 없다
                return self._fail(f"설치 패키지에 {', '.join(missing)} 가 없습니다.", steps)

            folder = install_dir()
            app_path = os.path.join(folder, APP_EXE)
            un_path = os.path.join(folder, UNINSTALLER_EXE)

            self.status_update.emit('파일을 복사하는 중…')
            self.progress_update.emit(10)
            created_dir = not os.path.isdir(folder)
            os.makedirs(folder, exist_ok=True)

            # 새 이름으로 먼저 다 복사하고 크기를 확인한 뒤에 바꿔 넣는다.
            # 중간에 실패하면 기존 설치는 그대로 남는다.
            pairs = [(payload, app_path), (uninstaller, un_path)]
            staged, placed = [], []
            try:
                for src, dst in pairs:
                    tmp = dst + '.new'
                    shutil.copyfile(src, tmp)
                    staged.append(tmp)
                    if os.path.getsize(tmp) != os.path.getsize(src):
                        raise OSError(f'{os.path.basename(dst)} 복사본 크기가 다릅니다.')
                self.progress_update.emit(40)
                for src, dst in pairs:
                    existed = os.path.exists(dst)
                    os.replace(dst + '.new', dst)
                    if not existed:
                        placed.append(dst)
            except OSError as e:
                # 이번에 새로 놓은 파일과 복사본만 치운다. 원래 있던 설치 파일은 건드리지 않는다.
                for tmp in staged + placed:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except OSError:
                        pass
                if created_dir:
                    try:
                        os.rmdir(folder)
                    except OSError:
                        pass
                return self._fail(f'파일을 복사하지 못했습니다: {e}', steps)
            steps.append((True, f'프로그램을 설치했습니다: {folder}'))
            self.progress_update.emit(55)

            self.status_update.emit('제거 정보를 등록하는 중…')
            err = register_uninstall(app_path, un_path)
            if err:
                steps.append((False, f"'앱 및 기능' 에 등록하지 못했습니다 — {err}\n"
                                     f'  제거할 때는 {un_path} 를 실행하세요.'))
            else:
                steps.append((True, "'앱 및 기능' 에 등록했습니다."))
            self.progress_update.emit(70)

            self.status_update.emit('바로 가기를 만드는 중…')
            shell = None
            com_ready = False
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()          # 작업 스레드에서 COM 을 쓰려면 필요하다
                com_ready = True
                shell = win32com.client.Dispatch('WScript.Shell')
            except Exception as e:
                steps.append((False, f'바로 가기를 만들 수 없습니다 — {e}'))

            try:
                if shell is not None:
                    err = create_shortcut(shell, shell.SpecialFolders('AllUsersPrograms'), app_path)
                    steps.append((err is None, '시작 메뉴에 바로 가기를 만들었습니다.' if err is None
                                  else f'시작 메뉴 바로 가기를 만들지 못했습니다 — {err}'))
                    if self.want_desktop:
                        err = create_shortcut(shell, shell.SpecialFolders('AllUsersDesktop'), app_path)
                        steps.append((err is None, '바탕 화면에 바로 가기를 만들었습니다.' if err is None
                                      else f'바탕 화면 바로 가기를 만들지 못했습니다 — {err}'))
                self.progress_update.emit(85)

                self.status_update.emit('이전 설치를 정리하는 중…')
                steps.extend(cleanup_legacy(shell))
            finally:
                shell = None
                if com_ready:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

            self.progress_update.emit(100)
            self.finished_install.emit({'ok': True, 'error': None, 'steps': steps,
                                        'installed_path': app_path})
        except Exception as e:
            self._fail(f'설치 중 오류가 났습니다: {e}', steps)


# ─────────────────────────────────────────────
# 화면
# ─────────────────────────────────────────────

class LicensePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("사용권 계약")
        self.setSubTitle("소프트웨어를 설치하기 전에 사용권 계약서를 주의 깊게 읽어보시기 바랍니다.")

        layout = QVBoxLayout(self)
        desc = QLabel("아래의 사용권 계약에 동의하십니까? 동의하신다면 '동의함'을 선택하십시오.\n프로그램을 설치하려면 반드시 사용권 계약에 동의해야 합니다.")
        layout.addWidget(desc)

        self.eula_box = QTextEdit()
        self.eula_box.setReadOnly(True)
        self.eula_box.setStyleSheet("background-color: white; color: black; font-family: 'Malgun Gothic', sans-serif;")
        layout.addWidget(self.eula_box)

        self.radio_accept = QRadioButton("사용권 계약의 조항에 동의합니다(&A)")
        self.radio_reject = QRadioButton("사용권 계약의 조항에 동의하지 않습니다(&D)")
        self.radio_reject.setChecked(True)

        layout.addWidget(self.radio_accept)
        layout.addWidget(self.radio_reject)

        self.radio_accept.toggled.connect(self.completeChanged)

    def isComplete(self):
        return self.radio_accept.isChecked()


class ReadyPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("설치 준비 완료")
        self.setSubTitle("컴퓨터에 APEX CARE 설치를 시작할 준비가 되었습니다.")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("계속하려면 [다음]을 클릭하십시오. 설정을 검토하거나 변경하려면 [뒤로]를 클릭하십시오."))
        layout.addWidget(QLabel(f"\n대상 위치:\n{install_dir()}\n\n시작 메뉴에 바로 가기를 만듭니다."))

        self.chk_desktop = QCheckBox("바탕 화면에 바로 가기 만들기")
        self.chk_desktop.setChecked(True)
        layout.addWidget(self.chk_desktop)

    def validatePage(self):
        """설치를 시작하기 전에 확인한다. 문제가 있으면 이 화면에 머문다."""
        pending = pending_reboot_deletes(target_files()[:2])
        if pending:
            QMessageBox.warning(
                self, "설치할 수 없음",
                "이전 제거 작업이 PC 재시작을 기다리고 있습니다.\n"
                "지금 설치하면 재시작할 때 새로 설치한 파일이 지워집니다.\n\n"
                "PC 를 다시 시작한 뒤 설치해 주세요.")
            return False
        running = running_targets(target_files())
        if running:
            QMessageBox.warning(
                self, "APEX CARE 가 실행 중입니다",
                "APEX CARE 가 실행 중이라 파일을 바꿀 수 없습니다.\n"
                "APEX CARE 창을 닫은 뒤 [다음]을 다시 눌러 주세요.\n\n" + '\n'.join(running))
            return False
        return True


class ProgressPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("설치 중")
        self.setSubTitle("컴퓨터에 APEX CARE를 설치하는 중입니다. 잠시만 기다려 주십시오.")

        layout = QVBoxLayout(self)
        self.lbl_status = QLabel("설치를 준비하는 중…")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.is_done = False
        self.worker = None

    def isComplete(self):
        return self.is_done

    def initializePage(self):
        # 파일을 바꾸는 중에는 취소·뒤로 가기를 막는다
        self.wizard().setButtonLayout([QWizard.WizardButton.Stretch])
        self.worker = InstallWorker(self.wizard().resource_path,
                                    self.wizard().ready_page.chk_desktop.isChecked())
        self.worker.progress_update.connect(self.progress.setValue)
        self.worker.status_update.connect(self.lbl_status.setText)
        self.worker.finished_install.connect(self.on_install_finished)
        self.worker.start()

    def on_install_finished(self, result):
        if self.worker is not None:
            self.worker.wait()                 # 스레드가 끝나야 창을 닫거나 넘어갈 수 있다
        if result.get('ok'):
            self.wizard().installed_path = result.get('installed_path', '')
            self.wizard().install_steps = result.get('steps', [])
            self.lbl_status.setText("설치가 끝났습니다.")
            self.is_done = True
            self.completeChanged.emit()
            self.wizard().next()
        else:
            self.lbl_status.setText("설치하지 못했습니다.")
            QMessageBox.critical(self, "설치 오류", f"설치하지 못했습니다.\n\n{result.get('error')}")
            self.wizard().reject()


class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("APEX CARE 설치 마법사 완료")

        layout = QVBoxLayout(self)
        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

        self.chk_run = QCheckBox("APEX CARE 실행하기")
        self.chk_run.setChecked(True)
        layout.addWidget(self.chk_run)

    def initializePage(self):
        wiz = self.wizard()
        wiz.setButtonLayout([QWizard.WizardButton.Stretch, QWizard.WizardButton.FinishButton])
        steps = getattr(wiz, 'install_steps', [])
        failed = [text for ok, text in steps if not ok]
        if failed:
            self.setSubTitle("설치는 끝났지만 일부 단계가 실패했습니다.")
        else:
            self.setSubTitle("컴퓨터에 APEX CARE 를 설치했습니다.")
        lines = [f"{'완료' if ok else '실패'} · {text}" for ok, text in steps]
        lines.append("\n마법사를 닫으려면 [종료]를 클릭하십시오.")
        self.lbl_result.setText('\n'.join(lines))
        self.chk_run.setEnabled(bool(wiz.installed_path) and os.path.isfile(wiz.installed_path))


class SetupWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"설치 - APEX CARE {APP_VERSION}")
        self.setWindowIcon(QIcon(self.resource_path("setup_icon.ico")))
        self.setFixedSize(560, 440)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        self.installed_path = ""
        self.install_steps = []

        self.license_page = LicensePage()
        self.ready_page = ReadyPage()
        self.progress_page = ProgressPage()
        self.finish_page = FinishPage()

        self.addPage(self.license_page)
        self.addPage(self.ready_page)
        self.addPage(self.progress_page)
        self.addPage(self.finish_page)

        self.setButtonText(QWizard.WizardButton.BackButton, "< 뒤로(&B)")
        self.setButtonText(QWizard.WizardButton.NextButton, "다음(&N) >")
        self.setButtonText(QWizard.WizardButton.CancelButton, "취소")
        self.setButtonText(QWizard.WizardButton.FinishButton, "종료(&F)")

        self.load_eula()
        self.finished.connect(self.on_finished)

    def load_eula(self):
        eula_path = self.resource_path("eula.txt")
        if os.path.exists(eula_path):
            with open(eula_path, "r", encoding="utf-8") as f:
                self.license_page.eula_box.setText(f.read())
        else:
            self.license_page.eula_box.setText("EULA 파일을 찾을 수 없습니다.")

    def reject(self):
        # 파일을 바꾸는 중에는 창 닫기·Esc 로 끊지 않는다
        worker = self.progress_page.worker
        if worker is not None and worker.isRunning():
            return
        super().reject()

    def resource_path(self, relative_path):
        base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
        return os.path.join(base_path, relative_path)

    def on_finished(self, result):
        if result != 1 or not self.installed_path:
            return
        if self.finish_page.chk_run.isChecked() and self.finish_page.chk_run.isEnabled():
            try:
                subprocess.Popen([self.installed_path], cwd=os.path.dirname(self.installed_path),
                                 shell=False, close_fds=True)
            except OSError as e:
                QMessageBox.warning(None, "실행 실패", f"APEX CARE 를 실행하지 못했습니다.\n{e}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("windowsvista")
    if not is_admin():
        QMessageBox.critical(None, "설치 - APEX CARE",
                             "관리자 권한이 필요합니다.\n설치 파일을 다시 실행하고 사용자 계정 컨트롤 창에서 [예]를 눌러 주세요.")
        sys.exit(1)
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())
