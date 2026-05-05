import os
import sys
import subprocess

def convert():
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
        from PIL import Image

    png_path = "icon.png"
    ico_path = "icon.ico"

    if not os.path.exists(png_path):
        print(f"Error: {png_path} not found.")
        return

    print(f"Converting {png_path} to {ico_path}...")
    img = Image.open(png_path)
    # Windows icons usually contain multiple sizes
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico_path, sizes=icon_sizes)
    print("Success!")

if __name__ == "__main__":
    convert()
