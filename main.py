import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 제거 프로그램이 설치 폴더를 지우기 전에 부른다. 창을 띄우지 않고 이 앱이 바꾼 것만 되돌린 뒤 끝낸다.
# Api 를 만들면 안 된다: 생성자가 저장된 성능 모드를 다시 적용하고 게임 부스트를 켠다.
if __name__ == '__main__' and '--revert-for-uninstall' in sys.argv[1:]:
    from backend import uninstall_prep
    sys.exit(uninstall_prep.main_cli())

import webview
from backend.api import Api


def get_html_path():
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'dist_react', 'index.html')
    
    dist_path = os.path.join(os.path.dirname(__file__), 'dist_react')
    if os.path.exists(os.path.join(dist_path, 'index.html')):
        return os.path.join(dist_path, 'index.html')
    return "http://localhost:5173"

if __name__ == '__main__':
    html_path = get_html_path()
    
    api = Api(None)
    
    # Priority boost removed to prevent UI freezing (Not Responding)
    
    window = webview.create_window(
        title='APEX CARE', 
        url=html_path,
        js_api=api,
        width=1240, 
        height=840,
        resizable=False,
        frameless=True,
        easy_drag=False,
        background_color='#080c14'
    )
    api._window = window
    # 창이 최대화됐는지 Api 가 알고 있어야 최대화 버튼이 '최대화 ↔ 이전 크기' 를 맞게 오간다
    # (Windows 키+↑ 나 제목 표시줄 더블클릭으로 바뀐 경우 포함).
    window.events.maximized += api._on_window_maximized
    window.events.restored += api._on_window_restored
    # Ensure persistent storage across version updates by setting a fixed storage path
    app_data_path = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'APEX_CARE_DATA')
    os.makedirs(app_data_path, exist_ok=True)
    
    webview.start(debug=False, private_mode=False, storage_path=app_data_path)

    # 창이 제목 표시줄의 닫기 버튼이 아닌 다른 경로(작업 표시줄, Alt+F4, 로그오프)로
    # 닫혀도 게임 부스트와 우선순위를 되돌린다. 이미 정리됐다면 아무 일도 하지 않는다.
    api._cleanup()
