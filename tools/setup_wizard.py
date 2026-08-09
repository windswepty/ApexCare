import sys
import os
import shutil
import time
from PyQt6.QtWidgets import (QApplication, QWizard, QWizardPage, QVBoxLayout, 
                             QLabel, QRadioButton, QTextEdit, QMessageBox, 
                             QProgressBar, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

class InstallWorker(QThread):
    progress_update = pyqtSignal(int)
    finished_install = pyqtSignal(bool, str)

    def __init__(self, resource_path_func):
        super().__init__()
        self.resource_path_func = resource_path_func

    def run(self):
        try:
            # Simulate some progress for realism
            for i in range(1, 40):
                time.sleep(0.02)
                self.progress_update.emit(i)
                
            payload_path = self.resource_path_func("APEX CARE Payload.exe")
            uninstaller_path = self.resource_path_func("APEX CARE Uninstaller.exe")
            if not os.path.exists(payload_path):
                self.finished_install.emit(False, "설치 패키지를 찾을 수 없습니다!")
                return

            install_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "APEX CARE")
            if not os.path.exists(install_dir):
                os.makedirs(install_dir)
                
            for i in range(40, 70):
                time.sleep(0.02)
                self.progress_update.emit(i)

            target_path = os.path.join(install_dir, "APEX CARE.exe")
            shutil.copy2(payload_path, target_path)
            
            if os.path.exists(uninstaller_path):
                shutil.copy2(uninstaller_path, os.path.join(install_dir, "APEX CARE Uninstaller.exe"))
            
            for i in range(70, 101):
                time.sleep(0.01)
                self.progress_update.emit(i)
                
            self.finished_install.emit(True, target_path)
        except Exception as e:
            self.finished_install.emit(False, str(e))


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
        
        info = QLabel("\n대상 위치:\n사용자 로컬 앱 데이터 폴더 (AppData\\Local\\APEX CARE)\n\n설치 마법사가 APEX CARE를 설치합니다.")
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
        self.wizard().setButtonLayout(
            [QWizard.WizardButton.Stretch, QWizard.WizardButton.CancelButton]
        ) # Hide back/next buttons during progress
        
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
        if result == 1 and self.installed_path: # Accepted/Finished
            self.register_uninstall()
            if self.finish_page.chk_shortcut.isChecked():
                self.create_shortcut()
            if self.finish_page.chk_run.isChecked():
                os.startfile(self.installed_path)

    def register_uninstall(self):
        try:
            import winreg
            install_dir = os.path.dirname(self.installed_path)
            uninstaller_exe = os.path.join(install_dir, "APEX CARE Uninstaller.exe")
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "APEX CARE")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_exe}"')
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, self.installed_path)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "APEX CARE Team")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.2")
            winreg.CloseKey(key)
        except Exception:
            pass

    def create_shortcut(self):
        try:
            import win32com.client
            desktop_path = None
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
                val, _ = winreg.QueryValueEx(key, "Desktop")
                winreg.CloseKey(key)
                desktop_path = os.path.expandvars(val)
            except Exception:
                pass
                
            if not desktop_path or not os.path.exists(desktop_path):
                desktop_path = os.path.join(os.path.expanduser("~"), "OneDrive", "바탕 화면")
            if not os.path.exists(desktop_path):
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            
            shortcut_path = os.path.join(desktop_path, "APEX CARE.lnk")
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = self.installed_path
            shortcut.WorkingDirectory = os.path.dirname(self.installed_path)
            shortcut.save()
        except Exception:
            pass

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("windowsvista")
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec())
