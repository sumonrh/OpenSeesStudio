"""Render the application icon to assets/opensees_studio.ico."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import icons  # noqa: E402

app = QApplication([])
assets = os.path.join(ROOT, "assets")
os.makedirs(assets, exist_ok=True)

pm = icons.app_icon(256).pixmap(256, 256)
png = os.path.join(assets, "opensees_studio.png")
pm.save(png)

from PIL import Image  # noqa: E402

img = Image.open(png).convert("RGBA")
ico = os.path.join(assets, "opensees_studio.ico")
img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)])
print("wrote", ico)
