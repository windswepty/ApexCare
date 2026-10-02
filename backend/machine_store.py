"""
APEX CARE — PC 전체에 하나뿐인 상태를 두는 곳: HKLM\\SOFTWARE\\APEX CARE (64비트 보기).

시스템 변경 저널과 성능 모드처럼 PC 에 하나뿐인 것은 계정마다 따로 두면 안 되고, 관리자만 쓸 수 있는 곳에 둬야 한다.
예전에는 %APPDATA%\\APEX_CARE_DATA 에 두었다.
  - 두 계정이 앱을 쓰면 계정 B 가 계정 A 의 게이밍 값(전원 플랜·HKLM)을 '원래 값' 으로 기록해, B 의 되돌리기가
    게이밍 값을 다시 써 넣었다. 제거 프로그램도 제거하는 계정의 기록만 되돌렸다.
  - 그 폴더는 같은 계정의 일반 권한 프로그램도 쓸 수 있다. 저널에 항목을 써 넣으면 관리자 권한으로 도는 이 앱이
    '되돌리기' 로 그 값을 어느 HKLM 키에든 썼다.
HKLM\\SOFTWARE 아래 키는 관리자·SYSTEM 만 만들고 쓸 수 있다(일반 사용자는 읽기만).
"""

import json
import logging
import time
import winreg

log = logging.getLogger('MachineStore')

KEY = r'SOFTWARE\APEX CARE'
_VIEW = winreg.KEY_WOW64_64KEY


class Unreadable(Exception):
    """값은 있는데 읽지 못했다(권한 등). 없는 것과 다르다 — 빈 값으로 보고 쓰면 기존 기록을 덮는다."""


def read(name):
    """JSON 값을 읽는다. 없으면 None. 읽지 못하면 Unreadable. 깨졌으면 옆 이름으로 옮기고 None."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY, 0, winreg.KEY_READ | _VIEW) as k:
            raw, vtype = winreg.QueryValueEx(k, name)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Unreadable(str(e))
    try:
        if vtype != winreg.REG_SZ or not isinstance(raw, str):
            raise ValueError(f'형식이 REG_SZ 가 아닙니다({vtype})')
        return json.loads(raw)
    except ValueError as e:
        # 깨진 값을 그대로 두면 다음 저장이 덮어 안의 원래 값 기록이 사라진다. 사람이 볼 수 있게 옆에 남긴다.
        log.error(f"{name} 값이 깨져 있습니다: {e}")
        aside = f"{name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, 0,
                                    winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE | _VIEW) as k:
                winreg.SetValueEx(k, aside, 0, vtype, raw)
                winreg.DeleteValue(k, name)
        except (OSError, TypeError, ValueError) as e2:
            log.error(f"깨진 {name} 값을 옮기지 못했습니다: {e2}")
        return None


def write(name, data):
    """JSON 으로 쓰고 디스크에 내린다. 다시 읽어 같으면 True."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE | _VIEW) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, text)
            # 레지스트리는 몇 초 뒤에 디스크에 쓴다. 원래 값 기록이 내려가기 전에 시스템을 바꾸고 전원이 꺼지면
            # 바뀐 값만 남는다. 바꾸기 전에 내려 둔다.
            winreg.FlushKey(k)
            back, vtype = winreg.QueryValueEx(k, name)
    except OSError as e:
        log.error(f"{name} 을(를) 저장하지 못했습니다: {e}")
        return False
    return vtype == winreg.REG_SZ and back == text


def remove():
    """키를 통째로 지운다(제거할 때, 되돌릴 기록이 하나도 없을 때만). 지웠거나 원래 없으면 True."""
    try:
        winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, _VIEW, 0)
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        log.error(f"{KEY} 를 지우지 못했습니다: {e}")
        return False
