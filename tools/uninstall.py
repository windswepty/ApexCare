import base64
import json
import ntpath
import os
import subprocess
import sys
import tempfile
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
import win32com.client

CREATE_NO_WINDOW = 0x08000000
APP_EXE = "APEX CARE.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE"


def install_dir_expected():
    """설치 마법사(tools/setup_wizard.install_dir)와 같은 위치: %ProgramFiles%\\APEX CARE."""
    base = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return os.path.join(base, "APEX CARE")
REVERT_TIMEOUT_SEC = 300
# backend/uninstall_prep.py 의 RESULT_NAME 과 같아야 한다
RESULT_PATH = os.path.join(os.environ.get("APPDATA", ""), "APEX_CARE_DATA", "uninstall_revert.json")
# backend/debloater.py 의 REMOVED_NAME 과 같아야 한다
REMOVED_APPS_PATH = os.path.join(os.environ.get("APPDATA", ""), "APEX_CARE_DATA", "debloat_removed.json")


def _english():
    """화면 언어: APEX CARE 에서 고른 언어가 있으면 그것, 없으면 Windows 표시 언어(한국어가 아니면 영어). 앱과 같은 규칙."""
    try:
        with open(os.path.join(os.environ.get("APPDATA", ""), "APEX_CARE_DATA", "settings.json"), encoding="utf-8") as f:
            chosen = json.load(f).get("ui_language")
        if chosen in ("ko", "en"):
            return chosen == "en"
    except Exception:
        pass
    try:
        import ctypes
        return (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) != 0x12     # LANG_KOREAN
    except Exception:
        return False


ENGLISH = _english()


def _T(ko, en):
    return en if ENGLISH else ko


TITLE = _T("APEX CARE 삭제", "Uninstall APEX CARE")


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
        return False, _T(f"{APP_EXE} 가 없어 설정을 되돌리지 못했습니다.",
                         f"Settings could not be restored because {APP_EXE} is missing.")
    try:
        os.remove(RESULT_PATH)             # 지난번 결과를 이번 결과로 착각하지 않게
    except FileNotFoundError:
        pass
    except OSError as e:
        return False, _T(f"이전 결과 파일을 지우지 못했습니다: {e}", f"Could not delete the previous result file: {e}")

    try:
        r = subprocess.run([exe, "--revert-for-uninstall"], shell=False,
                           creationflags=CREATE_NO_WINDOW, timeout=REVERT_TIMEOUT_SEC)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return False, _T(f"설정 되돌리기가 {REVERT_TIMEOUT_SEC}초 안에 끝나지 않았습니다.",
                         f"Restoring settings did not finish within {REVERT_TIMEOUT_SEC} seconds.")
    except Exception as e:
        return False, _T(f"설정 되돌리기를 시작하지 못했습니다: {e}", f"Could not start restoring settings: {e}")

    try:
        with open(RESULT_PATH, encoding="utf-8") as f:
            res = json.load(f)
    except Exception:
        return False, _T(f"설정 되돌리기 결과를 읽지 못했습니다 (종료 코드 {rc}).",
                         f"Could not read the result of restoring settings (exit code {rc}).")

    if rc == 0 and res.get("success"):
        return True, ""
    failed = res.get("failed") or []
    lines = [f"- {f.get('name', '?')}: {f.get('detail', '')}".rstrip(": ") for f in failed[:10]]
    if len(failed) > 10:
        lines.append(_T(f"- 외 {len(failed) - 10}개", f"- and {len(failed) - 10} more"))
    return False, (_T("되돌리지 못한 항목:\n", "Items that could not be restored:\n")
                   + ("\n".join(lines) if lines else _T(f"(종료 코드 {rc})", f"(exit code {rc})")))


