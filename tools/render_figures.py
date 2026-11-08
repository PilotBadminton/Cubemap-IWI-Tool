"""Render the editable handbook figures to high-resolution PNG files."""
import argparse
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

FIGURES = Path(__file__).resolve().parents[1] / "docs" / "figures"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="*", help="SVG files; defaults to all handbook figures")
    parser.add_argument("--scale", type=int, default=3, help="Raster resolution multiplier (default: 3)")
    args = parser.parse_args()
    if args.scale < 1:
        parser.error("--scale must be positive")
    app = QGuiApplication([])
    fonts = Path(os.environ["SystemRoot"]) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf"):
        path = fonts / name
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            raise OSError(f"Cannot load figure font: {path}")
    for path in args.files or sorted(FIGURES.glob("*.svg")):
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            raise ValueError(f"Invalid SVG: {path}")
        size = renderer.defaultSize()
        image = QImage(QSize(size.width()*args.scale, size.height()*args.scale),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
        painter.end()
        output = path.with_suffix(".png")
        if not image.save(str(output)):
            raise OSError(f"Cannot save figure: {output}")
        print(f"{output.name}: {image.width()} x {image.height()}")


if __name__ == "__main__":
    main()
