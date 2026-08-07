import os
from PIL import Image, ImageDraw, ImageOps

def create_perfect_icon(src_path, dest_png, dest_ico, invert=False):
    # Load original AI image
    img = Image.open(src_path).convert("RGBA")
    
    # Make it a square just in case
    sz = min(img.size)
    img = img.crop((0, 0, sz, sz))
    
    if invert:
        # Invert colors for setup icon (black background, white A)
        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))
        inverted_rgb = ImageOps.invert(rgb)
        img = Image.merge("RGBA", (*inverted_rgb.split(), a))
        
    # Create rounded mask
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(w * 0.25)
    draw.rounded_rectangle((0, 0, w, h), radius, fill=255)
    
    # Apply mask
    img.putalpha(mask)
    
    # CRITICAL FIX for Windows ICO white corners:
    # Set all fully transparent pixels to pure BLACK (0,0,0,0)
    # So if Windows drops the alpha channel, it draws black instead of white.
    # Since the setup icon is black, black corners will be invisible!
    pixels = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < 255:
                # Blend the RGB with black based on alpha to remove any white fringes
                # If a=0, it becomes (0,0,0,0)
                # This mathematically guarantees no white pixels on the edges!
                pixels[x, y] = (0, 0, 0, a)
                
    img.save(dest_png)
    
    # Save ICO with proper sizes
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(dest_ico, format="ICO", sizes=icon_sizes)
    print(f"Created perfect icon: {dest_ico}")

if __name__ == "__main__":
    src_img = r"C:\Users\rlagu\.gemini\antigravity-ide\brain\254f653c-c9e5-49ef-9e1d-c6a28329072b\unique_apex_monogram_1786013178552.png"
    
    # 1. Main Icon (Black A on White rounded box)
    create_perfect_icon(src_img, "public/icon.png", "public/icon.ico", invert=False)
    
    # 2. Setup Icon (White A on Black rounded box)
    create_perfect_icon(src_img, "public/setup_icon.png", "public/setup_icon.ico", invert=True)