def _app_icon():
    # 제거 프로그램의 창은 모두 메시지 상자라 아이콘을 앱 전체에 건다. 없으면 Windows 기본 아이콘으로 보였다
    base = getattr(sys, '_MEIPASS', os.path.abspath('.'))
    for name in ('setup_icon.ico', os.path.join('public', 'setup_icon.ico')):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('APEXCARE.Uninstall')
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())

    removed_apps = _removed_app_count()
    # 사용자가 일부러 지운 앱을 프로그램 제거 때 다시 설치하지 않는다. 대신 그 사실을 먼저 알린다.
    # 화면 이름은 앱 사이드바와 같아야 사용자가 찾아갈 수 있다('Windows 기본 앱 정리', '변경 내역 · 되돌리기').
    removed_note = (_T(f"\n\n'Windows 기본 앱 정리' 로 제거한 앱 {removed_apps}개는 다시 설치하지 않습니다. 필요하면 "
                       "'아니요' 를 누르고 APEX CARE 의 'Windows 기본 앱 정리' 화면 → '제거한 앱' 에서 먼저 되살리세요.",
                       f"\n\n{removed_apps} apps removed with 'Windows built-in apps' will not be reinstalled. If needed, "
                       "press 'No' and restore them first under 'Windows built-in apps' → 'Removed apps' in APEX CARE.")
                    if removed_apps else "")
    if _message(QMessageBox.Icon.Warning, TITLE,
                _T("APEX CARE 프로그램을 삭제하시겠습니까?\n\n"
                   "삭제하기 전에 APEX CARE 가 바꾼 설정(성능 모드, 게임 부스트, 원격 분석·Cortana 정책, "
                   "맞춤 튜닝, 이 앱으로 켜거나 끈 시작 프로그램)을 바꾸기 전 상태로 되돌립니다.",
                   "Do you want to uninstall APEX CARE?\n\n"
                   "Before uninstalling, the settings APEX CARE changed (performance modes, game boost, telemetry and "
                   "Cortana policies, tailored tuning, startup programs turned on or off with this app) are restored to "
                   "how they were before.") + removed_note,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
        sys.exit(0)

    install_dir = os.path.dirname(os.path.abspath(sys.executable))

    # 엄격한 위치 확인: 설치 마법사가 설치하는 곳(%ProgramFiles%\APEX CARE)에서 실행될 때만 지운다
    expected_dir = install_dir_expected()
    if os.path.normcase(install_dir) != os.path.normcase(expected_dir):
        _message(QMessageBox.Icon.Critical, _T("제거 오류", "Uninstall error"),
                 _T(f"정상적인 설치 경로가 아닙니다.\n이 프로그램은 설치된 위치({expected_dir})에서만 실행할 수 있습니다.\n"
                    f"현재 경로: {install_dir}",
                    f"This is not the normal install location.\nThis program can run only from where it was installed "
                    f"({expected_dir}).\nCurrent location: {install_dir}"))
        sys.exit(1)

    # 실행 중인 앱을 강제 종료하지 않는다. 강제 종료하면 게임 부스트·우선순위 정리가 돌지 않고,
    # 되돌리기와 앱이 같은 기록 파일을 동시에 쓴다.
    if _app_running():
        _message(QMessageBox.Icon.Warning, TITLE,
                 _T("APEX CARE 가 실행 중입니다(또는 실행 여부를 확인하지 못했습니다).\n"
                    "APEX CARE 창을 닫은 뒤 다시 삭제해 주세요.",
                    "APEX CARE is running (or it could not be checked whether it is running).\n"
                    "Close the APEX CARE window and uninstall again."))
        sys.exit(1)

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        reverted, why = _revert_system_changes(install_dir)
    finally:
        QApplication.restoreOverrideCursor()

    if not reverted:
        # 되돌리지 못했는데 앱을 지우면 되돌릴 방법이 사라진다. 기본 선택은 '아니요'.
        if _message(QMessageBox.Icon.Warning, _T("설정을 모두 되돌리지 못했습니다", "Not all settings could be restored"),
                    f"{why}\n\n" + _T("그래도 삭제하시겠습니까?\n"
                                        "삭제하면 남은 설정을 이 프로그램으로 되돌릴 수 없습니다. '아니요' 를 누르고 "
                                        "APEX CARE 의 '변경 내역 · 되돌리기' 화면에서 다시 시도하는 것을 권합니다.",
                                        "Uninstall anyway?\n"
                                        "After uninstalling, the remaining settings cannot be restored with this program. "
                                        "We recommend pressing 'No' and trying again on the 'Change history · Undo' "
                                        "screen in APEX CARE."),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            sys.exit(1)

    # 정리 배치는 관리자만 고칠 수 있는 곳에 무작위 이름으로 만든다. 예전에는 사용자 %TEMP% 의 고정 이름
    # (uninstall_apex.bat)이라, 관리자 권한 cmd 가 줄 단위로 다시 읽는 수십 초 동안 일반 권한 프로그램이
    # 내용을 바꿔 관리자 권한으로 실행시킬 수 있었다.
    temp_root = _secure_temp_root()
    try:
        work_dir = tempfile.mkdtemp(prefix="apexcare-uninst-", dir=temp_root)
        bat_path = os.path.join(work_dir, "cleanup.bat")
        _write_cleanup_bat(bat_path, install_dir)
    except (OSError, UnicodeEncodeError) as e:
        if ENGLISH:
            first = ("Settings were restored, but" if reverted else "Some settings were not restored, and")
            text = (f"{first} preparing to delete the install folder failed: {e}\n"
                    f"Please delete this folder yourself.\n{install_dir}")
        else:
            first = ("설정은 되돌렸지만" if reverted else "설정 일부를 되돌리지 못한 채로")
            text = (f"{first} 설치 폴더를 지우는 준비를 하지 못했습니다: {e}\n"
                    f"아래 폴더를 직접 지워 주세요.\n{install_dir}")
        _message(QMessageBox.Icon.Warning, TITLE, text)
        sys.exit(1)

    # 배치 파일의 작업 폴더를 설치 폴더 밖으로 둔다. 탐색기에서 제거 프로그램을 실행하면 작업 폴더가
    # 설치 폴더이고, os.startfile 로 띄운 cmd 가 그것을 물려받는다. 어떤 프로세스의 작업 폴더인 폴더는
    # 지울 수 없어서 샌드박스 점검에서 설치 폴더가 그대로 남았다.
    # 작업 폴더는 System32(관리자만 씀). 사용자가 파일을 만들 수 있는 폴더를 작업 폴더로 두면, 배치가 이름만으로
    # 부르는 도구 대신 그 폴더에 심은 같은 이름의 exe 가 관리자 권한으로 돌 수 있다.
    subprocess.Popen([_system32("cmd.exe"), "/d", "/c", bat_path], shell=False, cwd=_system32(""),
                     creationflags=CREATE_NO_WINDOW, close_fds=True)
    sys.exit(0)


def _secure_temp_root():
    """%SystemRoot%\\Temp. 사용자는 여기 새 파일을 만들 수 있어도, 관리자가 만든 파일은 고칠 수 없다."""
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(root, "Temp")


def _bat_encoding():
    # cmd 는 배치 파일을 콘솔 코드 페이지(OEM)로 읽는다. euc-kr 로 고정하면 한국어가 아닌 Windows 에서 경로가 깨진다.
    return "oem" if os.name == "nt" else "utf-8"


def _fits(text):
    try:
        text.encode(_bat_encoding())
        return True
    except UnicodeEncodeError:
        return False


def _message_line(text):
    """배치에서 결과 창을 띄우는 한 줄. 모든 Windows 에디션에 있는 PowerShell 로 이 세션에만 띄운다.

    예전에는 'msg *' 를 썼는데, msg.exe 는 Home 에디션에 없어 성공도 실패도 보이지 않았고, Pro 에서는
    PC 의 모든 세션(다른 로그인 사용자 포함)에 설치 경로가 담긴 안내를 보냈다. 문구는 Base64(UTF-16) 로 넘겨
    콘솔 코드 페이지와 상관없이 한국어 그대로 보인다.
    """
    quoted = text.replace("'", "''")
    script = ("Add-Type -AssemblyName PresentationFramework; "
              f"[void][System.Windows.MessageBox]::Show('{quoted}', 'APEX CARE')")
    b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ('"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
            f'-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {b64}')


def _cleanup_bat_lines(bat_path, install_dir, shortcuts):
    """설치 폴더·바로 가기·프로그램 목록 키를 지우는 배치 파일 내용.

    제거 프로그램(PyInstaller 부트로더 포함)이 끝나 exe 잠금이 풀릴 때까지 폴더 삭제를 최대 30번 다시 시도하고,
    끝에 실제로 지워졌는지에 따라 다른 메시지를 띄운다(지우지 못했는데 '제거되었습니다' 라고 하지 않는다).
    작업 폴더는 배치가 든 폴더의 상위(%SystemRoot%\\Temp)다. 배치 폴더를 작업 폴더로 두면 끝에 그 폴더를 지울 수 없다.
    """
    ok_msg = _T("APEX CARE가 제거되었습니다.", "APEX CARE has been uninstalled.")
    fail_msg = _T(f"APEX CARE 설치 폴더를 지우지 못했습니다. 이 폴더를 직접 지워 주세요:\n{install_dir}",
                  f"Could not delete the APEX CARE install folder. Please delete this folder yourself:\n{install_dir}")
    work_dir = ntpath.dirname(bat_path)
    lines = [
        '@echo off',
        # 작업 폴더는 System32(관리자만 씀). 도구도 모두 절대 경로로 부른다. %SystemRoot%\\Temp 처럼 사용자가 파일을
        # 만들 수 있는 폴더를 작업 폴더로 두면, cmd 가 현재 폴더에서 먼저 찾은 ping.exe·reg.exe 가 관리자 권한으로 돌았다.
        'cd /d "%SystemRoot%\\System32"',
        'set /a tries=0',
        ':retry',
        '"%SystemRoot%\\System32\\PING.EXE" -n 2 127.0.0.1 > NUL',   # 창 없이 돌면 timeout 은 바로 끝난다
        f'if exist "{install_dir}" rmdir /s /q "{install_dir}"',
        f'if not exist "{install_dir}" goto removed',
        'set /a tries+=1',
        'if %tries% lss 30 goto retry',
        'goto cleanup',
        ':removed',
    ]
    lines += [f'del /q "{p}" > NUL 2>&1' for p in shortcuts]
    lines += [
        f'"%SystemRoot%\\System32\\reg.exe" delete "HKLM\\{UNINSTALL_KEY}" /f /reg:64 > NUL 2>&1',
        _message_line(ok_msg),
        'goto end',
        ':cleanup',
        _message_line(fail_msg),
        ':end',
        # 배치 파일과 그 폴더(이 제거 프로그램이 만든 것)만 지운다. (goto) 로 배치 문맥을 먼저 빠져나와야 지울 수 있다.
        f'(goto) 2>nul & del "%~f0" & rmdir "{work_dir}"',
    ]
    return lines


def _shortcut_paths():
    """지울 바로 가기: 이 버전(모든 사용자 시작 메뉴·공용 바탕 화면)과 예전 버전(사용자 바탕 화면)의 'APEX CARE.lnk'.

    배치에 쓸 수 없는(코드 페이지로 나타낼 수 없는) 경로는 뺀다. 예전에는 그런 바로 가기 경로 하나 때문에
    배치를 만들지 못해 설치 폴더 정리 전체가 취소됐다.
    """
    shell = win32com.client.Dispatch("WScript.Shell")
    folders = []
    for name in ("AllUsersPrograms", "AllUsersDesktop", "Desktop"):
        try:
            folders.append(shell.SpecialFolders(name))
        except Exception:
            pass
    folders.append(os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "바탕 화면"))
    out = []
    for f in dict.fromkeys(x for x in folders if x):
        lnk = os.path.join(f, "APEX CARE.lnk")
        if os.path.exists(lnk) and _fits(lnk):
            out.append(lnk)
    return out


def _write_cleanup_bat(bat_path, install_dir):
    lines = _cleanup_bat_lines(bat_path, install_dir, _shortcut_paths())
    # 설치 경로를 코드 페이지로 나타낼 수 없으면 errors 없이 실패시킨다. 깨진 경로로 rmdir 을 부르지 않는다.
    # 'x' 모드: 이미 있는 파일(미리 만들어 둔 것)에는 쓰지 않는다.
    with open(bat_path, "x", encoding=_bat_encoding()) as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
