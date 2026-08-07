import sys
from PIL import Image

try:
    img = Image.open("public/icon.png")
    # Convert to standard icon sizes
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save("public/icon.ico", format="ICO", sizes=icon_sizes)
    print("Icon successfully converted to public/icon.ico")
except Exception as e:
    print(f"Error: {e}")
