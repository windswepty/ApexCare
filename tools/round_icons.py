from PIL import Image, ImageDraw
import os

def make_rounded_transparent(img, radius_ratio=0.25):
    img = img.convert("RGBA")
    
    # Create mask
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw rounded rectangle
    w, h = img.size
    radius = int(min(w, h) * radius_ratio)
    draw.rounded_rectangle((0, 0, w, h), radius, fill=255)
    
    # Put mask as alpha
    result = img.copy()
    result.putalpha(mask)
    return result

def process_icons():
    # 1. Main Icon
    icon = Image.open("public/icon.png").convert("RGBA")
    icon_rounded = make_rounded_transparent(icon, 0.3)
    icon_rounded.save("public/icon.png")
    
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    icon_rounded.save("public/icon.ico", format="ICO", sizes=icon_sizes)
    
    # Copy to artifacts
    icon_rounded.save(r"C:\Users\rlagu\.gemini\antigravity-ide\brain\254f653c-c9e5-49ef-9e1d-c6a28329072b\main_icon.png")

    # 2. Setup Icon
    setup_icon = Image.open("public/setup_icon.png").convert("RGBA")
    setup_rounded = make_rounded_transparent(setup_icon, 0.3)
    setup_rounded.save("public/setup_icon.png")
    setup_rounded.save("public/setup_icon.ico", format="ICO", sizes=icon_sizes)
    
    # Copy to artifacts
    setup_rounded.save(r"C:\Users\rlagu\.gemini\antigravity-ide\brain\254f653c-c9e5-49ef-9e1d-c6a28329072b\setup_icon.png")
    print("Icons processed with rounded transparent borders successfully!")

if __name__ == "__main__":
    process_icons()
