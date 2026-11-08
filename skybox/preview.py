"""A pixel-coordinate canvas with shared pan/zoom and clipped wipe drawing."""
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QAction
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QDoubleSpinBox, QToolButton, QMenu, QSizePolicy, QLayout, QAbstractSpinBox, QStackedWidget
from .document import PreviewKey, PREVIEW_CHANNELS
from .models import FACE_ORDER
from .messages import msg
from .cube_preview import CubePreview
from .theme import FluentButton, Segments, label_font, WorkbenchCombo, CompactButton
from .i18n import populate
from .widgets import ElidedLabel


class Canvas(QWidget):
    view_changed = Signal(object)
    sample = Signal(object)
    face_step = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus); self.setMouseTracking(True)
        self.images = []; self.background = 'dark'; self.comparison = 'single'
        self.state = dict(zoom=1., center=None, fit=True, wipe=.5)
        self.loading_text = ''; self.empty_text = ''; self.captions = []
        self.drag = None; self.space = False
        self.setMinimumSize(220, 180)

    def regions(self):
        width = self.width()/2 if self.comparison == 'side' and len(self.images) == 2 else self.width()
        first = QRectF(0, 0, width, self.height())
        return [first, QRectF(width, 0, width, self.height())] if width != self.width() else [first]

    def active_region(self, point):
        regions = self.regions()
        return regions[1] if len(regions) == 2 and point.x() >= regions[1].left() else regions[0]

    def scale(self): return self.state['zoom']/self.devicePixelRatioF()
    def center(self): return QPointF(*(self.state['center'] or (0., 0.)))

    def image_point(self, point):
        return self.center()+(point-self.active_region(point).center())/self.scale()

    def set_images(self, images, state, comparison, captions):
        self.images = images; self.state = {k: state[k] for k in ('zoom', 'center', 'fit', 'wipe')}
        self.comparison, self.captions = comparison, captions
        self.loading_text = ''
        if self.images:
            if self.state['fit']: self.fit()
            elif self.state['center'] is None:
                self.state['center'] = [self.images[0].width()/2, self.images[0].height()/2]
        self.update()

    def clear(self, text):
        self.images = []; self.empty_text = text; self.loading_text = ''; self.update()

    def announce(self):
        self.view_changed.emit(dict(self.state)); self.update()

    def fit(self):
        if not self.images: return
        image, region = self.images[0], self.regions()[0].adjusted(16, 16, -16, -16)
        self.state.update(zoom=min(region.width()/image.width(), region.height()/image.height())*self.devicePixelRatioF(),
                          center=[image.width()/2, image.height()/2], fit=True)
        self.announce()

    def actual(self): self.set_zoom(1.)
    def set_zoom(self, value):
        self.state.update(zoom=max(.01, min(32., value)), fit=False)
        self.announce()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        if self.background != 'transparent':
            base = {'dark': '#303030', 'light': '#D9D9D9', 'checker': '#999999'}[self.background]
            painter.fillRect(self.rect(), QColor(base))
        if self.background == 'checker':
            for y in range(0, self.height(), 16):
                for x in range(0, self.width(), 16):
                    if (x//16+y//16) % 2: painter.fillRect(x, y, 16, 16, QColor('#BBBBBB'))
        if not self.images:
            painter.setPen(self.palette().windowText().color() if self.background == 'transparent' else
                           QColor('#EAEAEA' if self.background == 'dark' else '#303030'))
            painter.drawText(self.rect().adjusted(28, 28, -28, -28), Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap, self.empty_text)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.state['zoom'] < 1)
            regions = self.regions()
            for index, image in enumerate(self.images):
                if index and self.comparison == 'single': break
                region = regions[index] if self.comparison == 'side' else regions[0]
                painter.save(); painter.setClipRect(region)
                if self.comparison == 'wipe' and len(self.images) == 2:
                    cut = self.width()*self.state['wipe']
                    painter.setClipRect(QRectF(0 if index == 0 else cut, 0, cut if index == 0 else self.width()-cut, self.height()))
                painter.translate(region.center()); painter.scale(self.scale(), self.scale()); painter.translate(-self.center())
                painter.drawImage(QPointF(0, 0), image); painter.restore()
            if self.comparison == 'wipe' and len(self.images) == 2:
                x = self.width()*self.state['wipe']
                painter.setPen(QPen(QColor('#FFFFFF'), 1)); painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
                painter.setBrush(QColor('#008A83')); painter.drawRoundedRect(QRectF(x-12, self.height()/2-17, 24, 34), 4, 4)
                painter.drawText(QRectF(x-12, self.height()/2-17, 24, 34), Qt.AlignmentFlag.AlignCenter, '‹ ›')
            for index, caption in enumerate(self.captions):
                if index and self.comparison == 'single': break
                width = painter.fontMetrics().horizontalAdvance(caption)+18
                x = 12 if index == 0 else (self.width()/2+12 if self.comparison == 'side' else self.width()-width-12)
                area = QRectF(x, 12, width, 26)
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(20, 24, 22, 215)); painter.drawRoundedRect(area, 4, 4)
                painter.setPen(QColor('#FFFFFF')); painter.drawText(area, Qt.AlignmentFlag.AlignCenter, caption)
        if self.loading_text:
            area = self.rect().adjusted(12, self.height()-48, -12, -12)
            painter.fillRect(area, QColor(25, 30, 27, 230)); painter.setPen(QColor('#FFFFFF'))
            painter.drawText(area.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, self.loading_text)

    def wheelEvent(self, event):
        if not self.images: return
        position = event.position(); before = self.image_point(position)
        zoom = max(.01, min(32., self.state['zoom']*1.2**(event.angleDelta().y()/120)))
        self.state['zoom'] = zoom
        center = before-(position-self.active_region(position).center())/self.scale()
        self.state.update(center=[center.x(), center.y()], fit=False)
        self.announce(); event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        if not self.images: return
        if event.button() == Qt.MouseButton.LeftButton and self.comparison == 'wipe' and len(self.images) == 2 and abs(event.position().x()-self.width()*self.state['wipe']) < 14:
            self.drag = ('wipe', event.position())
        elif event.button() == Qt.MouseButton.MiddleButton or (self.space and event.button() == Qt.MouseButton.LeftButton):
            self.drag = ('pan', event.position()); self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag:
            kind, old = self.drag
            if kind == 'wipe': self.state['wipe'] = max(0., min(1., event.position().x()/self.width()))
            else:
                center = self.center()-(event.position()-old)/self.scale()
                self.state.update(center=[center.x(), center.y()], fit=False)
            self.drag = kind, event.position(); self.announce()
        elif self.comparison == 'wipe' and len(self.images) == 2 and abs(event.position().x()-self.width()*self.state['wipe']) < 14:
            self.setCursor(Qt.CursorShape.SplitHCursor)
        else: self.setCursor(Qt.CursorShape.OpenHandCursor if self.space else Qt.CursorShape.ArrowCursor)
        if self.images and not self.loading_text:
            point = self.image_point(event.position()); x, y = int(point.x()), int(point.y())
            index = 1 if len(self.images) == 2 and ((self.comparison == 'wipe' and event.position().x() >= self.width()*self.state['wipe']) or (self.comparison == 'side' and event.position().x() >= self.width()/2)) else 0
            image = self.images[index]
            if 0 <= point.x() < image.width() and 0 <= point.y() < image.height():
                color = image.pixelColor(x, y); self.sample.emit((x, y, *color.getRgb()))
            else: self.sample.emit(None)
        elif self.loading_text: self.sample.emit(None)

    def mouseReleaseEvent(self, event): self.drag = None; self.unsetCursor()
    def mouseDoubleClickEvent(self, event):
        if self.comparison == 'wipe' and abs(event.position().x()-self.width()*self.state['wipe']) < 14:
            self.state['wipe'] = .5; self.announce()
        else: self.fit()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space: self.space = True; self.setCursor(Qt.CursorShape.OpenHandCursor); event.accept()
        elif event.key() == Qt.Key.Key_1: self.actual(); event.accept()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.face_step.emit({Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -2, Qt.Key.Key_Down: 2}[event.key()]); event.accept()
        else: super().keyPressEvent(event)
    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space: self.space = False; self.unsetCursor(); event.accept()
        else: super().keyReleaseEvent(event)
    def focusOutEvent(self, event): self.space = False; self.drag = None; self.unsetCursor(); super().focusOutEvent(event)
    def leaveEvent(self, event): self.sample.emit(None); super().leaveEvent(event)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.state['fit']: self.fit()


