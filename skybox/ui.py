"""Multi-document Fluent workbench; view state and authoring snapshots are separate."""
import json
import sys
from dataclasses import replace
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, Signal, QEvent, QThread, QSettings, QStandardPaths, QLocale, QUrl, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QPalette, QIcon, QDesktopServices, QImage, QTextCursor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QScrollArea, QLabel, QComboBox, QSplitter, QTabBar, QToolBar, QToolButton,
    QProgressBar, QPlainTextEdit, QListWidget, QListWidgetItem, QFileDialog, QDialog, QTextBrowser,
    QMessageBox, QLineEdit, QSizePolicy, QDoubleSpinBox, QCheckBox)
from .models import FACE_ORDER, ToolError
from .document import Document, Source, PreviewKey, PreviewEntry, ImageSource, PREVIEW_CHANNELS
from .pipeline import Job, output_paths
from .messages import msg, exception_message
from .i18n import Language, populate
from .theme import THEMES, FluentStyle, FluentButton, palette, label_font, ui_font, WorkbenchCombo, apply_title_bar, CompactButton
from .widgets import PathField, FaceTile, ElidedLabel, CommandBar, DialogLocations
from .preview import PreviewPanel
from .engine import PreviewWorker, AuthorWorker
from .icons import icon


class MainWindow(QMainWindow):
    execute = Signal(object, object)

    def __init__(self):
        super().__init__()
        area = self.screen().availableGeometry()
        self.setMinimumSize(min(820, area.width()-48), min(600, area.height()-48))
        self.resize(min(1440, area.width()-48), min(900, area.height()-48))
        config = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        config.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(config/'settings.ini'), QSettings.Format.IniFormat)
        self.locations = DialogLocations(self.settings)
        default = 'zh-CN' if QLocale.system().language() == QLocale.Language.Chinese else 'en'
        self.language = Language(self.settings.value('language', default))
        self.documents = []; self.updating = False; self.texts = []; self.icon_targets = []
        self.preview_sequence = 0; self.preview_token = None
        self.preview_error = None
        self.active_job = None; self.job_token = None; self.history = []; self.close_pending = False
        self.last_message = msg('status.ready'); self.task_failed = False
        self.appearance_mode = self.settings.value('appearance_mode', self.settings.value('theme', 'dark'))
        self.theme_name = 'dark'; self.background = self.settings.value('canvas_background_mode', 'auto')
        self.build_menus(); self.build_toolbar(); self.build_workspace(); self.build_tasks()
        self.preview_thread = QThread(self); self.preview_worker = PreviewWorker(); self.preview_worker.moveToThread(self.preview_thread)
        self.preview_worker.inspected.connect(self.on_inspected); self.preview_worker.loaded.connect(self.on_images)
        self.preview_worker.cube_loaded.connect(self.on_cube_loaded)
        self.preview_worker.failed.connect(self.on_preview_failed); self.preview_worker.progress.connect(self.on_inspect_progress)
        self.preview_worker.stopped.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self.preview_worker.deleteLater)
        self.preview_thread.finished.connect(self.finish_close); self.preview_thread.start()
        self.author_thread = QThread(self); self.author = AuthorWorker(); self.author.moveToThread(self.author_thread)
        self.execute.connect(self.author.execute); self.author.progress.connect(self.on_progress)
        self.author.face_ready.connect(self.on_face_ready); self.author.completed.connect(self.on_complete)
        self.author.failed.connect(self.on_job_failed); self.author.cancelled.connect(self.on_cancelled); self.author.finished.connect(self.on_finished)
        self.author_thread.finished.connect(self.author.deleteLater); self.author_thread.start()
        self.language.changed.connect(self.retranslate)
        self.apply_theme(self.appearance_mode, save=False); self.retranslate()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.on_system_scheme)
        if self.settings.contains('geometry'): self.restoreGeometry(self.settings.value('geometry'))
        if self.settings.contains('janus_columns'):
            self.settings.setValue('columns', self.settings.value('janus_columns'))
            self.settings.remove('janus_columns')
        if self.settings.contains('columns'): self.columns.restoreState(self.settings.value('columns'))
        self.set_panels(self.settings.value('assets_visible', True, type=bool), self.settings.value('output_visible', True, type=bool))
        for record in json.loads(self.settings.value('workspace', '[]')):
            doc = Document(Source.restore(record['source']))
            doc.settings.update(record['settings']); doc.view.update(record['view']); doc.settings_initialized = True
            doc.view.pop('camera', None)
            self.add_document(doc, activate=False)
        active = min(self.settings.value('active_tab', 0, type=int), len(self.documents)-1)
        if self.documents:
            self.tabs.blockSignals(True); self.tabs.setCurrentIndex(max(0, active)); self.tabs.blockSignals(False)
            QTimer.singleShot(0, self.activate)
        else: self.show_empty()
        self.encoding_toggle.setChecked(self.settings.value('encoding_expanded', True, type=bool))
        self.setAcceptDrops(True)

    @property
    def doc(self):
        index = self.tabs.currentIndex()
        return self.documents[index] if 0 <= index < len(self.documents) else None

    def find(self, token):
        return next((doc for doc in self.documents if doc.uid == token[0] and doc.revision == token[1]), None)

    def bind(self, widget, code, method='setText'):
        self.texts.append((widget, code, method)); getattr(widget, method)(self.language.text(code)); return widget

    def action(self, code, callback, shortcut=None, glyph=None):
        action = QAction(self); self.bind(action, code); action.triggered.connect(callback)
        if shortcut: action.setShortcut(shortcut)
        if glyph: self.icon_targets.append((action, glyph))
        return action

    def build_menus(self):
        menus = {}
        for name in ('file', 'view', 'tools', 'help'):
            menu = self.menuBar().addMenu(''); self.bind(menu, 'menu.'+name, 'setTitle'); menus[name] = menu
        self.open_action = self.action('action.open', self.open_files, 'Ctrl+O', 'import')
        self.panorama_action = self.action('action.open_panorama', self.open_panorama)
        self.png_action = self.action('action.open_png_faces', lambda: self.open_face_slots('png_faces'))
        self.dds_action = self.action('action.open_dds', self.open_dds, glyph='cube')
        self.refresh_action = self.action('action.reload', self.reload, 'F5', 'refresh')
        menus['file'].addActions([self.open_action, self.panorama_action, self.png_action, self.dds_action, self.refresh_action]); menus['file'].addSeparator()
        menus['file'].addAction(self.action('action.close_tab', lambda: self.close_document(self.tabs.currentIndex()), 'Ctrl+W'))
        menus['file'].addAction(self.action('action.exit', self.close, 'Alt+F4'))
        for key, callback, shortcut in (('fit', lambda: self.preview.canvas.fit() if not self.preview.in_cube() else None, 'Ctrl+0'),
            ('actual', lambda: self.preview.canvas.actual() if not self.preview.in_cube() else None, 'Ctrl+1'), ('stage', lambda: self.preview.switch_stage(), 'Ctrl+Tab')):
            menus['view'].addAction(self.action('action.'+key, callback, shortcut))
        self.assets_action = self.action('dock.assets', lambda checked: self.assets.setVisible(checked)); self.assets_action.setCheckable(True)
        self.output_action = self.action('dock.output', lambda checked: self.output_panel.setVisible(checked)); self.output_action.setCheckable(True)
        menus['view'].addActions([self.assets_action, self.output_action])
        menus['view'].addAction(self.action('action.focus_canvas', self.focus_canvas, 'Ctrl+Shift+F'))
        menus['view'].addAction(self.action('action.reset_layout', self.reset_layout))
        self.theme_actions = {}; self.background_actions = {}; self.language_actions = {}
        for kind, names, callback in (('theme', ('system', 'dark', 'light'), self.apply_theme), ('background', ('auto', 'dark', 'light', 'checker', 'transparent'), self.set_background)):
            menu = menus['view'].addMenu(''); self.bind(menu, 'menu.'+kind, 'setTitle'); group = QActionGroup(self)
            for name in names:
                action = self.action(kind+'.'+name, lambda checked=False, n=name, f=callback: f(n))
                action.setCheckable(True); group.addAction(action); menu.addAction(action)
                getattr(self, kind+'_actions')[name] = action
        menu = menus['tools'].addMenu(''); self.bind(menu, 'menu.language', 'setTitle'); group = QActionGroup(self)
        for name, title in (('zh-CN', '简体中文'), ('en', 'English')):
            action = QAction(title, self); action.setCheckable(True)
            action.triggered.connect(lambda checked=False, n=name: self.change_language(n)); group.addAction(action); menu.addAction(action)
            self.language_actions[name] = action
        menus['help'].addAction(self.action('action.help', self.show_help, 'F1'))
        menus['help'].addAction(self.action('action.about', self.about))

    def build_toolbar(self):
        toolbar = CommandBar(); self.command_bar = toolbar
        row = QHBoxLayout(toolbar); row.setContentsMargins(8, 6, 8, 6); row.setSpacing(8)
        toolbar.file_buttons = []
        for action in (self.open_action, self.panorama_action, self.png_action, self.dds_action, self.refresh_action):
            button = QToolButton(); button.setDefaultAction(action); button.setMinimumSize(36, 36)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly); row.addWidget(button); toolbar.file_buttons.append(button)
        self.document_summary = ElidedLabel(); self.document_summary.setMinimumWidth(0)
        row.addWidget(self.document_summary)
        self.language_box = WorkbenchCombo(); self.language_box.setMinimumHeight(36)
        self.language_box.addItem('简体中文', 'zh-CN'); self.language_box.addItem('English', 'en')
        self.language_box.currentIndexChanged.connect(lambda: self.change_language(self.language_box.currentData()))
        language_label = self.bind(QLabel(), 'menu.language'); row.addWidget(language_label); row.addWidget(self.language_box)
        self.appearance_box = WorkbenchCombo(); self.appearance_box.setMinimumHeight(36)
        self.appearance_box.currentIndexChanged.connect(lambda: self.apply_theme(self.appearance_box.currentData()))
        appearance_label = self.bind(QLabel(), 'appearance.label'); row.addWidget(appearance_label); row.addWidget(self.appearance_box)
        self.export_button = FluentButton(); self.export_button.setProperty('primary', True); self.export_button.setMinimumHeight(40)
        self.export_button.setMinimumWidth(144); self.export_button.clicked.connect(lambda: self.start_job())
        row.addWidget(self.export_button)
        toolbar.summary = self.document_summary; toolbar.captions = [language_label, appearance_label]

    def build_workspace(self):
        root = QWidget(); outer = QVBoxLayout(root); outer.setContentsMargins(8, 0, 8, 4); outer.setSpacing(4)
        outer.addWidget(self.command_bar)
        self.tabs = QTabBar(); self.tabs.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.tabs.setExpanding(False); self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(True); self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.currentChanged.connect(self.activate); self.tabs.tabCloseRequested.connect(self.close_document); outer.addWidget(self.tabs)
        self.columns = QSplitter(); self.columns.setChildrenCollapsible(False)
        self.assets = self.build_assets(); self.preview = PreviewPanel(self.language); self.output_panel = self.build_output()
        self.columns.addWidget(self.assets); self.columns.addWidget(self.preview); self.columns.addWidget(self.output_panel)
        self.columns.setStretchFactor(1, 1); self.columns.setSizes([256, 872, 312]); outer.addWidget(self.columns, 1)
        self.preview.selection_changed.connect(self.on_selection); self.preview.view_changed.connect(self.on_view)
        self.preview.sample.connect(self.on_sample); self.preview.background_changed.connect(self.set_background); self.preview.face_step.connect(self.step_face)
        self.setCentralWidget(root)

    def scroll_panel(self, content):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content); scroll.setMinimumWidth(200); return scroll

    def build_assets(self):
        content = QWidget(); box = QVBoxLayout(content); box.setContentsMargins(12, 12, 12, 12); box.setSpacing(8)
        title = self.bind(QLabel(), 'dock.assets'); label_font(title, 18, True); box.addWidget(title)
        self.source_label = self.bind(QLabel(), 'field.source'); box.addWidget(self.source_label)
        self.source_field = PathField(self.language, 'field.source', filter_key='filter.sources', locations=self.locations); box.addWidget(self.source_field)
        self.source_field.changed.connect(self.change_source_path)
        self.dds_assign = self.bind(FluentButton(), 'action.assign_dds'); self.dds_assign.clicked.connect(self.relocate_source); box.addWidget(self.dds_assign)
        self.repair_toggle = self.bind(QCheckBox(), 'field.repair_seams')
        self.repair_toggle.toggled.connect(self.change_repair)
        box.addWidget(self.repair_toggle); self.repair_toggle.hide()
        self.alpha_label = self.bind(QLabel(), 'field.alpha'); box.addWidget(self.alpha_label)
        self.alpha_field = PathField(self.language, 'field.alpha', locations=self.locations); box.addWidget(self.alpha_field); self.alpha_field.changed.connect(self.change_alpha)
        self.panorama_options = QWidget()
        panorama_form = QFormLayout(self.panorama_options)
        panorama_form.setContentsMargins(0, 0, 0, 0)
        panorama_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        panorama_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.panorama_size = WorkbenchCombo(); self.panorama_size.setMinimumHeight(36)
        for size in (512, 1024, 2048, 4096): self.panorama_size.addItem(str(size), size)
        self.panorama_yaw = QDoubleSpinBox(); self.panorama_yaw.setMinimumHeight(36)
        self.panorama_yaw.setRange(0, 359.9); self.panorama_yaw.setDecimals(1); self.panorama_yaw.setSuffix('°')
        self.panorama_yaw.setWrapping(True); self.panorama_yaw.setKeyboardTracking(False)
        for widget, key in ((self.panorama_size, 'field.panorama_size'), (self.panorama_yaw, 'field.panorama_yaw')):
            label = self.bind(QLabel(), key); label.setBuddy(widget); label.setWordWrap(True)
            panorama_form.addRow(label, widget)
        self.panorama_size.currentIndexChanged.connect(self.change_panorama)
        self.panorama_yaw.valueChanged.connect(self.change_panorama)
        box.addWidget(self.panorama_options); self.panorama_options.hide()
        self.asset_info = QLabel(); self.asset_info.setWordWrap(True); self.asset_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label_font(self.asset_info, 14); box.addWidget(self.asset_info); box.addSpacing(8)
        self.relocate = self.bind(FluentButton(), 'action.relocate'); self.relocate.clicked.connect(self.relocate_source); box.addWidget(self.relocate)
        self.faces_title = self.bind(QLabel(), 'group.faces'); label_font(self.faces_title, 17, True); box.addWidget(self.faces_title)
        grid = QGridLayout(); grid.setSpacing(6); self.tiles = {}
        for index, face in enumerate(FACE_ORDER):
            tile = FaceTile(face, self.language, self.locations); tile.activated.connect(self.select_face); tile.assigned.connect(self.assign_face)
            self.tiles[face] = tile; grid.addWidget(tile, index//2, index%2)
        box.addLayout(grid); box.addStretch(); return self.scroll_panel(content)

    def build_output(self):
        container = QWidget(); container.setMinimumWidth(260)
        box = QVBoxLayout(container); box.setContentsMargins(16, 16, 16, 16); box.setSpacing(12)
        title = self.bind(QLabel(), 'dock.output'); label_font(title, 18, True); box.addWidget(title)
        fields = QWidget(); self.output_fields = fields
        self.form = QFormLayout(fields); self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setVerticalSpacing(8); self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.combos = {}
        def field(name, key, form):
            combo = WorkbenchCombo(); combo.setMinimumHeight(36); combo.setMinimumContentsLength(10)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.combos[name] = combo; label = self.bind(QLabel(), key); label.setWordWrap(True); label.setBuddy(combo); form.addRow(label, combo)
            combo.currentIndexChanged.connect(lambda index, n=name: self.setting_changed(n))
        heading = self.bind(QLabel(), 'group.output_content'); label_font(heading, 17, True); self.form.addRow(heading)
        field('output', 'field.output_type', self.form); field('game', 'field.game', self.form)
        field('channel', 'field.export_channel', self.form)
        self.encoding_section = QWidget(); section = QVBoxLayout(self.encoding_section); section.setContentsMargins(0, 12, 0, 12); section.setSpacing(8)
        self.encoding_toggle = FluentButton(); self.encoding_toggle.setProperty('section', True); self.encoding_toggle.setCheckable(True); self.encoding_toggle.setChecked(True)
        self.encoding_toggle.setMinimumHeight(36)
        section.addWidget(self.encoding_toggle)
        self.encoding_body = QWidget(); self.encoding_form = QFormLayout(self.encoding_body)
        self.encoding_form.setContentsMargins(0, 0, 0, 0); self.encoding_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.encoding_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow); self.encoding_form.setVerticalSpacing(8)
        for name, key in (('policy', 'field.encoding_policy'), ('fourcc', 'field.format'), ('mode', 'field.device'), ('quality', 'field.quality')):
            field(name, key, self.encoding_form)
        self.preview_button = self.bind(FluentButton(), 'action.compress_face'); self.preview_button.clicked.connect(lambda: self.start_job('preview'))
        self.encoding_form.addRow(self.preview_button); section.addWidget(self.encoding_body)
        self.encoding_toggle.toggled.connect(self.toggle_encoding); self.form.addRow(self.encoding_section)
        heading = self.bind(QLabel(), 'group.save_location'); label_font(heading, 17, True); self.form.addRow(heading)
        self.directory = PathField(self.language, 'field.directory', 'directory', locations=self.locations); self.directory.changed.connect(self.change_output_directory)
        self.filename = QLineEdit(); self.filename.setMinimumHeight(36); self.filename.textEdited.connect(lambda text: self.save_settings())
        for widget, key in ((self.directory, 'field.directory'), (self.filename, 'field.basename')):
            label = self.bind(QLabel(), key); label.setWordWrap(True); label.setBuddy(self.filename if widget is self.filename else self.directory.edit); self.form.addRow(label, widget)
        heading = self.bind(QLabel(), 'group.result_summary'); label_font(heading, 17, True); self.form.addRow(heading)
        self.encoding_info = QLabel(); self.encoding_info.setWordWrap(True); label_font(self.encoding_info, 14); self.form.addRow(self.encoding_info)
        self.open_output_button = self.bind(FluentButton(), 'action.open_folder'); self.open_output_button.clicked.connect(self.open_output); self.form.addRow(self.open_output_button)
        scroll = self.scroll_panel(fields); scroll.setMinimumWidth(0); box.addWidget(scroll, 1)
        return container

    def toggle_encoding(self, expanded):
        self.encoding_body.setVisible(expanded)
        self.settings.setValue('encoding_expanded', expanded); self.update_output_controls()

    def build_tasks(self):
        self.task_toggle = CompactButton(); self.task_toggle.setCheckable(True); self.task_toggle.setText('▸'); self.task_toggle.toggled.connect(self.toggle_tasks)
        self.status_label = QLabel(); self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0); self.progress.setFixedWidth(140); self.progress.setMaximumHeight(12); self.progress.setTextVisible(False)
        self.cancel_button = self.bind(FluentButton(), 'action.cancel_task'); self.cancel_button.clicked.connect(self.cancel_task); self.cancel_button.hide()
        self.statusBar().addWidget(self.task_toggle); self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress); self.statusBar().addPermanentWidget(self.cancel_button)
        self.details = QWidget(); layout = QHBoxLayout(self.details); layout.setContentsMargins(4, 0, 4, 0)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(600)
        self.outputs = QListWidget(); self.outputs.itemDoubleClicked.connect(lambda item: self.open_folder(Path(item.data(Qt.ItemDataRole.UserRole)).parent))
        layout.addWidget(self.log, 2); layout.addWidget(self.outputs, 1); self.details.setMaximumHeight(160); self.details.hide()
        self.centralWidget().layout().addWidget(self.details)

    def apply_theme(self, mode, save=True):
        self.appearance_mode = mode
        hints = QApplication.instance().styleHints()
        hints.setColorScheme({'system': Qt.ColorScheme.Unknown, 'dark': Qt.ColorScheme.Dark, 'light': Qt.ColorScheme.Light}[mode])
        actual = ('dark' if hints.colorScheme() == Qt.ColorScheme.Dark else 'light') if mode == 'system' else mode
        self.paint_theme(actual)
        self.appearance_box.blockSignals(True); self.appearance_box.setCurrentIndex(self.appearance_box.findData(mode)); self.appearance_box.blockSignals(False)
        if save: self.settings.setValue('appearance_mode', mode)

    def on_system_scheme(self, scheme):
        if self.appearance_mode == 'system': self.paint_theme('dark' if scheme == Qt.ColorScheme.Dark else 'light')

    def paint_theme(self, name):
        self.theme_name, self.theme = name, THEMES[name]
        app = QApplication.instance(); self.fluent_style = FluentStyle(self.theme); app.setStyle(self.fluent_style)
        app.setPalette(palette(self.theme))
        app.setFont(ui_font())
        for target, glyph in self.icon_targets: target.setIcon(icon(glyph, self.theme.ink, self.devicePixelRatioF()))
        for tile in self.tiles.values(): tile.apply_theme(self.theme)
        for widget in (self.assets.widget(), self.output_panel, self.output_fields, self.command_bar):
            colors = widget.palette(); colors.setColor(QPalette.ColorRole.Window, QColor(self.theme.surface)); widget.setPalette(colors); widget.setAutoFillBackground(True)
        for label in (self.encoding_info, self.asset_info):
            colors = label.palette(); colors.setColor(QPalette.ColorRole.WindowText, QColor(self.theme.muted)); label.setPalette(colors)
        for key, action in self.theme_actions.items(): action.setChecked(key == self.appearance_mode)
        self.update_canvas_background(); self.refresh_status()
        self.sync_title_bar()

    def sync_title_bar(self):
        if self.isVisible() and hasattr(self, 'theme'):
            apply_title_bar(int(self.winId()), self.theme, self.isActiveWindow())

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_title_bar()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.WinIdChange, QEvent.Type.ActivationChange):
            QTimer.singleShot(0, self.sync_title_bar)
        return result

    def change_language(self, name):
        self.language.set(name); self.settings.setValue('language', name)

    def update_canvas_background(self):
        self.preview.canvas.background = self.theme_name if self.background == 'auto' else self.background
        self.preview.canvas.update()
        for key, action in self.background_actions.items(): action.setChecked(key == self.background)
        self.preview.set_background_mode(self.background)

    def set_background(self, name):
        self.background = name; self.update_canvas_background()
        self.settings.setValue('canvas_background_mode', name)

    def retranslate(self):
        self.updating = True; tr = self.language.text
        populate(self.appearance_box, [(tr('theme.'+name), name) for name in ('system', 'light', 'dark')])
        for combo, value in ((self.appearance_box, self.appearance_mode), (self.language_box, self.language.name)):
            combo.blockSignals(True); combo.setCurrentIndex(combo.findData(value)); combo.blockSignals(False)
        self.appearance_box.setAccessibleName(tr('appearance.label')); self.language_box.setAccessibleName(tr('menu.language'))
        self.setWindowTitle(tr('app.title'))
        for target, key, method in self.texts: getattr(target, method)(tr(key))
        for name, items in (
            ('output', [(tr('output.'+s), s) for s in ('iwi', 'rgb24', 'dds', 'png', 'atlas', 'mosaic', 'panorama')]),
            ('channel', [(value, value) for value in PREVIEW_CHANNELS]),
            ('policy', [(tr('policy.'+s), s) for s in ('preserve', 'encode')]),
            ('game', [(s, s) for s in ('COD4', 'MW2', 'MW3')]),
            ('fourcc', [('BC1 / DXT1', 'DXT1'), ('BC3 / DXT5', 'DXT5')]),
            ('mode', [('CPU', 'CPU'), ('CUDA', 'CUDA')]),
            ('quality', [(tr('quality.'+s), s) for s in ('Fastest', 'Normal', 'Production', 'Highest')])):
            populate(self.combos[name], items)
        for name, action in self.language_actions.items(): action.setChecked(name == self.language.name)
        for name, action in self.background_actions.items(): action.setChecked(name == self.background)
        for index in range(self.tabs.count()):
            self.label_tab_close(self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide))
        self.task_toggle.setToolTip(tr('dock.tasks')); self.task_toggle.setAccessibleName(tr('dock.tasks'))
        self.filename.setAccessibleName(tr('field.basename')); self.filename.setPlaceholderText(tr('field.basename'))
        self.log.setAccessibleName(tr('dock.tasks')); self.outputs.setAccessibleName(tr('field.results'))
        self.updating = False; self.bind_document(); self.render_history(); self.refresh_status()
        if self.doc and self.doc.ready: self.preview.configure(self.doc.entries, self.doc.view, self.doc.source.kind, self.doc.source.repair_seams)
        if self.preview.canvas.loading_text: self.preview.canvas.loading_text = tr('status.loading'); self.preview.canvas.update()
        if self.doc and self.doc.error: self.show_document_error(self.doc.error)
        elif self.preview_error: self.preview.canvas.clear(self.language.render(self.preview_error))

    def add_document(self, doc, activate=True):
        self.documents.append(doc); self.tabs.blockSignals(True)
        index = self.tabs.addTab(doc.source.name); self.tabs.setTabToolTip(index, '\n'.join(str(p) for p in doc.source.paths()))
        close = CompactButton(self.tabs, tab_close=True)
        close.setFixedSize(22, 22)
        self.label_tab_close(close)
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        close.clicked.connect(lambda checked=False, button=close: self.close_tab_button(button))
        if activate: self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        if activate: self.activate()

    def label_tab_close(self, button):
        text = self.language.text('action.close_tab')
        button.setToolTip(text)
        button.setAccessibleName(text)

    def close_tab_button(self, button):
        for index in range(self.tabs.count()):
            if self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.tabs.tabCloseRequested.emit(index)
                return

    def activate(self, *args):
        if self.close_pending: return
        self.preview_sequence += 1; self.preview_token = None; self.preview_error = None
        self.preview_worker.request('images', ('', 0, self.preview_sequence), [])
        self.preview.leave_cube()
        self.preview.canvas.clear(self.language.text('empty.workspace'))
        self.bind_document(); self.show_results()
        if self.doc:
            if self.doc.ready: self.request_view()
            elif self.doc.error: self.show_document_error(self.doc.error)
            else: self.request_inspection()

    def bind_document(self):
        self.updating = True; doc = self.doc
        self.document_summary.set_full_text((doc.source.name+' · '+(str(doc.size)+' × '+str(doc.size)+' · '+(doc.native_format.decode() or 'PNG') if doc.ready else self.language.text('status.loading'))) if doc else self.language.text('app.title'))
        self.output_panel.setEnabled(bool(doc and doc.ready)); self.assets.setEnabled(doc is not None); self.refresh_action.setEnabled(doc is not None)
        self.preview.setEnabled(doc is not None)
        self.panorama_options.setVisible(bool(doc and doc.source.kind == 'panorama'))
        self.repair_toggle.setVisible(bool(doc and doc.source.kind == 'atlas'))
        if doc:
            self.repair_toggle.setChecked(doc.source.repair_seams)
            self.panorama_size.setCurrentIndex(self.panorama_size.findData(doc.source.panorama_size or 512))
            self.panorama_yaw.setValue(doc.source.panorama_yaw)
            self.source_field.edit.setText(str(doc.source.path or '')); self.alpha_field.edit.setText(str(doc.source.alpha or ''))
            for name, combo in self.combos.items(): combo.setCurrentIndex(combo.findData(doc.settings[name]))
            self.directory.edit.setText(doc.settings['directory']); self.filename.setText(doc.settings['name'])
            self.asset_info.setText(self.language.render(doc.info) if doc.info else self.language.text('status.loading'))
            is_atlas = doc.source.kind == 'atlas'; is_slots = doc.source.kind in ('dds', 'png_faces')
            self.source_field.setVisible(not is_slots); self.source_label.setVisible(not is_slots); self.dds_assign.setVisible(is_slots)
            self.dds_assign.setText(self.language.text('action.assign_png' if doc.source.kind == 'png_faces' else 'action.assign_dds'))
            self.alpha_field.setVisible(is_atlas); self.alpha_label.setVisible(is_atlas)
            self.relocate.setVisible(bool(doc.error))
            index = self.tabs.currentIndex(); self.tabs.setTabText(index, doc.source.name)
        else:
            self.source_field.edit.clear(); self.alpha_field.edit.clear(); self.asset_info.clear(); self.relocate.hide()
        for face, tile in self.tiles.items():
            entry = doc.entries.get(PreviewKey('face', face, 'RGB', 'source')) if doc else None
            tile.set_image(doc.thumbnails.get(PreviewKey('face', face, 'RGB', 'source')) if doc else None); tile.selected = bool(doc and doc.view['face'] == face)
            tile.set_editable(bool(doc and doc.source.kind in ('dds', 'png_faces')))
            tile.filter_key = 'filter.png' if doc and doc.source.kind == 'png_faces' else 'filter.dds'
            tile.path = str(doc.source.face_files[FACE_ORDER.index(face)] or '') if doc and doc.source.kind in ('dds', 'png_faces') else ''
            tile.description = ''; tile.filename.setVisible(bool(doc and doc.source.kind in ('dds', 'png_faces'))); tile.update_filename(); tile.resize_thumbnail(); tile.update()
        self.updating = False; self.update_output_controls()

    def update_output_controls(self):
        doc = self.doc
        if not doc:
            self.export_button.setEnabled(False); self.export_button.setText(self.language.text('action.export')); return
        compressed = doc.settings['output'] in ('iwi', 'dds')
        preserve_available = doc.source.kind in ('dds', 'iwi') and doc.native_format != b'RGB24'
        encode = not preserve_available or doc.settings['policy'] == 'encode'
        self.encoding_section.setVisible(compressed)
        self.encoding_form.setRowVisible(self.combos['policy'], compressed and preserve_available)
        self.form.setRowVisible(self.combos['game'], doc.settings['output'] in ('iwi', 'rgb24'))
        self.form.setRowVisible(self.combos['channel'], doc.settings['output'] in ('png', 'atlas', 'mosaic', 'panorama'))
        for name in ('fourcc', 'mode', 'quality'): self.encoding_form.setRowVisible(self.combos[name], compressed and encode)
        self.export_button.setText(self.language.text('action.export_type', output=self.language.text('output.'+doc.settings['output'])))
        self.encoding_toggle.setText(self.language.text('group.encoding') if self.encoding_toggle.isChecked() else self.language.text('encoding.summary', format=doc.settings['fourcc'], mode=doc.settings['mode'], quality=self.language.text('quality.'+doc.settings['quality'])))
        self.export_button.setEnabled(doc.ready and self.active_job is None)
        self.preview_button.setEnabled(doc.ready and self.active_job is None and doc.view['layout'] == 'face')
        self.preview_button.setVisible(encode and compressed)
        self.open_output_button.setEnabled(bool(doc.paths))
        stored = doc.encoded.get(doc.view['face'])
        if doc.settings['output'] == 'rgb24':
            version = 6 if doc.settings['game'] == 'COD4' else 8
            size_bytes = 18 * doc.size * doc.size + (28 if version == 6 else 32)
            self.encoding_info.setText(self.language.text('status.rgb24', version=version, size=doc.size, mib=size_bytes/2**20))
        elif not compressed:
            self.encoding_info.setText(self.language.text('status.image_export'))
        elif not encode:
            self.encoding_info.setText(self.language.text('status.preserve_blocks'))
        elif stored:
            key = 'status.encoding_current' if stored.settings == doc.encoding() else 'status.encoding_previous'
            self.encoding_info.setText(self.language.text(key, face=doc.view['face'].upper(), format=stored.settings.fourcc.decode(), mode=stored.settings.mode,
                quality=self.language.text('quality.'+stored.settings.quality)))
        else: self.encoding_info.setText(self.language.text('status.encoding_none'))
        colors = self.encoding_info.palette(); colors.setColor(QPalette.ColorRole.WindowText, QColor(self.theme.warm if stored and encode and compressed else self.theme.muted)); self.encoding_info.setPalette(colors)

    def save_settings(self):
        if self.updating or not self.doc: return
        doc = self.doc
        for name, combo in self.combos.items(): doc.settings[name] = combo.currentData()
        doc.settings['directory'] = self.directory.edit.text().strip(); doc.settings['name'] = self.filename.text().strip()
        self.update_output_controls()

    def change_output_directory(self, value):
        if self.updating or not self.doc: return
        if value: self.locations.remember_output(value)
        self.save_settings()

    def setting_changed(self, name): self.save_settings()

    def request_inspection(self):
        doc = self.doc
        if not doc: return
        self.preview_error = None
        self.preview_sequence += 1; token = (doc.uid, doc.revision, self.preview_sequence); self.preview_token = token
        self.preview.canvas.loading_text = self.language.text('status.loading'); self.preview.canvas.update()
        self.preview_worker.request('inspect', token, doc.source)

    def request_view(self):
        doc = self.doc
        if not doc or not doc.ready: return
        self.preview_error = None; self.preview.pixel_info.clear()
        entries = self.preview.configure(doc.entries, doc.view, doc.source.kind, doc.source.repair_seams)
        self.preview_sequence += 1; token = (doc.uid, doc.revision, self.preview_sequence); self.preview_token = token
        if self.preview.in_cube():
            if self.preview.begin_cube():
                self.preview_worker.request('cube', token, (doc.source, doc.native))
            else:
                self.preview_worker.request('images', ('', 0, self.preview_sequence), [])
        else:
            self.preview.canvas.loading_text = self.language.text('status.loading')
            self.preview.canvas.update()
            self.preview_worker.request('images', token, entries)
        self.update_output_controls()

    def on_inspected(self, token, result):
        doc = self.find(token)
        if doc is None: return
        doc.ready = True; doc.error = None; doc.entries = result.entries; doc.info = result.message
        doc.thumbnails = result.thumbnails
        doc.size, doc.native_format, doc.native = result.size, result.fourcc, result.native
        if doc.source.kind == 'panorama' and not doc.source.panorama_size:
            doc.source = replace(doc.source, panorama_size=result.size)
        if PreviewKey('face', doc.view['face'], 'RGB', 'source') not in doc.entries:
            doc.view['face'] = next(key.face for key in doc.entries if key.layout == 'face')
        if not doc.settings_initialized:
            raw_source = doc.source.kind == 'png_faces' or result.fourcc == b'RGB24'
            if raw_source:
                doc.settings.update(output='rgb24', game='MW2' if result.iwi_version == 8 else 'COD4')
            doc.settings['policy'] = 'encode' if raw_source or doc.source.kind in ('atlas', 'panorama') else 'preserve'
            doc.settings['fourcc'] = result.fourcc.decode() if result.fourcc in (b'DXT1', b'DXT5') else ('DXT5' if any(k.channel == 'Alpha' for k in doc.entries) else 'DXT1')
            doc.settings['name'] = Path(doc.source.name).stem
            doc.settings['directory'] = self.locations.output_directory()
            doc.settings_initialized = True
        if self.doc is doc: self.bind_document(); self.request_view()

    def on_images(self, token, loaded):
        if token == self.preview_token and self.doc is self.find(token): self.preview.display(loaded)

    def on_cube_loaded(self, token, faces):
        if token == self.preview_token and self.doc is self.find(token):
            self.preview.display_cube(faces)

    def on_preview_failed(self, token, message):
        doc = self.find(token)
        if doc is None: return
        if not doc.ready: doc.error = message; doc.info = message
        if token == self.preview_token:
            self.preview_error = message
            if doc.ready and self.preview.in_cube(): self.preview.show_cube_message(message)
            elif doc.ready: self.preview.canvas.clear(self.language.render(message))
            else: self.show_document_error(message)
            self.report(message, error=True)

    def show_document_error(self, message):
        self.preview.canvas.clear(self.language.render(message)); self.asset_info.setText(self.language.render(message)); self.relocate.show()

    def on_inspect_progress(self, token, value):
        if token == self.preview_token:
            self.preview.canvas.loading_text = self.language.render(value.message); self.preview.canvas.update()

    def on_selection(self, values):
        if self.doc:
            if 'compare' in values and self.preview.canvas.images:
                self.doc.view.update(self.preview.canvas.state, fit=False)
            self.doc.view.update(values); self.request_view()

    def on_view(self, state):
        if self.doc: self.doc.view.update(state)

    def on_sample(self, value):
        if value is None or not self.doc: self.preview.pixel_info.clear(); return
        x, y, r, g, b, a = value
        channel = self.doc.view['channel']
        values = {
            'RGB': f'RGB: {r}, {g}, {b}',
            'Alpha': f'Alpha: {r}',
            'RGBA': f'RGBA: {r}, {g}, {b}, {a}',
        }
        self.preview.pixel_info.set_full_text(f'x: {x}   y: {y}   {values[channel]}')

    def select_face(self, face):
        if self.doc:
            if self.preview.in_cube():
                self.preview.look_at(face)
                return
            self.doc.view.update(layout='face', face=face)
            for name, tile in self.tiles.items(): tile.selected = name == face; tile.update()
            self.request_view()

    def step_face(self, delta):
        if not self.doc: return
        index = FACE_ORDER.index(self.doc.view['face']); self.select_face(FACE_ORDER[(index+delta) % 6])

    def replace_source(self, source):
        doc = self.doc
        if not doc: return
        if self.active_job and self.job_token[0] == doc.uid: self.active_job.cancel.set()
        doc.source = source; doc.revision += 1; doc.ready = False; doc.entries.clear(); doc.thumbnails.clear(); doc.encoded.clear()
        doc.error = None; doc.info = None; doc.paths.clear(); doc.native = ()
        if source.kind == 'atlas' and source.alpha: doc.settings['fourcc'] = 'DXT5'
        self.activate()

    def change_repair(self, enabled):
        if not self.updating and self.doc and self.doc.source.kind == 'atlas':
            if enabled != self.doc.source.repair_seams:
                self.replace_source(replace(self.doc.source, repair_seams=enabled))

    def change_panorama(self, *args):
        if self.updating or not self.doc or self.doc.source.kind != 'panorama':
            return
        source = replace(self.doc.source, panorama_size=self.panorama_size.currentData(),
                         panorama_yaw=self.panorama_yaw.value())
        if source != self.doc.source:
            self.replace_source(source)

    def change_source_path(self, value):
        if self.updating or not self.doc or not value: return
        path = Path(value)
        try:
            kind = source_kind(path)
            self.locations.remember_input(path)
            alpha = self.doc.source.alpha if kind == 'atlas' and self.doc.source.kind == 'atlas' else None
            if path != self.doc.source.path:
                source = replace(self.doc.source, path=path) if kind == self.doc.source.kind else Source(kind, path, alpha)
                self.replace_source(source)
        except Exception as error: self.report(exception_message(error), error=True)

    def change_alpha(self, value):
        if not self.updating and self.doc:
            alpha = Path(value) if value else None
            if alpha: self.locations.remember_input(alpha)
            if alpha != self.doc.source.alpha: self.replace_source(replace(self.doc.source, alpha=alpha))

    def assign_face(self, face, path):
        if not self.doc or self.doc.source.kind != 'dds': return
        self.locations.remember_input(path)
        paths = list(self.doc.source.face_files); paths[FACE_ORDER.index(face)] = Path(path)
        self.replace_source(replace(self.doc.source, face_files=tuple(paths)))

    def reload(self):
        if self.doc: self.replace_source(self.doc.source)

    def relocate_source(self):
        if self.doc and self.doc.source.kind in ('dds', 'png_faces'):
            self.open_face_slots(self.doc.source.kind, replace_current=True)
        else: self.source_field.browse()

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.language.text('action.open'), self.locations.input_directory(), self.language.text('filter.sources'))
        self.open_paths([Path(p) for p in paths])

    def open_panorama(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.language.text('action.open_panorama'),
            self.locations.input_directory(), self.language.text('filter.png'))
        self.open_paths([Path(p) for p in paths], kind='panorama')

    def open_paths(self, paths, kind=None):
        for path in paths:
            try:
                source_type = kind or source_kind(path)
                self.locations.remember_input(path)
                self.add_document(Document(Source(source_type, path)))
            except Exception as error: self.report(exception_message(error), error=True)

    def open_dds(self, checked=False):
        self.open_face_slots('dds')

    def open_face_slots(self, kind, replace_current=False):
        is_png = kind == 'png_faces'
        dialog = QDialog(self); dialog.setWindowTitle(self.language.text('dialog.assign_png_title' if is_png else 'dialog.assign_title')); dialog.resize(660, 440)
        box = QVBoxLayout(dialog); body = QLabel(self.language.text('dialog.assign_png_body' if is_png else 'dialog.assign_body')); body.setWordWrap(True); box.addWidget(body)
        form = QFormLayout(); fields = {}
        old = self.doc.source.face_files if replace_current and self.doc and self.doc.source.kind in ('dds', 'png_faces') else (None,)*6
        for face, path in zip(FACE_ORDER, old):
            field = PathField(self.language, 'face.'+face, filter_key='filter.png' if is_png else 'filter.dds', locations=self.locations); field.edit.setText(str(path or ''))
            form.addRow(self.language.text('face.'+face), field); fields[face] = field
        box.addLayout(form); row = QHBoxLayout(); row.addStretch()
        for key, callback in (('action.no', dialog.reject), ('dialog.assign_apply', dialog.accept)):
            button = FluentButton(); button.setText(self.language.text(key)); button.clicked.connect(callback); row.addWidget(button)
        box.addLayout(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            source = Source(kind, face_files=tuple(fields[f].path(False) for f in FACE_ORDER))
            if is_png and not all(source.face_files):
                self.report(msg('error.png_six'), error=True)
                return
            if not any(source.face_files): return
            self.locations.remember_input(source.paths()[0])
            if replace_current: self.replace_source(source)
            else: self.add_document(Document(source))

    def start_job(self, action=None):
        doc = self.doc
        if not doc or not doc.ready or self.active_job: return
        self.save_settings(); action = action or doc.settings['output']
        try:
            output = None
            if action != 'preview':
                output = self.directory.path()
                self.locations.remember_output(output)
            job = Job(action, doc.source, doc.encoding(), doc.view['face'], output, doc.settings['name'], doc.settings['game'],
                      doc.settings['policy'] if doc.source.kind in ('dds', 'iwi') and doc.native_format != b'RGB24' else 'encode', doc.native, tuple(doc.encoded.items()), channel=doc.settings['channel'])
            existing = [path for path in output_paths(job) if path.exists()]
            if existing and not self.confirm_replace(existing): return
            self.job_token = (doc.uid, doc.revision); self.active_job = job
            self.task_failed = False; self.last_message = msg('status.document_task', document=doc.source.name, stage=msg('status.started')); self.refresh_status()
            self.progress.setRange(0, 6); self.progress.setValue(0); self.cancel_button.show(); self.update_output_controls()
            self.execute.emit(self.job_token, job)
        except Exception as error: self.report(exception_message(error), error=True)

    def confirm_replace(self, paths):
        dialog = QMessageBox(QMessageBox.Icon.Question, self.language.text('dialog.replace_title'), self.language.text('dialog.replace_body'), parent=self)
        dialog.setDetailedText('\n'.join(str(path) for path in paths))
        yes = dialog.addButton(self.language.text('action.yes'), QMessageBox.ButtonRole.AcceptRole)
        no = dialog.addButton(self.language.text('action.no'), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(no); dialog.exec(); return dialog.clickedButton() == yes

    def on_face_ready(self, token, name, value):
        doc = self.find(token)
        if doc is None: return
        if doc.encoded.get(name) is value: return
        doc.encoded[name] = value
        # Replacing BC3 with BC1 removes the previous Alpha preview as well.
        for key in list(doc.entries):
            if key.layout == 'face' and key.face == name and key.stage == 'dds': del doc.entries[key]
        for channel in PREVIEW_CHANNELS if value.block.fourcc == b'DXT5' else ('RGB',):
            key = PreviewKey('face', name, channel, 'dds')
            doc.entries[key] = PreviewEntry(key, ImageSource('compressed', compressed=value.block), value.block.size, value.block.size)
        if self.doc is doc and doc.view['layout'] != 'cube' and doc.view['face'] == name and not self.close_pending:
            self.request_view()

    def on_progress(self, token, event):
        if token != self.job_token: return
        self.last_message = msg('status.document_task', document=self.active_job.source.name, stage=event.message)
        self.progress.setRange(0, max(1, event.total)); self.progress.setValue(event.done); self.refresh_status()

    def on_complete(self, token, result):
        doc = self.find(token)
        if doc and result.paths: doc.paths = result.paths
        self.report(msg('status.document_task', document=self.active_job.source.name, stage=result.message))
        if doc is self.doc: self.show_results()

    def on_job_failed(self, token, message): self.report(message, error=True)
    def on_cancelled(self, token): self.report(msg('status.cancelled'))
    def on_finished(self, token):
        self.active_job = None; self.cancel_button.hide(); self.update_output_controls()
        if self.close_pending: self.close()
    def cancel_task(self):
        if self.active_job: self.active_job.cancel.set(); self.last_message = msg('status.cancelling'); self.refresh_status()

    def report(self, message, error=False):
        self.last_message, self.task_failed = message, error
        self.history.append(message); self.history = self.history[-120:]; self.render_history(); self.refresh_status()
        if error: self.task_toggle.setChecked(True)

    def render_history(self): self.log.setPlainText('\n\n'.join(self.language.render(m) for m in self.history))
    def refresh_status(self):
        text = self.language.render(self.last_message); metrics = self.status_label.fontMetrics()
        self.status_label.setText(metrics.elidedText(text.splitlines()[0], Qt.TextElideMode.ElideRight, max(120, self.status_label.width())))
        self.status_label.setToolTip(text)
        colors = self.status_label.palette(); colors.setColor(QPalette.ColorRole.WindowText, QColor(self.theme.error if self.task_failed else self.theme.ink)); self.status_label.setPalette(colors)
    def toggle_tasks(self, shown): self.details.setVisible(shown); self.task_toggle.setText('▾' if shown else '▸')
    def show_results(self):
        self.outputs.clear()
        if self.doc:
            for path in self.doc.paths:
                item = QListWidgetItem(path.name); item.setData(Qt.ItemDataRole.UserRole, str(path)); item.setToolTip(str(path)); self.outputs.addItem(item)
    def open_output(self):
        if self.doc and self.doc.paths: self.open_folder(self.doc.paths[-1].parent)
    def open_folder(self, path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))): self.report(msg('error.open_folder', path=str(path)), error=True)

    def close_document(self, index):
        if not 0 <= index < len(self.documents): return
        doc = self.documents[index]
        if self.active_job and self.job_token[0] == doc.uid:
            self.report(msg('status.close_document_busy')); return
        self.tabs.blockSignals(True); self.documents.pop(index); self.tabs.removeTab(index); self.tabs.blockSignals(False)
        if self.documents: self.activate()
        else: self.show_empty()
    def show_empty(self):
        self.preview_sequence += 1; self.preview_token = None; self.preview_error = None
        self.preview_worker.request('images', ('', 0, self.preview_sequence), [])
        self.preview.leave_cube()
        self.preview.entries = {}; self.preview.view = {}; self.preview.update_controls(); self.preview.canvas.clear(self.language.text('empty.workspace')); self.preview.info.clear()
        self.bind_document(); self.show_results()

    def set_panels(self, assets, output):
        self.assets.setVisible(assets); self.output_panel.setVisible(output)
        self.assets_action.setChecked(assets); self.output_action.setChecked(output)
    def focus_canvas(self):
        if self.assets.isVisible() or self.output_panel.isVisible():
            self.focus_panels = (self.assets.isVisible(), self.output_panel.isVisible()); self.set_panels(False, False)
        else: self.set_panels(*getattr(self, 'focus_panels', (True, True)))
        self.preview.stack.currentWidget().setFocus()
    def reset_layout(self): self.set_panels(True, True); self.columns.setSizes([256, 872, 312])

    def text_dialog(self, title, text, *, markdown_base=None):
        dialog = QDialog(self); dialog.setWindowTitle(title); dialog.resize(800, 620)
        box = QVBoxLayout(dialog)
        browser = QTextBrowser()
        if markdown_base is not None:
            browser.document().setBaseUrl(QUrl.fromLocalFile(markdown_base.as_posix() + '/'))
            browser.setMarkdown(text)
            size_help_images(browser.document())
        else:
            browser.setPlainText(text)
        box.addWidget(browser)
        close = FluentButton(); close.setText(self.language.text('action.close')); close.clicked.connect(dialog.accept); box.addWidget(close); dialog.exec()
    def show_help(self):
        path = resource_root()/('UserGuide.md' if self.language.name == 'en' else '使用说明.md')
        self.text_dialog(self.language.text('action.help'), path.read_text(encoding='utf-8-sig'), markdown_base=path.parent)
    def about(self):
        text = self.language.text('about.heading')+'\n\n'+self.language.text('about.components')+'\n\n'
        text += self.language.text('about.project_license')+'\n\n'+(resource_root()/'LICENSE').read_text(encoding='utf-8')+'\n\n'
        text += '\n\n'.join(p.name+'\n\n'+p.read_text(encoding='utf-8') for p in sorted((resource_root()/'licenses').glob('*.txt')))
        self.text_dialog(self.language.text('about.title'), text)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in ('.png', '.iwi') for u in urls): event.acceptProposedAction()
    def dropEvent(self, event): self.open_paths([Path(u.toLocalFile()) for u in event.mimeData().urls()]); event.acceptProposedAction()

    def save_workspace(self):
        self.save_settings(); self.settings.setValue('workspace', json.dumps([doc.record() for doc in self.documents], ensure_ascii=False))
        self.settings.setValue('active_tab', max(0, self.tabs.currentIndex())); self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('columns', self.columns.saveState()); self.settings.setValue('assets_visible', self.assets.isVisible())
        self.settings.setValue('output_visible', self.output_panel.isVisible()); self.settings.sync()
    def closeEvent(self, event):
        self.save_workspace(); self.close_pending = True
        if self.active_job:
            self.cancel_task(); event.ignore(); return
        if self.preview_thread.isRunning():
            self.preview_worker.stop(); self.last_message = msg('status.closing'); self.refresh_status(); event.ignore(); return
        self.preview.leave_cube()
        if self.preview.cube is not None and self.preview.cube.isValid():
            self.preview.cube.release_gl()
        self.author_thread.quit(); self.author_thread.wait(); event.accept()
    def finish_close(self):
        if self.close_pending and self.active_job is None: self.close()


def source_kind(path):
    if path.suffix.lower() == '.png':
        with Image.open(path) as image:
            return 'panorama' if image.width == image.height * 2 else 'atlas'
    if path.suffix.lower() == '.iwi': return 'iwi'
    raise ToolError('error.input_type', path=str(path))



def size_help_images(document):
    images = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.charFormat().isImageFormat():
                images.append((fragment.position(), fragment.length(), fragment.charFormat().toImageFormat()))
            iterator += 1
        block = block.next()
    cursor = QTextCursor(document)
    for position, length, image_format in images:
        url = document.baseUrl().resolved(QUrl(image_format.name()))
        image = QImage(url.toLocalFile())
        if image.isNull():
            continue
        width = min(720, image.width())
        image_format.setWidth(width)
        image_format.setHeight(width * image.height() / image.width())
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(image_format)


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent


def main():
    app = QApplication(sys.argv); app.setApplicationName('CubemapIWI'); app.setOrganizationName('CubemapIWI')
    app.setFont(ui_font())
    app.setWindowIcon(QIcon(str(resource_root()/'assets'/'app.ico')))
    window = MainWindow(); window.show(); return app.exec()
