import sys
import os
import shutil
import subprocess
from PyQt6.QtWidgets import (QApplication, QWizard, QWizardPage, QVBoxLayout, 
                             QLabel, QRadioButton, QTextEdit, QMessageBox, 
                             QProgressBar, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

# 버전은 여기 한 곳에서 정한다. 'APEX CARE Setup 1.0.1.spec' 이 이 줄을 읽어 설치 파일 이름을 짓고,
# package.json 의 version 과 다르면 빌드를 멈춘다.
APP_VERSION = '1.0.1'

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE"
APP_EXE = "APEX CARE.exe"
UNINSTALLER_EXE = "APEX CARE Uninstaller.exe"
CREATE_NO_WINDOW = 0x08000000


def install_dir():
    """설치 위치: %ProgramFiles%\\APEX CARE (모든 사용자).

    APEX CARE 는 실행할 때마다 관리자 권한으로 돈다. 예전에는 일반 권한 프로그램도 쓸 수 있는 %LOCALAPPDATA% 에
    설치해, 악성 프로그램이 exe 를 바꿔치기하면 사용자가 다음에 UAC 를 누를 때 관리자 권한을 얻을 수 있었다.
    Program Files 는 관리자만 쓸 수 있다.
    """
    base = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return os.path.join(base, "APEX CARE")


def legacy_install_dir():
    """예전 버전(1.0.1 이전 빌드)이 설치하던 사용자 폴더."""
    local = os.environ.get("LOCALAPPDATA")
    return os.path.join(local, "APEX CARE") if local else ""


def _system32(name):
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(root, "System32", name)


def app_running():
    """APEX CARE 가 실행 중인지. 확인하지 못하면 실행 중으로 본다(안전 쪽)."""
    try:
        r = subprocess.run([_system32("tasklist.exe"), "/FI", f"IMAGENAME eq {APP_EXE}", "/FO", "CSV", "/NH"],
                           shell=False, capture_output=True, text=True, errors="replace",
                           creationflags=CREATE_NO_WINDOW, timeout=30)
    except Exception:
        return True
    if r.returncode != 0:
        return True
    return f'"{APP_EXE.lower()}"' in (r.stdout or "").lower()


def copy_with_progress(src, dst, on_bytes):
    """src 를 dst 로 복사한다. 옆에 임시 파일로 다 쓴 뒤 바꿔 끼워, 도중에 실패해도 반쯤 쓴 exe 가 남지 않는다.

    on_bytes(복사한 바이트, 전체 바이트) 를 실제로 쓴 만큼 부른다(진행률은 이 값으로만 움직인다).
    """
    total = os.path.getsize(src)
    tmp = dst + ".new"
    done = 0
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                chunk = fi.read(1 << 20)
                if not chunk:
                    break
                fo.write(chunk)
                done += len(chunk)
                on_bytes(done, total)
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)                  # 이 함수가 만든 임시 파일만 지운다
    return total


def register_uninstall(install_dir, app_exe, size_bytes):
    """'앱 및 기능' 에 모든 사용자용으로 등록한다(HKLM, 64비트 보기). 실패하면 예외를 올린다
    (등록 없이 '설치 완료' 라고 하지 않는다)."""
    import winreg
    uninstaller_exe = os.path.join(install_dir, UNINSTALLER_EXE)
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "APEX CARE")
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_exe}"')
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, app_exe)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "APEX CARE Team")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, max(1, size_bytes // 1024))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _shortcut_target(lnk):
    try:
        import win32com.client
        return win32com.client.Dispatch("WScript.Shell").CreateShortCut(lnk).Targetpath or ""
    except Exception:
        return ""


def remove_legacy_install(new_dir):
    """예전 버전이 사용자 폴더에 설치한 것을 정리한다. 남겨 두면 그 exe 가 여전히 바꿔치기 대상이다.

    그 폴더의 우리 exe 두 개, 그 폴더를 가리키는 프로그램 목록 항목(HKCU)과 바로 가기만 지운다.
    폴더는 비었을 때만 지운다. 설정·변경 기록(%APPDATA%\\APEX_CARE_DATA)은 그대로 이어 쓴다.
    반환: 지우지 못한 것의 설명 목록.
    """
    import winreg
    old = legacy_install_dir()
    problems = []
    if not old or os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(new_dir)):
        return problems
    if os.path.isdir(old) and not os.path.islink(old):
        for name in (APP_EXE, UNINSTALLER_EXE):
            path = os.path.join(old, name)
            if os.path.isfile(path) and not os.path.islink(path):
                try:
                    os.remove(path)                       # 우리 프로그램 파일만 지운다
                except OSError as e:
                    problems.append(f"{path}: {e}")
        try:
            os.rmdir(old)                                 # 비었을 때만 지워진다
        except OSError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            loc = winreg.QueryValueEx(k, "InstallLocation")[0]
        if os.path.normcase(os.path.abspath(str(loc))) == os.path.normcase(os.path.abspath(old)):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except OSError as e:
        problems.append(f"예전 프로그램 목록 항목: {e}")
    old_exe = os.path.normcase(os.path.join(old, APP_EXE))
    for desk in _user_desktops():
        lnk = os.path.join(desk, "APEX CARE.lnk")
        if os.path.isfile(lnk) and os.path.normcase(_shortcut_target(lnk)) == old_exe:
            try:
                os.remove(lnk)                            # 예전 위치를 가리키는 우리 바로 가기만
            except OSError as e:
                problems.append(f"{lnk}: {e}")
    return problems