class PreviewPanel(QWidget):
    selection_changed = Signal(object)
    view_changed = Signal(object)
    sample = Signal(object)
    face_step = Signal(int)
    background_changed = Signal(str)

    def __init__(self, language):
        super().__init__(); self.language = language; self.view = {}; self.entries = {}; self.kind = ''
        self.setMinimumWidth(220); self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(4)
        box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        row = QHBoxLayout(); row.setContentsMargins(8, 4, 8, 4); row.setSpacing(6)
        self.layout_box = WorkbenchCombo(); self.stage_box = WorkbenchCombo(); self.compare_box = WorkbenchCombo()
        for combo in (self.layout_box, self.stage_box, self.compare_box): combo.setMinimumHeight(36)
        self.channels = Segments([(channel, 'channel.'+channel.lower()) for channel in PREVIEW_CHANNELS], language)
        self.fit_button = FluentButton(); self.fit_button.clicked.connect(lambda: self.canvas.fit())
        self.zoom_box = QDoubleSpinBox(); self.zoom_box.setRange(1, 3200); self.zoom_box.setDecimals(1); self.zoom_box.setSuffix('%')
        self.zoom_box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); self.zoom_box.setKeyboardTracking(False); self.zoom_box.setMinimumHeight(36); self.zoom_box.setMinimumWidth(132)
        self.zoom_box.valueChanged.connect(lambda value: self.canvas.set_zoom(value/100))
        self.background_box = WorkbenchCombo(); self.background_box.setMinimumHeight(36)
        self.background_mode = 'auto'
        self.background_box.currentIndexChanged.connect(lambda: self.background_changed.emit(self.background_box.currentData()))
        self.more = CompactButton(); self.more.setText('…'); self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setMinimumSize(32, 32); self.more_menu = QMenu(self.more); self.more.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(self.more.update)
        self.more_menu.aboutToHide.connect(self.more.update)
        self.actual_action = self.more_menu.addAction(''); self.actual_action.triggered.connect(lambda: self.canvas.actual())
        self.original_action = self.more_menu.addAction(''); self.original_action.triggered.connect(self.original)
        self.next_stage_action = self.more_menu.addAction(''); self.next_stage_action.triggered.connect(self.switch_stage)
        self.fit_action = self.more_menu.addAction(''); self.fit_action.triggered.connect(lambda: self.canvas.fit())
        self.channel_menu = self.more_menu.addMenu(''); self.channel_actions = {}
        for channel in PREVIEW_CHANNELS:
            action = self.channel_menu.addAction(channel); action.setCheckable(True)
            action.triggered.connect(lambda checked=False, c=channel: self.change(channel=c)); self.channel_actions[channel] = action
        self.layout_menu = self.more_menu.addMenu(''); self.layout_actions = {}
        for layout in ('face', 'atlas', 'mosaic', 'panorama', 'cube'):
            action = self.layout_menu.addAction(''); action.setCheckable(True)
            action.triggered.connect(lambda checked=False, value=layout: self.change(layout=value)); self.layout_actions[layout] = action
        self.compare_menu = self.more_menu.addMenu(''); self.compare_actions = {}
        for comparison in ('single', 'wipe', 'side'):
            action = self.compare_menu.addAction(''); action.setCheckable(True)
            action.triggered.connect(lambda checked=False, c=comparison: self.change(compare=c)); self.compare_actions[comparison] = action
        for widget in (self.layout_box, self.channels, self.stage_box, self.compare_box): row.addWidget(widget)
        row.addStretch(); row.addWidget(self.zoom_box); row.addWidget(self.fit_button); row.addWidget(self.background_box); row.addWidget(self.more)
        box.addLayout(row)
        self.canvas = Canvas()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.canvas)
        self.cube = None
        self.cube_problem = None
        self.cube_message = QLabel()
        self.cube_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cube_message.setWordWrap(True)
        self.stack.addWidget(self.cube_message)
        box.addWidget(self.stack, 1)
        info_row = QHBoxLayout(); info_row.setContentsMargins(8, 2, 8, 4)
        self.info = QLabel(); self.pixel_info = ElidedLabel(); self.pixel_info.setMinimumWidth(0); label_font(self.info, 14); label_font(self.pixel_info, 14)
        info_row.addWidget(self.info); info_row.addStretch(); info_row.addWidget(self.pixel_info); box.addLayout(info_row)
        self.layout_box.currentIndexChanged.connect(lambda: self.change(layout=self.layout_box.currentData()))
        self.stage_box.currentIndexChanged.connect(lambda: self.change(stage=self.stage_box.currentData()))
        self.compare_box.currentIndexChanged.connect(lambda: self.change(compare=self.compare_box.currentData()))
        self.channels.changed.connect(lambda value: self.change(channel=value))
        self.canvas.view_changed.connect(self.on_view); self.canvas.sample.connect(self.sample.emit); self.canvas.face_step.connect(self.face_step.emit)
        language.changed.connect(self.retranslate); self.retranslate()

    def change(self, **values):
        if self.view:
            self.selection_changed.emit(values)

    def configure(self, entries, view, kind, repaired=True):
        self.entries, self.view, self.kind = entries, view, kind
        self.repaired = repaired
        tr = self.language.text
        layouts = [name for name in ('face', 'atlas', 'mosaic', 'panorama') if any(k.layout == name for k in entries)]
        if entries:
            layouts.append('cube')
        populate(self.layout_box, [(tr('layout.'+name), name) for name in layouts])
        if self.layout_box.findData(view['layout']) >= 0:
            self.layout_box.blockSignals(True); self.layout_box.setCurrentIndex(self.layout_box.findData(view['layout'])); self.layout_box.blockSignals(False)
        else: view['layout'] = self.layout_box.currentData() or 'face'
        for value, action in self.layout_actions.items():
            action.setText(tr('layout.'+value)); action.setChecked(value == view['layout']); action.setEnabled(self.layout_box.findData(value) >= 0)
        self.update_controls()
        if view['layout'] == 'cube':
            for action in (*self.channel_actions.values(), *self.compare_actions.values(),
                           self.actual_action, self.fit_action, self.next_stage_action):
                action.setEnabled(False)
            self.original_action.setEnabled(any(k.stage == 'original' for k in entries))
            return []
        self.leave_cube()
        for action in (self.actual_action, self.fit_action, self.next_stage_action, self.channel_actions['RGB']):
            action.setEnabled(True)
        face = view['face'] if view['layout'] == 'face' else ''
        relevant = [k for k in entries if k.layout == view['layout'] and k.face == face]
        available_channels = {key.channel for key in relevant}
        if view['channel'] not in available_channels:
            view['channel'] = 'RGB'
        self.channels.select(view['channel'])
        for channel in PREVIEW_CHANNELS:
            enabled = channel in available_channels
            self.channels.buttons[channel].setEnabled(enabled)
            self.channel_actions[channel].setEnabled(enabled)
        stages = [stage for stage in ('source', 'dds', 'original') if any(k.stage == stage and k.channel == view['channel'] for k in relevant)]
        items = [(tr('stage.repaired' if kind == 'atlas' and self.repaired else 'stage.input') if s == 'source' else tr('stage.'+s), s) for s in stages]
        populate(self.stage_box, items)
        if view['stage'] not in stages: view['stage'] = stages[0] if stages else 'source'
        self.stage_box.blockSignals(True); self.stage_box.setCurrentIndex(self.stage_box.findData(view['stage'])); self.stage_box.blockSignals(False)
        pair = 'source' in stages and 'dds' in stages and view['layout'] == 'face' and view['stage'] != 'original'
        populate(self.compare_box, [(tr('compare.'+s), s) for s in ('single', 'wipe', 'side')])
        self.comparison = view['compare'] if pair else 'single'
        self.compare_box.blockSignals(True); self.compare_box.setCurrentIndex(self.compare_box.findData(self.comparison)); self.compare_box.blockSignals(False)
        self.compare_box.setEnabled(pair); self.stage_box.setEnabled(self.comparison == 'single')
        for value, action in self.compare_actions.items(): action.setChecked(value == self.comparison); action.setEnabled(pair or value == 'single')
        for value, action in self.channel_actions.items(): action.setChecked(value == view['channel'])
        self.original_action.setEnabled(any(k.stage == 'original' for k in entries))
        self.current = []
        for stage in ('source', 'dds') if self.comparison != 'single' else (view['stage'],):
            key = PreviewKey(view['layout'], face, view['channel'], stage)
            if key in entries: self.current.append(entries[key])
        self.update_info()
        return self.current

    def in_cube(self):
        return self.view.get('layout') == 'cube'

    def begin_cube(self):
        complete = all(PreviewKey('face', face, 'RGB', 'source') in self.entries for face in FACE_ORDER)
        if not complete:
            self.show_cube_message(msg('error.cube_incomplete'))
            return False
        if self.cube is None:
            self.cube = CubePreview()
            self.cube.camera_changed.connect(self.on_camera)
            self.cube.failed.connect(self.on_cube_error, Qt.ConnectionType.QueuedConnection)
            self.stack.addWidget(self.cube)
        self.cube_problem = None
        self.cube.clear_source()
        self.cube.set_camera(self.view['camera_z_up'])
        self.stack.setCurrentWidget(self.cube)
        self.info.setText(self.language.text('status.loading'))
        return True

    def leave_cube(self):
        self.cube_problem = None
        if self.cube is not None:
            self.cube.clear_source()
        self.stack.setCurrentWidget(self.canvas)

    def show_cube_message(self, message):
        if self.cube is not None:
            self.cube.clear_source()
        self.cube_problem = message
        self.cube_message.setText(self.language.render(message))
        self.stack.setCurrentWidget(self.cube_message)
        self.info.clear()

    def on_cube_error(self, generation, error):
        if (self.in_cube() and self.stack.currentWidget() is self.cube
                and self.cube.generation == generation):
            self.show_cube_message(error)

    def display_cube(self, faces):
        if self.in_cube() and self.stack.currentWidget() is self.cube:
            self.cube.set_faces(faces)
            self.update_info()

    def on_camera(self, camera):
        self.view['camera_z_up'] = camera
        self.update_info()

    def look_at(self, face):
        if self.cube is not None and self.stack.currentWidget() is self.cube:
            self.cube.look_at(face)

    def on_view(self, state):
        self.view_changed.emit(state); self.update_info()

    def update_info(self):
        if not self.view: self.info.clear(); return
        if self.in_cube():
            if self.cube is not None and self.stack.currentWidget() is self.cube:
                self.info.setText(self.language.text('status.cube_camera',
                    fov=self.cube.camera[2], face=self.cube.direction()))
            return
        self.zoom_box.blockSignals(True); self.zoom_box.setValue(self.canvas.state['zoom']*100); self.zoom_box.blockSignals(False)
        if self.entries:
            entry = next(iter(self.entries.values()))
            selected = getattr(self, 'current', [])
            if selected: entry = selected[0]
            self.info.setText(self.language.text('status.preview_size', width=entry.width, height=entry.height, zoom=self.canvas.state['zoom']*100))

    def retranslate(self):
        tr = self.language.text
        populate(self.background_box, [(tr('background.'+name), name) for name in ('auto', 'light', 'dark', 'checker', 'transparent')])
        self.set_background_mode(self.background_mode)
        self.background_box.setAccessibleName(tr('menu.background')); self.background_box.setToolTip(tr('menu.background'))
        self.fit_button.setText(tr('action.fit')); self.fit_button.setToolTip(tr('action.fit'))
        for target, key in ((self.layout_box, 'field.layout'), (self.stage_box, 'field.stage'), (self.compare_box, 'field.compare'), (self.zoom_box, 'field.zoom'), (self.more, 'action.more')):
            target.setAccessibleName(tr(key)); target.setToolTip(tr(key))
        self.actual_action.setText(tr('action.actual')); self.original_action.setText(tr('action.original')); self.next_stage_action.setText(tr('action.stage'))
        self.layout_menu.setTitle(tr('field.layout'))
        self.fit_action.setText(tr('action.fit')); self.channel_menu.setTitle(tr('field.channel')); self.compare_menu.setTitle(tr('field.compare'))
        for value, action in self.channel_actions.items(): action.setText(tr('channel.'+value.lower()))
        for value, action in self.compare_actions.items(): action.setText(tr('compare.'+value))
        self.canvas.empty_text = tr('empty.workspace'); self.canvas.update()
        if self.entries: self.configure(self.entries, self.view, self.kind, self.repaired)
        if self.in_cube():
            if self.cube_problem is not None:
                self.cube_message.setText(self.language.render(self.cube_problem))
            else:
                self.update_info()
        if hasattr(self, 'loaded_keys'): self.canvas.captions = [self.caption(key.stage) for key in self.loaded_keys]

    def caption(self, stage):
        key = ('stage.repaired' if self.kind == 'atlas' and self.repaired else 'stage.input') if stage == 'source' else 'stage.'+stage
        return self.language.text(key)

    def display(self, loaded):
        self.loaded_keys = [key for key, image in loaded]
        captions = [self.caption(key.stage) for key, image in loaded]
        self.canvas.set_images([image for key, image in loaded], self.view, self.comparison, captions); self.update_info()

    def set_background_mode(self, name):
        self.background_mode = name
        self.background_box.blockSignals(True); self.background_box.setCurrentIndex(self.background_box.findData(name)); self.background_box.blockSignals(False)

    def original(self):
        key = next((key for key in self.entries if key.stage == 'original'), None)
        if key is not None:
            self.change(layout=key.layout, stage='original')
    def switch_stage(self):
        if not self.in_cube() and self.stage_box.count() > 1:
            index = (self.stage_box.currentIndex()+1) % self.stage_box.count()
            self.change(compare='single', stage=self.stage_box.itemData(index))
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_controls()

    def update_controls(self):
        width = self.width()
        flat = not self.in_cube()
        self.zoom_box.setVisible(flat and width >= 860)
        self.stage_box.setVisible(flat and width >= 860)
        self.layout_box.setVisible(width >= 420)
        self.channels.setVisible(flat and width >= 760)
        self.compare_box.setVisible(flat and width >= 560)
        self.fit_button.setVisible(flat and width >= 440)
        self.background_box.setVisible(flat)
        self.pixel_info.setVisible(flat)
