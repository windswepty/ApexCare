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

    webview.start(debug=False)
