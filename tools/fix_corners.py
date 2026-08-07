from PIL import Image, ImageDraw

def process_image(filepath):
    # Load image (which might have (255,255,255,0) in corners)
    img = Image.open(filepath).convert("RGBA")
    
    # Create a new image with pure black transparent background (0,0,0,0)
    fixed = Image.new("RGBA", img.size, (0, 0, 0, 0))
    
    # Composite the image over the transparent black background
    # This ensures that any pixel with alpha=0 becomes (0,0,0,0) instead of (255,255,255,0)
    fixed = Image.alpha_composite(fixed, img)
    
    # Overwrite the original png
    fixed.save(filepath)
    
    # Save the ICO file
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_path = filepath.replace(".png", ".ico")
    
    # When saving ICO, ensure the background is completely transparent
    fixed.save(ico_path, format="ICO", sizes=icon_sizes)
    print(f"Fixed transparency for {filepath}")

if __name__ == "__main__":
    process_image("public/icon.png")
    process_image("public/setup_icon.png")
