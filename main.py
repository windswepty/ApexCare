import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

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
    # Ensure persistent storage across version updates by setting a fixed storage path
    app_data_path = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'APEX_CARE_DATA')
    os.makedirs(app_data_path, exist_ok=True)
    
    webview.start(debug=False, private_mode=False, storage_path=app_data_path)

    # 창이 제목 표시줄의 닫기 버튼이 아닌 다른 경로(작업 표시줄, Alt+F4, 로그오프)로
    # 닫혀도 게임 부스트와 우선순위를 되돌린다. 이미 정리됐다면 아무 일도 하지 않는다.
    api._cleanup()
