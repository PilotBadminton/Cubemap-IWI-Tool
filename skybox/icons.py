"""One small vector icon family, drawn at the requested device pixel ratio."""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon, QPainterPath


def icon(name, color, dpr=1.0):
    image=QPixmap(round(20*dpr),round(20*dpr))
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color),1.35,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    def line(a,b):painter.drawLine(QPointF(*a),QPointF(*b))
    if name in ("import","folder"):
        path=QPainterPath(QPointF(2,6));path.lineTo(2,16);path.lineTo(18,16);path.lineTo(18,6)
        path.lineTo(10,6);path.lineTo(8,4);path.lineTo(2,4);path.lineTo(2,6)
        painter.drawPath(path)
        if name=="import":
            line((10,8),(10,14));line((7,11),(10,14));line((13,11),(10,14))
    elif name in ("build","cube"):
        for a,b in [((10,2),(18,6)),((18,6),(18,14)),((18,14),(10,18)),((10,18),(2,14)),((2,14),(2,6)),((2,6),(10,2)),((2,6),(10,10)),((18,6),(10,10)),((10,10),(10,18))]:line(a,b)
    elif name in ("zoom_in","zoom_out"):
        painter.drawEllipse(QRectF(3,3,10,10));line((12,12),(18,18));line((5,8),(11,8))
        if name=="zoom_in":line((8,5),(8,11))
    elif name=="fit":
        for a,b in [((2,7),(2,2)),((2,2),(7,2)),((13,2),(18,2)),((18,2),(18,7)),((18,13),(18,18)),((18,18),(13,18)),((7,18),(2,18)),((2,18),(2,13))]:line(a,b)
        painter.drawRect(QRectF(6,6,8,8))
    elif name=="compare":
        painter.drawRect(QRectF(2,3,16,14));line((10,3),(10,17))
    elif name=="refresh":
        painter.drawArc(QRectF(3,3,14,14),30*16,295*16);line((16,3),(16,8));line((16,8),(12,7))
    elif name=="save":
        painter.drawRect(QRectF(3,2,14,16));painter.drawRect(QRectF(6,2,7,5));painter.drawRect(QRectF(6,11,8,7))
    elif name=="file":
        path=QPainterPath(QPointF(4,2));path.lineTo(12,2);path.lineTo(16,6);path.lineTo(16,18);path.lineTo(4,18);path.closeSubpath();painter.drawPath(path)
        line((7,10),(13,10));line((7,13),(13,13))
    elif name=="info":
        painter.drawEllipse(QRectF(2,2,16,16));line((10,9),(10,14));painter.drawPoint(QPointF(10,6))
    else:
        raise ValueError(name)
    painter.end()
    return QIcon(image)
