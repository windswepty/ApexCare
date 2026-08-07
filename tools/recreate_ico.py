from PIL import Image

def recreate_ico(png_path, ico_path):
    img = Image.open(png_path).convert("RGBA")
    # Resize to 256x256, which is standard for Windows icons and highly compatible
    img = img.resize((256, 256), Image.Resampling.LANCZOS)
    # Save as ICO without specifying sizes (Pillow will create a single 256x256 icon)
    # which avoids the multi-size ICO corruption issue in Windows Explorer
    img.save(ico_path, format="ICO")
    print(f"Recreated robust ICO: {ico_path}")

if __name__ == "__main__":
    recreate_ico("public/icon.png", "public/icon.ico")
    recreate_ico("public/setup_icon.png", "public/setup_icon.ico")
