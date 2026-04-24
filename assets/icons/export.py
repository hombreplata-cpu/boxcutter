#!/usr/bin/env python3
"""Export all icon sizes from the master SVG for rekordbocks."""

import cairosvg
from PIL import Image
import os
from io import BytesIO

BASE_DIR = "/home/claude/rekordbocks"
MASTER_SVG = os.path.join(BASE_DIR, "icon-master.svg")
FAVICON_SVG = os.path.join(BASE_DIR, "favicon.svg")

# Sizes needed
PNG_SIZES = {
    # Favicon pack
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    # Apple touch
    "apple-touch-icon.png": 180,
    # Android / PWA
    "android-chrome-192x192.png": 192,
    "android-chrome-512x512.png": 512,
    # App store / general
    "icon-1024.png": 1024,
    "icon-512.png": 512,
    "icon-256.png": 256,
    "icon-128.png": 128,
    "icon-64.png": 64,
}

# For tiny favicon sizes (16, 32, 48), use the simplified favicon SVG
# For everything else, use the detailed master
TINY_SIZES = {"favicon-16x16.png", "favicon-32x32.png", "favicon-48x48.png"}

print("Exporting PNG files...")
for filename, size in PNG_SIZES.items():
    source_svg = FAVICON_SVG if filename in TINY_SIZES else MASTER_SVG
    output_path = os.path.join(BASE_DIR, filename)
    cairosvg.svg2png(
        url=source_svg,
        write_to=output_path,
        output_width=size,
        output_height=size,
    )
    print(f"  {filename} ({size}x{size})")

# Generate multi-resolution .ico file
print("\nGenerating favicon.ico...")
ico_sizes = [(16, 16), (32, 32), (48, 48)]
ico_images = []
for w, h in ico_sizes:
    png_bytes = cairosvg.svg2png(
        url=FAVICON_SVG,
        output_width=w,
        output_height=h,
    )
    img = Image.open(BytesIO(png_bytes))
    ico_images.append(img)

ico_path = os.path.join(BASE_DIR, "favicon.ico")
ico_images[0].save(
    ico_path,
    format="ICO",
    sizes=ico_sizes,
    append_images=ico_images[1:],
)
print(f"  favicon.ico (16, 32, 48 multi-res)")

# Macos .icns source sizes (for manual iconutil assembly if needed)
print("\nExporting macOS .icns source PNGs...")
ICNS_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}
icns_dir = os.path.join(BASE_DIR, "icon.iconset")
os.makedirs(icns_dir, exist_ok=True)
for filename, size in ICNS_SIZES.items():
    source_svg = FAVICON_SVG if size <= 48 else MASTER_SVG
    output_path = os.path.join(icns_dir, filename)
    cairosvg.svg2png(
        url=source_svg,
        write_to=output_path,
        output_width=size,
        output_height=size,
    )
print(f"  icon.iconset/ folder ready (run `iconutil -c icns icon.iconset` on macOS)")

print("\nDone.")
