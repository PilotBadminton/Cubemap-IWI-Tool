"""Workbench input fields and six-face asset tiles."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QStandardPaths
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QLineEdit,QLabel,QFileDialog,QSizePolicy,QStyleOptionFrame,QStyle
from .theme import CompactButton
from .messages import msg
from .icons import icon


class DialogLocations:
    def __init__(self, settings):
        self.settings = settings

    def input_directory(self):
        return self.settings.value('paths/import_directory', QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation))

    def output_directory(self):
        default = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))/'cubemap_output')
        return self.settings.value('paths/export_directory', default)

    def remember_input(self, path):
        self.settings.setValue('paths/import_directory', str(Path(path).absolute().parent))
        self.settings.sync()

    def remember_output(self, path):
        self.settings.setValue('paths/export_directory', str(Path(path).absolute()))
        self.settings.sync()


class PathEdit(QLineEdit):
    def paintEvent(self,event):
        if self.hasFocus() or not self.text(): return super().paintEvent(event)
        option=QStyleOptionFrame();self.initStyleOption(option)
        area=self.style().subElementRect(QStyle.SubElement.SE_LineEditContents,option,self).adjusted(5,0,-6,0)
        if self.fontMetrics().horizontalAdvance(self.text()) <= area.width(): return super().paintEvent(event)
        painter=QPainter(self);self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelLineEdit,option,painter,self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(area,Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideMiddle,max(0,area.width())))


class PathField(QWidget):
    changed=Signal(str)
    invalid=Signal(object)

    def __init__(self,language,caption,kind="file",filter_key="filter.png",*,locations):
        super().__init__()
        self.locations=locations
        self.language,self.caption,self.kind,self.filter_key=language,caption,kind,filter_key
        self.setAcceptDrops(True)
        box=QHBoxLayout(self)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(4)
        self.edit=PathEdit()
        self.edit.setAcceptDrops(False)
        self.edit.setMinimumHeight(36)
        self.edit.setClearButtonEnabled(False)
        self.edit.editingFinished.connect(lambda:self.changed.emit(self.edit.text().strip()))
        self.edit.textChanged.connect(self.edit.setToolTip)
        self.setFocusProxy(self.edit)
        self.browse_button=CompactButton()
        self.browse_button.setMinimumHeight(36)
        self.browse_button.setText("…")
        self.browse_button.setFixedWidth(36)
        self.browse_button.clicked.connect(self.browse)
        box.addWidget(self.edit,1)
        box.addWidget(self.browse_button)
        language.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self):
        caption=self.language.text(self.caption)
        self.edit.setPlaceholderText(caption)
        self.edit.setAccessibleName(caption)
        self.browse_button.setToolTip(self.language.text("action.choose"))
        self.browse_button.setAccessibleName(self.language.text("action.choose")+" "+caption)

    def browse(self):
        tr=self.language.text
        initial=(self.edit.text().strip() or self.locations.output_directory()) if self.kind in ('directory','save') else self.locations.input_directory()
        if self.kind=="directory":value=QFileDialog.getExistingDirectory(self,tr(self.caption),initial)
        elif self.kind=="save":value,_=QFileDialog.getSaveFileName(self,tr(self.caption),initial,tr(self.filter_key))
        else:value,_=QFileDialog.getOpenFileName(self,tr(self.caption),initial,tr(self.filter_key))
        if value:
            if self.kind=='directory':self.locations.remember_output(value)
            elif self.kind=='save':self.locations.remember_output(Path(value).parent)
            else:self.locations.remember_input(value)
            self.edit.setText(value)
            self.changed.emit(value)

    def dragEnterEvent(self,event):
        urls=event.mimeData().urls()
        if len(urls)==1 and urls[0].isLocalFile():event.acceptProposedAction()

    def dropEvent(self,event):
        value=event.mimeData().urls()[0].toLocalFile()
        self.edit.setText(value)
        self.changed.emit(value)
        event.acceptProposedAction()

    def path(self,required=True):
        text=self.edit.text().strip()
        if text:return Path(text)
        if required:
            from .models import ToolError
            raise ToolError("error.required",field=msg(self.caption))
        return None


class FaceTile(QWidget):
    activated=Signal(str)
    assigned=Signal(str,str)

    def __init__(self,face,language,locations):
        super().__init__()
        self.locations=locations
        self.face,self.language=face,language
        self.filter_key = "filter.dds"
        self.selected=False
        self.hovered=False
        self.pressed=False
        self.theme=None
        self.path=""
        self.description=""
        self.editable=False
        self.setMinimumWidth(88)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        self.original=None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box=QVBoxLayout(self)
        box.setContentsMargins(7,5,7,6)
        box.setSpacing(3)
        row=QHBoxLayout()
        self.title=QLabel()
        self.browse_button=CompactButton()
        self.browse_button.setText("…")
        self.browse_button.setFixedSize(22,22)
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.title,1)
        row.addWidget(self.browse_button)
        box.addLayout(row)
        self.image=QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(52)
        box.addWidget(self.image)
        self.filename=QLabel()
        self.filename.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.filename)
        self.browse_button.hide()
        language.changed.connect(self.retranslate)
        self.retranslate()
        self.resize(112,148)

    def retranslate(self):
        self.title.setText(self.language.text("face."+self.face))
        self.browse_button.setToolTip(self.language.text("action.choose"))
        self.setAccessibleName(self.language.text("face."+self.face))
        self.browse_button.setAccessibleName(self.language.text("action.choose")+" "+self.accessibleName())
        self.update_filename()

    def update_filename(self):
        text=Path(self.path).name if self.path else (self.description or self.language.text("empty.slot"))
        self.filename.setText(self.filename.fontMetrics().elidedText(text,Qt.TextElideMode.ElideMiddle,max(50,self.width()-14)))
        self.filename.setToolTip(self.path or self.description or self.language.text("empty.face",face=self.face))

    def set_editable(self,editable):
        self.editable=editable
        self.setAcceptDrops(editable)
        self.browse_button.setVisible(editable)
        self.resize_thumbnail()

    def apply_theme(self,theme):
        self.theme=theme
        self.browse_button.setIcon(QIcon())
        self.update()

    def set_image(self,image):
        self.original=image
        self.resize_thumbnail()

    def resize_thumbnail(self):
        side=max(32,self.width()-14)
        self.image.setFixedSize(side,side)
        if self.original is None:self.image.clear()
        else:
            dpr=self.devicePixelRatioF()
            thumb=QPixmap.fromImage(self.original).scaled(round(side*dpr),round(side*dpr),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            thumb.setDevicePixelRatio(dpr);self.image.setPixmap(thumb)
        title=max(24,self.title.sizeHint().height(),self.browse_button.height() if self.editable else 0)
        tail=self.filename.sizeHint().height()+3 if not self.filename.isHidden() else 0
        self.setFixedHeight(side+title+tail+14)


    def browse(self):
        value,_=QFileDialog.getOpenFileName(self,self.language.text("face."+self.face),self.locations.input_directory(),self.language.text(self.filter_key))
        if value:
            self.locations.remember_input(value)
            self.assigned.emit(self.face,value)

    def paintEvent(self,event):
        if self.theme:
            painter=QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(self.theme.selected if self.selected else self.theme.surface))
            painter.setPen(QPen(QColor(self.theme.accent if self.selected or self.hasFocus() else self.theme.edge),1))
            painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),4,4)
            if self.hovered or self.pressed:
                color=QColor(self.theme.accent);color.setAlpha(34 if self.pressed else 16)
                painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(color)
                painter.drawRoundedRect(self.rect().adjusted(2,2,-2,-2),4,4)
            if self.hasFocus():
                painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor(self.theme.accent),2))
                painter.drawRoundedRect(self.rect().adjusted(3,3,-3,-3),3,3)

    def enterEvent(self,event):self.hovered=True;self.setCursor(Qt.CursorShape.PointingHandCursor);self.update();super().enterEvent(event)
    def leaveEvent(self,event):self.hovered=False;self.pressed=False;self.update();super().leaveEvent(event)
    def mouseReleaseEvent(self,event):self.pressed=False;self.update();super().mouseReleaseEvent(event)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.pressed=True
            self.setFocus()
            self.activated.emit(self.face)
        super().mousePressEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Space):
            self.activated.emit(self.face)
            event.accept()
        else:super().keyPressEvent(event)

    def dragEnterEvent(self,event):
        urls=event.mimeData().urls()
        if self.editable and len(urls)==1 and urls[0].isLocalFile():event.acceptProposedAction()

    def dropEvent(self,event):
        self.assigned.emit(self.face,event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.update_filename();self.resize_thumbnail()


class ElidedLabel(QLabel):
    def __init__(self):
        super().__init__();self.full_text=''
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
    def minimumSizeHint(self):return QSize(0,self.fontMetrics().height())
    def sizeHint(self):return QSize(160,self.fontMetrics().height())
    def clear(self):self.set_full_text('')
    def set_full_text(self,text):
        self.full_text=text;self.setToolTip(text);self.refresh()
    def refresh(self):
        self.setText(self.fontMetrics().elidedText(self.full_text,Qt.TextElideMode.ElideMiddle,max(0,self.width())))
    def resizeEvent(self,event):super().resizeEvent(event);self.refresh()


class CommandBar(QWidget):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        compact=self.width()<1000
        for button in self.file_buttons:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.summary.setVisible(not compact)
        for label in self.captions:label.setVisible(self.width()>=960)
