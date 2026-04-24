# rekordbocks icon pack

Complete icon set for the rekordbocks app and website. Generated from a single master SVG.

---

## What's here

### Source files (editable)
- `icon-master.svg` — 1024×1024 master artwork. Edit this to change the icon; re-run export.py to regenerate all sizes.
- `favicon.svg` — simplified version optimized for tiny sizes (16–48px). Modern browsers prefer this for the favicon.
- `export.py` — script that regenerates every PNG + the .ico from the two SVGs above.

### Web / favicon pack
Drop these at the root of your website:
- `favicon.ico` — multi-res .ico (16, 32, 48) for legacy browser support
- `favicon.svg` — scalable favicon for modern browsers
- `favicon-16x16.png` — tab icon
- `favicon-32x32.png` — tab icon (retina)
- `favicon-48x48.png`
- `apple-touch-icon.png` — 180×180, iOS home screen
- `android-chrome-192x192.png` — Android home screen
- `android-chrome-512x512.png` — PWA splash / install icon
- `site.webmanifest` — PWA manifest referencing the Android icons

### HTML integration
- `html-head-snippet.html` — paste this inside your `<head>` tag

### App icons (various sizes)
- `icon-1024.png` — App Store, App Store Connect uploads
- `icon-512.png`, `icon-256.png`, `icon-128.png`, `icon-64.png` — general use

### macOS app bundle
- `icon.iconset/` — folder with all the PNG sizes macOS needs for an .icns file
- To generate `icon.icns` on a Mac, run in terminal:
  ```
  iconutil -c icns icon.iconset
  ```

### Windows app
- For a .ico file for a Windows app installer/executable, use `favicon.ico` (it's multi-res)
- If you need bigger sizes in the ico (256px), regenerate with modified `export.py`

---

## Palette

- Tile background: `#1e3a5f` (deep navy)
- Drive body gradient: `#7fb3de` → `#3d6590`
- Metal connector: `#e8eef7` → `#8fa8c8`
- LED accent: `#5ec8e8` (cyan)

---

## Re-exporting

If you edit `icon-master.svg` or `favicon.svg`, regenerate everything with:

```bash
python3 export.py
```

Requires `cairosvg` and `pillow`:
```bash
pip install cairosvg pillow
```
