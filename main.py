import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import webview
from backend.api import Api
import threading
import pystray
from PIL import Image, ImageDraw

def create_image():
    # Create a simple icon image for the system tray
    image = Image.new('RGB', (64, 64), color = (8, 12, 20))
    dc = ImageDraw.Draw(image)
    dc.rectangle(
        (16, 16, 48, 48),
        fill=(34, 211, 238) # Cyan-400
    )
    return image

tray_icon = None

def setup_tray(window, api):
    global tray_icon
    
    def on_show(icon, item):
        window.show()

    def on_quit(icon, item):
        icon.stop()
        api.quitApplication()

    def toggle_game_booster(icon, item):
        current = api.getGameBoosterStatus()
        api.toggleGameBooster(not current)

    def is_game_booster_on(item):
        return api.getGameBoosterStatus()

    def set_opt_mode(mode):
        def handler(icon, item):
            api.setOptimizationMode(mode)
        return handler

    def is_opt_mode(mode):
        def handler(item):
            return api.getOptimizationMode() == mode
        return handler

    menu = pystray.Menu(
        pystray.MenuItem('APEX CARE 띄우기', on_show, default=True),
        pystray.MenuItem('🎮 스마트 게임 부스터', toggle_game_booster, checked=is_game_booster_on),
        pystray.MenuItem('⚡ 성능 모드', pystray.Menu(
            pystray.MenuItem('표준 (Standard)', set_opt_mode('standard'), checked=is_opt_mode('standard'), radio=True),
            pystray.MenuItem('게이밍 (Gaming)', set_opt_mode('gaming'), checked=is_opt_mode('gaming'), radio=True),
            pystray.MenuItem('에코 (Eco)', set_opt_mode('eco'), checked=is_opt_mode('eco'), radio=True)
        )),
        pystray.MenuItem('완전히 종료 (프로세스 킬)', on_quit)
    )
    
    tray_icon = pystray.Icon("APEX_CARE", create_image(), "APEX CARE", menu)
    threading.Thread(target=tray_icon.run, daemon=True).start()


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
    
    
    # window closing event hook (for Alt+F4 or direct window close)
    def on_closing():
        window.hide()
        return False
        
    window.events.closing += on_closing
    
    setup_tray(window, api)
    
    webview.start(debug=False, private_mode=False, storage_path=app_data_path)
