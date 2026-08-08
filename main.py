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

def setup_tray(window):
    global tray_icon
    
    def on_show(icon, item):
        window.show()

    def on_quit(icon, item):
        icon.stop()
        window.destroy()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem('APEX CARE 열기', on_show),
        pystray.MenuItem('완전히 종료', on_quit)
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
    
    setup_tray(window)
    
    webview.start(debug=False, private_mode=False, storage_path=app_data_path)
