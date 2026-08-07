import sys
from PIL import Image, ImageOps, ImageDraw

def make_setup_icon():
    img = Image.open("public/icon.png").convert("RGBA")
    
    # Invert the original icon (black to white)
    r, g, b, a = img.split()
    rgb = Image.merge('RGB', (r, g, b))
    inverted = ImageOps.invert(rgb)
    img_inverted = Image.merge('RGBA', (*inverted.split(), a))
    
    # Create a dark slate box for the setup
    box_size = img.size
    box = Image.new('RGBA', box_size, (20, 25, 30, 255)) # Dark slate blue
    
    # Draw a subtle border
    draw = ImageDraw.Draw(box)
    border_width = int(box_size[0] * 0.05)
    draw.rectangle([0, 0, box_size[0]-1, box_size[1]-1], outline=(100, 100, 100, 255), width=border_width)
    
    # Paste the inverted A inside
    # Shrink the A slightly
    w, h = int(box_size[0] * 0.6), int(box_size[1] * 0.6)
    scaled = img_inverted.resize((w, h), Image.Resampling.LANCZOS)
    
    # Calculate center
    offset_x = (box_size[0] - w) // 2
    offset_y = (box_size[1] - h) // 2
    
    box.paste(scaled, (offset_x, offset_y), scaled)
    
    box.save("public/setup_icon.png")
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    box.save("public/setup_icon.ico", format="ICO", sizes=icon_sizes)
    print("Setup icon created successfully!")

if __name__ == "__main__":
    make_setup_icon()