def _user_desktops():
    out = []
    try:
        import win32com.client
        out.append(win32com.client.Dispatch("WScript.Shell").SpecialFolders("Desktop"))
    except Exception:
        pass
    out.append(os.path.join(os.path.expanduser("~"), "OneDrive", "바탕 화면"))
    out.append(os.path.join(os.path.expanduser("~"), "Desktop"))
    return [d for d in dict.fromkeys(out) if d]


class InstallWorker(QThread):
    progress_update = pyqtSignal(int)
    finished_install = pyqtSignal(bool, str)

    def __init__(self, resource_path_func):
        super().__init__()
        self.resource_path_func = resource_path_func

    def run(self):
        # 진행률은 실제로 복사한 바이트로만 움직인다. 예전에는 '그럴듯해 보이게' 일부러 잠깐씩 멈추며 막대를 채웠다.
        try:
            payload_path = self.resource_path_func("APEX CARE Payload.exe")
            uninstaller_path = self.resource_path_func("APEX CARE Uninstaller.exe")
            # 제거 프로그램이 없으면 설치하지 않는다. 예전에는 조용히 건너뛰어, 지울 방법이 없는 설치가 됐다.
            missing = [os.path.basename(p) for p in (payload_path, uninstaller_path) if not os.path.exists(p)]
            if missing:
                self.finished_install.emit(False, f"설치 패키지가 손상되었습니다(없는 파일: {', '.join(missing)}).")
                return

            if app_running():
                self.finished_install.emit(False, "APEX CARE 가 실행 중입니다(또는 실행 여부를 확인하지 못했습니다).\n"
                                                  "APEX CARE 창을 닫은 뒤 다시 설치해 주세요.")
                return
            target_dir = install_dir()
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, APP_EXE)
            uninst_target = os.path.join(target_dir, UNINSTALLER_EXE)

            sizes = [os.path.getsize(payload_path), os.path.getsize(uninstaller_path)]
            grand = sum(sizes) or 1

            def report(offset):
                return lambda done, _total: self.progress_update.emit(min(95, int((offset + done) * 95 / grand)))

            try:
                copy_with_progress(payload_path, target_path, report(0))
                copy_with_progress(uninstaller_path, uninst_target, report(sizes[0]))
            except PermissionError:
                self.finished_install.emit(False, "APEX CARE 가 실행 중이라 파일을 바꿀 수 없습니다.\n"
                                                  "APEX CARE 창을 닫은 뒤 다시 설치해 주세요.")
                return

            try:
                register_uninstall(target_dir, target_path, sum(sizes))
            except OSError as e:
                self.finished_install.emit(False, f"'앱 및 기능' 에 등록하지 못했습니다: {e}\n"
                                                  "파일은 복사됐지만 제거 목록에 나오지 않습니다. 다시 설치해 주세요.")
                return
            self.legacy_problems = remove_legacy_install(target_dir)
            self.progress_update.emit(100)
            self.finished_install.emit(True, target_path)
        except Exception as e:
            self.finished_install.emit(False, str(e) or type(e).__name__)


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
        desc = QLabel("계속하려면 [설치]를 클릭하십시오. 설정을 검토하거나 변경하려면 [뒤로]를 클릭하십시오.")
        layout.addWidget(desc)
        
        info = QLabel(f"\n대상 위치:\n{install_dir()} (이 PC 의 모든 사용자)\n\n"
                      "예전 버전이 사용자 폴더(AppData\\Local\\APEX CARE)에 설치돼 있으면 그 프로그램 파일은 정리하고,\n"
                      "설정과 변경 기록은 그대로 이어 씁니다.")
        info.setWordWrap(True)
        layout.addWidget(info)

class ProgressPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("설치 중")
        self.setSubTitle("컴퓨터에 APEX CARE를 설치하는 중입니다. 잠시만 기다려 주십시오.")
        
        layout = QVBoxLayout(self)
        self.lbl_status = QLabel("파일을 복사하는 중...")
        layout.addWidget(self.lbl_status)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
        self.is_done = False
        
    def isComplete(self):
        return self.is_done
        
    def initializePage(self):
        # 복사하는 동안에는 취소를 받지 않는다. 예전에는 '취소'·Esc·창 닫기가 복사 스레드를 기다리지 않고 끝내,
        # 반쯤 복사된 파일과 제거 목록에 없는 설치가 남았다.
        self.wizard().setButtonLayout([QWizard.WizardButton.Stretch])
        
        self.worker = InstallWorker(self.wizard().resource_path)
        self.worker.progress_update.connect(self.progress.setValue)
        self.worker.finished_install.connect(self.on_install_finished)
        self.worker.start()
        
    def on_install_finished(self, success, path_or_err):
        if success:
            self.wizard().installed_path = path_or_err
            self.lbl_status.setText("설치가 완료되었습니다.")
            self.is_done = True
            self.completeChanged.emit()
            self.wizard().next() # Auto proceed to finish page
        else:
            self.lbl_status.setText("설치 실패.")
            QMessageBox.critical(self, "설치 오류", f"설치 중 오류가 발생했습니다:\n{path_or_err}")
            self.wizard().reject()

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("APEX CARE 설치 마법사 완료")
        self.setSubTitle("컴퓨터에 프로그램 설치를 성공적으로 완료했습니다.")
        
        layout = QVBoxLayout(self)
        desc = QLabel("컴퓨터에 APEX CARE 설치가 완료되었습니다.\n마법사를 닫으려면 [종료]를 클릭하십시오.")
        layout.addWidget(desc)
        
        self.chk_shortcut = QCheckBox("바탕 화면에 바로 가기 만들기")
        self.chk_shortcut.setChecked(True)
        layout.addWidget(self.chk_shortcut)
        
        self.chk_run = QCheckBox("APEX CARE 실행하기")
        self.chk_run.setChecked(True)
        layout.addWidget(self.chk_run)
        
    def initializePage(self):
        self.wizard().setButtonLayout(
            [QWizard.WizardButton.Stretch, QWizard.WizardButton.FinishButton]
        )

class SetupWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("설치 - APEX CARE")
        self.setWindowIcon(QIcon(self.resource_path("setup_icon.ico")))
        self.setFixedSize(500, 380)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        
        self.installed_path = ""
        
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

    def _copying(self):
        w = getattr(self.progress_page, "worker", None)
        return bool(w is not None and w.isRunning())

    def reject(self):
        if self._copying():
            return                                 # 설치를 마칠 때까지 닫지 않는다(Esc 포함)
        super().reject()

    def closeEvent(self, event):
        if self._copying():
            event.ignore()
            QMessageBox.information(self, "설치 중", "설치를 마칠 때까지 기다려 주세요.")
            return
        super().closeEvent(event)

    def load_eula(self):
        eula_path = self.resource_path("eula.txt")
        if os.path.exists(eula_path):
            with open(eula_path, "r", encoding="utf-8") as f:
                self.license_page.eula_box.setText(f.read())
        else:
            self.license_page.eula_box.setText("EULA 파일을 찾을 수 없습니다.")

    def resource_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def on_finished(self, result):
        # '앱 및 기능' 등록은 설치 단계(InstallWorker)에서 이미 끝났다. 실패했으면 완료 화면까지 오지 않는다.
        if result == 1 and self.installed_path: # Accepted/Finished
            if not self.create_shortcut("AllUsersPrograms"):
                QMessageBox.warning(self, "바로 가기", "시작 메뉴에 바로 가기를 만들지 못했습니다.\n"
                                    f"APEX CARE 는 설치되었습니다: {self.installed_path}")
            if self.finish_page.chk_shortcut.isChecked() and not self.create_shortcut("AllUsersDesktop"):
                QMessageBox.warning(self, "바로 가기", "바탕 화면에 바로 가기를 만들지 못했습니다.\n"
                                    f"APEX CARE 는 설치되었습니다: {self.installed_path}")
            legacy = getattr(self.progress_page.worker, "legacy_problems", None) or []
            if legacy:
                QMessageBox.warning(self, "예전 버전 정리", "예전 버전(사용자 폴더 설치)의 일부를 정리하지 못했습니다.\n"
                                    "새 버전은 설치되었습니다. 아래 항목은 직접 지워 주세요:\n" + "\n".join(legacy[:5]))
            if self.finish_page.chk_run.isChecked():
                try:
                    os.startfile(self.installed_path)
                except OSError:
                    pass                     # 관리자 권한 확인 창에서 '아니요' 를 눌렀다. 설치는 끝났다.

    def create_shortcut(self, folder):
        """모든 사용자용 바로 가기를 만든다(folder: 'AllUsersPrograms' 시작 메뉴, 'AllUsersDesktop' 공용 바탕 화면).

        모든 사용자용으로 만든다. 표준 사용자가 관리자 암호로 설치하면 설치 프로그램은 관리자 계정으로 돌아서,
        예전처럼 '현재 사용자' 바탕 화면에 만들면 정작 설치한 사람에게는 바로 가기가 보이지 않았다.
        """
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            base = shell.SpecialFolders(folder)
            if not base or not os.path.isdir(base):
                return False
            shortcut_path = os.path.join(base, "APEX CARE.lnk")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = self.installed_path
            shortcut.WorkingDirectory = os.path.dirname(self.installed_path)
            shortcut.save()
            return os.path.exists(shortcut_path)
        except Exception:
            return False

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("windowsvista")
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())
