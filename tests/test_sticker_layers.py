import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from app.pages.sticker_page import StickerPage
from app.widgets.preview_canvas import PreviewCanvas
from config import AppConfig


app = QApplication.instance() or QApplication([])
config = AppConfig()
config.sticker_layers_json = json.dumps([
    {"scale": 90, "opacity": 80, "x": 10, "y": -43},
    {"scale": 110, "opacity": 100, "x": -10, "y": 43},
])
page = StickerPage(config)

page._update_layer(0, "y", -45)
assert json.loads(config.sticker_layers_json)[0]["y"] == -45
page._add_layer()
assert len(json.loads(config.sticker_layers_json)) == 3
page._delete_layer(1)
layers = json.loads(config.sticker_layers_json)
assert len(layers) == 2 and layers[1]["x"] == 0

preview = PreviewCanvas(config, Path.cwd())
preview._label.resize(400, 800)
preview._pixmap = QPixmap(300, 600)
assert preview._layer_point({"x": -50, "y": -50}) == (50, 100)
assert preview._layer_point({"x": 50, "y": 50}) == (350, 700)

preview._show_pixmap(QPixmap(100, 200))
preview._label.resize(300, 600)
preview._rescale_pixmap()
assert preview._pixmap.size().width() == 300
assert preview._pixmap.size().height() == 600
print("sticker layer editor: OK")
