import json
import os
import subprocess
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
import win32com.client

CREATE_NO_WINDOW = 0x08000000
APP_EXE = "APEX CARE.exe"
REVERT_TIMEOUT_SEC = 300
# backend/uninstall_prep.py 의 RESULT_NAME 과 같아야 한다
RESULT_PATH = os.path.join(os.environ.get("APPDATA", ""), "APEX_CARE_DATA", "uninstall_revert.json")


def _message(icon, title, text, buttons=QMessageBox.StandardButton.Ok,
             default=QMessageBox.StandardButton.Ok):
    box = QMessageBox()
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    box.setDefaultButton(default)
    return box.exec()


def _system32(name):
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(root, "System32", name)


def _app_running():
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


def _revert_system_changes(install_dir):
    """앱을 되돌리기 모드로 불러 이 앱이 바꾼 설정을 원래대로 돌린다.

    (성공 여부, 사용자에게 보여줄 실패 설명) 을 돌려준다.
    되돌리는 코드는 앱(backend/uninstall_prep.py)에 있다. 제거 프로그램에 따로 짜 두면 두 구현이 어긋난다.
    """
    exe = os.path.join(install_dir, APP_EXE)
    if not os.path.isfile(exe):
        return False, f"{APP_EXE} 가 없어 설정을 되돌리지 못했습니다."
    try:
        os.remove(RESULT_PATH)             # 지난번 결과를 이번 결과로 착각하지 않게
    except FileNotFoundError:
        pass
    except OSError as e:
        return False, f"이전 결과 파일을 지우지 못했습니다: {e}"

    try:
        r = subprocess.run([exe, "--revert-for-uninstall"], shell=False,
                           creationflags=CREATE_NO_WINDOW, timeout=REVERT_TIMEOUT_SEC)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return False, f"설정 되돌리기가 {REVERT_TIMEOUT_SEC}초 안에 끝나지 않았습니다."
    except Exception as e:
        return False, f"설정 되돌리기를 시작하지 못했습니다: {e}"

    try:
        with open(RESULT_PATH, encoding="utf-8") as f:
            res = json.load(f)
    except Exception:
        return False, f"설정 되돌리기 결과를 읽지 못했습니다 (종료 코드 {rc})."

    if rc == 0 and res.get("success"):
        return True, ""
    failed = res.get("failed") or []
    lines = [f"- {f.get('name', '?')}: {f.get('detail', '')}".rstrip(": ") for f in failed[:10]]
    if len(failed) > 10:
        lines.append(f"- 외 {len(failed) - 10}개")
    return False, "되돌리지 못한 항목:\n" + ("\n".join(lines) if lines else f"(종료 코드 {rc})")


def main():
    app = QApplication(sys.argv)

    if _message(QMessageBox.Icon.Warning, "APEX CARE 삭제",
                "APEX CARE 프로그램을 완전히 삭제하시겠습니까?\n\n"
                "삭제하기 전에 APEX CARE 가 바꾼 설정(성능 모드, 게임 부스트, 원격 분석 정책, "
                "맞춤 튜닝, 꺼 둔 시작 프로그램)을 원래대로 되돌립니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
        sys.exit(0)

    install_dir = os.path.dirname(os.path.abspath(sys.executable))

    # STRICT SAFETY CHECK: Only delete if running EXACTLY from LOCALAPPDATA\APEX CARE
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    expected_dir = os.path.join(local_app_data, "APEX CARE")

    if os.path.normcase(install_dir) != os.path.normcase(expected_dir):
        _message(QMessageBox.Icon.Critical, "제거 오류",
                 f"정상적인 설치 경로가 아닙니다.\n이 프로그램은 실제 설치된 위치(AppData)에서만 실행 가능합니다.\n현재 경로: {install_dir}")
        sys.exit(1)

    # 실행 중인 앱을 강제 종료하지 않는다. 강제 종료하면 게임 부스트·우선순위 정리가 돌지 않고,
    # 되돌리기와 앱이 같은 기록 파일을 동시에 쓴다.
    if _app_running():
        _message(QMessageBox.Icon.Warning, "APEX CARE 삭제",
                 "APEX CARE 가 실행 중입니다(또는 실행 여부를 확인하지 못했습니다).\n"
                 "APEX CARE 창을 닫은 뒤 다시 삭제해 주세요.")
        sys.exit(1)

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        reverted, why = _revert_system_changes(install_dir)
    finally:
        QApplication.restoreOverrideCursor()

    if not reverted:
        # 되돌리지 못했는데 앱을 지우면 되돌릴 방법이 사라진다. 기본 선택은 '아니요'.
        if _message(QMessageBox.Icon.Warning, "설정을 모두 되돌리지 못했습니다",
                    f"{why}\n\n그래도 삭제하시겠습니까?\n"
                    "삭제하면 남은 설정을 이 프로그램으로 되돌릴 수 없습니다. '아니요' 를 누르고 "
                    "APEX CARE 복구 센터에서 다시 시도하는 것을 권합니다.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            sys.exit(1)

    bat_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "uninstall_apex.bat")

    with open(bat_path, "w", encoding="euc-kr") as f:
        f.write('@echo off\n')
        f.write('timeout /t 2 /nobreak > NUL\n')  # wait for uninstaller to exit

        # 1. Delete installation directory
        f.write(f'rmdir /s /q "{install_dir}"\n')

        # 2. Delete Desktop shortcuts
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = shell.SpecialFolders("Desktop")
        f.write(f'del /q "{os.path.join(desktop, "APEX CARE.lnk")}" > NUL 2>&1\n')

        # Try OneDrive desktop just in case
        onedrive_desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "바탕 화면")
        if os.path.exists(onedrive_desktop):
            f.write(f'del /q "{os.path.join(onedrive_desktop, "APEX CARE.lnk")}" > NUL 2>&1\n')

        # 3. Delete Start Menu shortcut
        start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "APEX CARE")
        f.write(f'rmdir /s /q "{start_menu}" > NUL 2>&1\n')

        # 4. Delete Registry key
        f.write('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\APEX CARE" /f > NUL 2>&1\n')

        # 5. Show completion message
        f.write('msg * APEX CARE가 성공적으로 제거되었습니다.\n')

        # 6. Delete self (the batch file)
        f.write('del "%~f0"\n')

    os.startfile(bat_path)
    sys.exit(0)

if __name__ == "__main__":
    main()
