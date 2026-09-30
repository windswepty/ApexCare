import json
import ntpath
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
# backend/debloater.py 의 REMOVED_NAME 과 같아야 한다
REMOVED_APPS_PATH = os.path.join(os.environ.get("APPDATA", ""), "APEX_CARE_DATA", "debloat_removed.json")


def _removed_app_count():
    """디블로터로 제거하고 아직 되살리지 않은 앱 수. 읽지 못하면 0."""
    try:
        with open(REMOVED_APPS_PATH, encoding="utf-8") as f:
            apps = json.load(f).get("apps", [])
        return len([a for a in apps if isinstance(a, dict)])
    except Exception:
        return 0


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

    removed_apps = _removed_app_count()
    # 사용자가 일부러 지운 앱을 프로그램 제거 때 다시 설치하지 않는다. 대신 그 사실을 먼저 알린다.
    # 화면 이름은 앱 사이드바와 같아야 사용자가 찾아갈 수 있다('Windows 기본 앱 정리', '변경 내역 · 되돌리기').
    removed_note = (f"\n\n'Windows 기본 앱 정리' 로 제거한 앱 {removed_apps}개는 다시 설치하지 않습니다. 필요하면 "
                    "'아니요' 를 누르고 APEX CARE 의 'Windows 기본 앱 정리' 화면 → '제거한 앱' 에서 먼저 되살리세요."
                    if removed_apps else "")
    if _message(QMessageBox.Icon.Warning, "APEX CARE 삭제",
                "APEX CARE 프로그램을 삭제하시겠습니까?\n\n"
                "삭제하기 전에 APEX CARE 가 바꾼 설정(성능 모드, 게임 부스트, 원격 분석 정책, "
                "맞춤 튜닝, 꺼 둔 시작 프로그램)을 원래대로 되돌립니다." + removed_note,
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
                    "APEX CARE 의 '변경 내역 · 되돌리기' 화면에서 다시 시도하는 것을 권합니다.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            sys.exit(1)

    temp_dir = os.environ.get("TEMP") or os.path.join(local_app_data, "Temp")
    bat_path = os.path.join(temp_dir, "uninstall_apex.bat")
    try:
        _write_cleanup_bat(bat_path, install_dir)
    except (OSError, UnicodeEncodeError) as e:
        _message(QMessageBox.Icon.Warning, "APEX CARE 삭제",
                 f"설정은 되돌렸지만 설치 폴더를 지우는 준비를 하지 못했습니다: {e}\n"
                 f"아래 폴더를 직접 지워 주세요.\n{install_dir}")
        sys.exit(1)

    # 배치 파일의 작업 폴더를 설치 폴더 밖으로 둔다. 탐색기에서 제거 프로그램을 실행하면 작업 폴더가
    # 설치 폴더이고, os.startfile 로 띄운 cmd 가 그것을 물려받는다. 어떤 프로세스의 작업 폴더인 폴더는
    # 지울 수 없어서 샌드박스 점검에서 설치 폴더가 그대로 남았다.
    subprocess.Popen([_system32("cmd.exe"), "/d", "/c", bat_path], shell=False, cwd=temp_dir,
                     creationflags=CREATE_NO_WINDOW, close_fds=True)
    sys.exit(0)


def _bat_encoding():
    # cmd 는 배치 파일을 콘솔 코드 페이지(OEM)로 읽는다. euc-kr 로 고정하면 한국어가 아닌 Windows 에서 경로가 깨진다.
    return "oem" if os.name == "nt" else "utf-8"


def _fits(text):
    try:
        text.encode(_bat_encoding())
        return True
    except UnicodeEncodeError:
        return False


def _cleanup_bat_lines(bat_path, install_dir, shortcuts, start_menu):
    """설치 폴더·바로 가기·프로그램 목록 키를 지우는 배치 파일 내용.

    제거 프로그램(PyInstaller 부트로더 포함)이 끝나 exe 잠금이 풀릴 때까지 폴더 삭제를 최대 30번 다시 시도하고,
    끝에 실제로 지워졌는지에 따라 다른 메시지를 띄운다(지우지 못했는데 '제거되었습니다' 라고 하지 않는다).
    """
    ok_msg = "APEX CARE가 제거되었습니다."
    fail_msg = "APEX CARE 설치 폴더를 지우지 못했습니다. 이 폴더를 직접 지워 주세요:"
    if not (_fits(ok_msg) and _fits(fail_msg)):
        ok_msg, fail_msg = "APEX CARE has been removed.", "Could not delete the APEX CARE folder. Please delete it:"
    lines = [
        '@echo off',
        f'cd /d "{ntpath.dirname(bat_path)}"',
        'set /a tries=0',
        ':retry',
        'ping -n 2 127.0.0.1 > NUL',          # 창 없이 돌면 timeout 은 입력 리디렉션 오류로 바로 끝난다
        f'if exist "{install_dir}" rmdir /s /q "{install_dir}"',
        f'if not exist "{install_dir}" goto removed',
        'set /a tries+=1',
        'if %tries% lss 30 goto retry',
        'goto cleanup',
        ':removed',
    ]
    lines += [f'del /q "{p}" > NUL 2>&1' for p in shortcuts]
    lines += [
        f'rmdir /s /q "{start_menu}" > NUL 2>&1',
        'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\APEX CARE" /f > NUL 2>&1',
        f'msg * {ok_msg}',
        'goto end',
        ':cleanup',
        f'msg * {fail_msg} {install_dir}',
        ':end',
        'del "%~f0"',
    ]
    return lines


def _write_cleanup_bat(bat_path, install_dir):
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcuts = [os.path.join(shell.SpecialFolders("Desktop"), "APEX CARE.lnk")]
    onedrive_desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "바탕 화면")
    if os.path.exists(onedrive_desktop):
        shortcuts.append(os.path.join(onedrive_desktop, "APEX CARE.lnk"))
    start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "APEX CARE")
    lines = _cleanup_bat_lines(bat_path, install_dir, shortcuts, start_menu)
    # 경로를 코드 페이지로 나타낼 수 없으면 errors 없이 실패시킨다. 깨진 경로로 rmdir 을 부르지 않는다.
    with open(bat_path, "w", encoding=_bat_encoding()) as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
