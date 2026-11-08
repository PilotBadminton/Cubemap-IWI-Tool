"""Windows 11 controls with lake-teal accents and neutral image surroundings."""
import ctypes
import sys
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QPalette, QFont, QFontDatabase, QPen, QPainter
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory, QPushButton, QButtonGroup, QWidget, QHBoxLayout, QStyleOptionButton, QStyleOptionMenuItem, QComboBox, QStyledItemDelegate, QToolButton, QTabBar
from .models import ToolError


def ui_font(size=16, semibold=False):
    """Use the platform UI font and its native rendering defaults."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPixelSize(size)
    if semibold: font.setWeight(QFont.Weight.DemiBold)
    return font


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    surface: str
    base: str
    edge: str
    ink: str
    muted: str
    accent: str
    accent_text: str
    selected: str
    disabled: str
    error: str
    warm: str
    control: str
    hover: str
    pressed: str
    primary: str
    compact_hover: str
    compact_pressed: str
    compact_focus: str


THEMES = {
    'dark': Theme('dark', '#061014', '#0D1B1F', '#071418', '#4D727B', '#F4FBFC', '#91AAB0',
                  '#63DCE9', '#061014', '#12323A', '#71868B', '#FFC2CA', '#FFD49D',
                  '#14272C', '#1A363C', '#0E2024', '#F49132', '#2A343A', '#39454D', '#C3CBCF'),
    'light': Theme('light', '#F4EEDF', '#F8F2E7', '#FFFDF8', '#B5AB99', '#10252B', '#536970',
                   '#006F82', '#FFFFFF', '#DCECE6', '#718086', '#8A2733', '#744008',
                   '#F2EADF', '#E7EEE7', '#DFE6DD', '#F08A2B', '#E8DFD2', '#D9CCBC', '#635C53'),
}


def palette(theme):
    result = QPalette()
    roles = {QPalette.ColorRole.Window: theme.window, QPalette.ColorRole.WindowText: theme.ink,
        QPalette.ColorRole.Base: theme.base, QPalette.ColorRole.AlternateBase: theme.surface,
        QPalette.ColorRole.Text: theme.ink, QPalette.ColorRole.Button: theme.control,
        QPalette.ColorRole.ButtonText: theme.ink, QPalette.ColorRole.Highlight: theme.accent,
        QPalette.ColorRole.Accent: theme.accent, QPalette.ColorRole.HighlightedText: theme.accent_text,
        QPalette.ColorRole.ToolTipBase: theme.surface, QPalette.ColorRole.ToolTipText: theme.ink,
        QPalette.ColorRole.PlaceholderText: theme.muted, QPalette.ColorRole.Link: theme.accent,
        QPalette.ColorRole.Mid: theme.edge, QPalette.ColorRole.Dark: theme.edge,
        QPalette.ColorRole.Light: theme.surface}
    for role, color in roles.items(): result.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.disabled))
    return result


def apply_title_bar(hwnd, theme, active):
    if sys.getwindowsversion().build < 22000:
        return
    dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
    dwm.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)
    dwm.restype = ctypes.c_long
    for attribute, color in ((34, theme.accent if active else theme.edge),
                             (35, theme.surface), (36, theme.ink)):
        rgb = QColor(color)
        value = ctypes.c_uint(rgb.red() | rgb.green() << 8 | rgb.blue() << 16)
        dwm(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))


def draw_check(painter, x, y, color):
    painter.setPen(QPen(QColor(color), 1.5))
    painter.drawLine(x - 5, y, x - 1, y + 4)
    painter.drawLine(x - 1, y + 4, x + 6, y - 4)


class ComboRows(QStyledItemDelegate):
    def paint(self, painter, option, index):
        combo = self.parent()
        theme = combo.style().theme
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hovered = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        chosen = index.row() == combo.currentIndex()
        area = option.rect.adjusted(2, 1, -2, -1)
        painter.save()
        painter.setFont(combo.font())
        if hovered and enabled:
            painter.fillRect(area, QColor(theme.selected))
            painter.fillRect(area.left(), area.top() + 2, 2, area.height() - 4, QColor(theme.accent))
        text_area = area.adjusted(12, 0, -32, 0)
        text = painter.fontMetrics().elidedText(index.data(), Qt.TextElideMode.ElideRight, max(0, text_area.width()))
        painter.setPen(QColor(theme.ink if enabled else theme.disabled))
        painter.drawText(text_area, Qt.AlignmentFlag.AlignVCenter, text)
        if chosen:
            draw_check(painter, area.right() - 15, area.center().y(), theme.accent)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 44, max(36, size.height() + 12))


class WorkbenchCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(ComboRows(self))
        self.view().setMouseTracking(True)
        self.setMaxVisibleItems(8)
        self.popup_open = False

    def showPopup(self):
        if not self.count():
            return
        self.popup_open = True
        metrics = self.fontMetrics()
        screen = self.screen().availableGeometry()
        width = max(self.width(), max(metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())) + 64)
        self.view().setMinimumWidth(min(width, screen.width() - 16))
        super().showPopup()
        self.update()

    def hidePopup(self):
        super().hidePopup()
        self.popup_open = False
        self.update()


class FluentStyle(QProxyStyle):
    def __init__(self, theme):
        self.theme = theme
        base = QStyleFactory.create('windows11')
        if base is None: raise ToolError('error.fluent_style')
        super().__init__(base)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_SmallIconSize, QStyle.PixelMetric.PM_ToolBarIconSize): return 20
        if metric == QStyle.PixelMetric.PM_SplitterWidth: return 5
        if metric in (QStyle.PixelMetric.PM_MenuHMargin, QStyle.PixelMetric.PM_MenuVMargin):
            return 5
        if metric == QStyle.PixelMetric.PM_MenuPanelWidth:
            return 1
        return super().pixelMetric(metric, option, widget)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup and isinstance(widget, WorkbenchCombo):
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def sizeFromContents(self, kind, option, size, widget=None):
        result = super().sizeFromContents(kind, option, size, widget)
        if kind == QStyle.ContentsType.CT_MenuItem and isinstance(option, QStyleOptionMenuItem):
            if option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
                return QSize(result.width(), 9)
            title, _, shortcut = option.text.partition('\t')
            metrics = option.fontMetrics
            width = 52 + metrics.horizontalAdvance(title)
            if shortcut:
                width += 20 + metrics.horizontalAdvance(shortcut)
            return QSize(max(width, result.width() + 12, 160), max(result.height(), 34))
        return result

    def draw_menu_item(self, option, painter):
        area = option.rect.adjusted(1, 1, -1, -1)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        y = area.center().y()
        painter.save()
        painter.setFont(option.font)
        if option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
            painter.setPen(QColor(self.theme.edge))
            painter.drawLine(area.left() + 10, y, area.right() - 10, y)
        else:
            if selected and enabled:
                painter.fillRect(area, QColor(self.theme.selected))
                painter.fillRect(area.left(), area.top() + 3, 2, area.height() - 6, QColor(self.theme.accent))
            if option.checked:
                draw_check(painter, area.left() + 14, y, self.theme.accent)
            title, _, shortcut = option.text.partition('\t')
            flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic
            painter.setPen(QColor(self.theme.ink if enabled else self.theme.disabled))
            painter.drawText(area.adjusted(28, 0, -24, 0), flags, title)
            if shortcut:
                painter.setPen(QColor(self.theme.muted if enabled else self.theme.disabled))
                painter.drawText(area.adjusted(28, 0, -14, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, shortcut)
            if option.menuItemType == QStyleOptionMenuItem.MenuItemType.SubMenu:
                x = area.right() - 12
                painter.drawLine(x - 2, y - 4, x + 2, y)
                painter.drawLine(x + 2, y, x - 2, y + 4)
        painter.restore()

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.ControlElement.CE_MenuItem:
            self.draw_menu_item(option, painter)
            return
        if element == QStyle.ControlElement.CE_MenuBarItem:
            painter.save()
            painter.setFont(option.font)
            active = option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_Sunken)
            painter.fillRect(option.rect.adjusted(1, 1, -1, -1), QColor(self.theme.selected if active else self.theme.surface))
            painter.setPen(QColor(self.theme.ink))
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextShowMnemonic.value, option.text)
            painter.restore()
            return
        if element == QStyle.ControlElement.CE_ComboBoxLabel:
            if option.editable: return
            painter.save()
            if widget is not None: painter.setFont(widget.font())
            area = self.subControlRect(QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, widget)
            painter.setPen(QColor(self.theme.ink if option.state & QStyle.StateFlag.State_Enabled else self.theme.disabled))
            text = painter.fontMetrics().elidedText(option.currentText, Qt.TextElideMode.ElideRight, max(0, area.width()))
            painter.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            painter.restore(); return
        if element == QStyle.ControlElement.CE_PushButton:
            state = option.state
            enabled = bool(state & QStyle.StateFlag.State_Enabled)
            pressed = bool(state & QStyle.StateFlag.State_Sunken)
            selected = bool(state & QStyle.StateFlag.State_On)
            hover = bool(state & QStyle.StateFlag.State_MouseOver)
            section = bool(widget and widget.property('section'))
            primary = bool(widget and widget.property('primary'))
            color = QColor(self.theme.primary if primary and enabled else self.theme.pressed if pressed else
                           self.theme.selected if selected else self.theme.hover if hover and enabled else self.theme.control)
            if primary and enabled:
                if pressed: color = color.darker(112)
                elif hover: color = color.lighter(110)
            painter.save()
            if widget is not None: painter.setFont(widget.font())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if section:
                color = QColor(self.theme.surface)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen if section else QPen(QColor(self.theme.accent if selected else self.theme.edge), 1))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(.5,.5,-.5,-.5), 4, 4)
            if state & QStyle.StateFlag.State_HasFocus:
                painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(QColor(self.theme.accent), 2))
                painter.drawRoundedRect(QRectF(option.rect).adjusted(3,3,-3,-3), 2, 2)
            label = QStyleOptionButton(option)
            label.features &= ~(QStyleOptionButton.ButtonFeature.DefaultButton | QStyleOptionButton.ButtonFeature.AutoDefaultButton)
            text = '#1B0B00' if primary and enabled else self.theme.ink if enabled else self.theme.disabled
            label.palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
            if section:
                area = option.rect.adjusted(2,0,-24,0)
                text = painter.fontMetrics().elidedText(option.text, Qt.TextElideMode.ElideRight, area.width())
                painter.setPen(QColor(self.theme.ink)); painter.drawText(area, Qt.AlignmentFlag.AlignVCenter, text)
                x,y=option.rect.right()-12,option.rect.center().y()
                painter.setPen(QPen(QColor(self.theme.accent),1.5))
                if selected:
                    painter.drawLine(x-4,y-2,x,y+2); painter.drawLine(x,y+2,x+4,y-2)
                else:
                    painter.drawLine(x-2,y-4,x+2,y); painter.drawLine(x+2,y,x-2,y+4)
            else:
                super().drawControl(QStyle.ControlElement.CE_PushButtonLabel, label, painter, widget)
            painter.restore(); return
        if element == QStyle.ControlElement.CE_TabBarTabShape:
            painter.save()
            state = option.state
            selected = bool(state & QStyle.StateFlag.State_Selected)
            enabled = bool(state & QStyle.StateFlag.State_Enabled)
            hover = bool(state & QStyle.StateFlag.State_MouseOver)
            pressed = bool(state & QStyle.StateFlag.State_Sunken)
            if hover and isinstance(widget, QTabBar):
                close = widget.tabButton(option.tabIndex, QTabBar.ButtonPosition.RightSide)
                hover = not isinstance(close, CompactButton) or not close.underMouse()
            color = self.theme.selected if selected else self.theme.window
            if enabled and (hover or pressed):
                if selected:
                    color = QColor(color)
                    factor = 112 if pressed else 105
                    color = color.lighter(factor) if self.theme.name == 'dark' else color.darker(factor)
                else:
                    color = self.theme.compact_pressed if pressed else self.theme.compact_hover
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(1,1,-1,-1), 4, 4)
            if selected:
                painter.setPen(QPen(QColor(self.theme.accent), 3))
                painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            painter.restore(); return
        super().drawControl(element, option, painter, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PrimitiveElement.PE_PanelMenu, QStyle.PrimitiveElement.PE_FrameMenu):
            painter.save()
            if element == QStyle.PrimitiveElement.PE_PanelMenu:
                painter.fillRect(option.rect, QColor(self.theme.base))
            painter.setPen(QColor(self.theme.edge))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
            painter.restore()
            return
        if element == QStyle.PrimitiveElement.PE_PanelLineEdit:
            painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            focus = bool(option.state & QStyle.StateFlag.State_HasFocus)
            painter.setBrush(QColor(self.theme.control))
            painter.setPen(QPen(QColor(self.theme.accent if focus else self.theme.edge), 2 if focus else 1))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(1,1,-1,-1), 4, 4)
            painter.restore(); return
        if element in (QStyle.PrimitiveElement.PE_PanelToolBar, QStyle.PrimitiveElement.PE_PanelMenuBar):
            painter.fillRect(option.rect, QColor(self.theme.surface)); return
        super().drawPrimitive(element, option, painter, widget)

    def subControlRect(self, control, option, subcontrol, widget=None):
        if control == QStyle.ComplexControl.CC_ComboBox:
            if subcontrol == QStyle.SubControl.SC_ComboBoxArrow:
                return option.rect.adjusted(option.rect.width()-28, 2, -4, -2)
            if subcontrol == QStyle.SubControl.SC_ComboBoxEditField:
                return option.rect.adjusted(10, 2, -32, -2)
        return super().subControlRect(control, option, subcontrol, widget)

    def drawComplexControl(self, control, option, painter, widget=None):
        if control == QStyle.ComplexControl.CC_ToolButton and isinstance(widget, CompactButton):
            self.draw_compact_button(option, painter, widget)
            return
        if control == QStyle.ComplexControl.CC_ComboBox:
            painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            focus = bool(option.state & QStyle.StateFlag.State_HasFocus)
            opened = isinstance(widget, WorkbenchCombo) and widget.popup_open
            painter.setBrush(QColor(self.theme.hover if (hover or opened) and enabled else self.theme.control))
            painter.setPen(QPen(QColor(self.theme.accent if focus or opened else self.theme.edge), 1))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(.5,.5,-.5,-.5), 4, 4)
            arrow = self.subControlRect(control, option, QStyle.SubControl.SC_ComboBoxArrow, widget)
            x, y = arrow.center().x(), arrow.center().y()
            painter.setPen(QPen(QColor(self.theme.accent if enabled else self.theme.disabled), 1.5))
            dy = -2 if opened else 2
            painter.drawLine(x - 4, y - dy, x, y + dy)
            painter.drawLine(x, y + dy, x + 4, y - dy)
            painter.restore(); return
        super().drawComplexControl(control, option, painter, widget)

    def draw_compact_button(self, option, painter, widget):
        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        menu = widget.menu()
        pressed = bool(state & QStyle.StateFlag.State_Sunken) or (menu is not None and menu.isVisible())
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        keyboard_focus = bool(state & QStyle.StateFlag.State_HasFocus) and widget.keyboard_focus
        area = QRectF(option.rect).adjusted(1, 1, -1, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if enabled and (pressed or hovered):
            painter.setBrush(QColor(self.theme.compact_pressed if pressed else self.theme.compact_hover))
            painter.drawRoundedRect(area, 4, 4)
        if enabled and keyboard_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(self.theme.compact_focus), 1.5))
            painter.drawRoundedRect(area, 4, 4)
        ink = QColor(self.theme.ink if enabled else self.theme.disabled)
        pen = QPen(ink, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if widget.tab_close:
            center = option.rect.center()
            x, y = center.x(), center.y()
            painter.drawLine(x - 4, y - 4, x + 4, y + 4)
            painter.drawLine(x + 4, y - 4, x - 4, y + 4)
        else:
            painter.setFont(widget.font())
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, option.text)
        painter.restore()


class CompactButton(QToolButton):
    def __init__(self, parent=None, *, tab_close=False):
        super().__init__(parent)
        self.tab_close = tab_close
        self.keyboard_focus = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self.keyboard_focus = False
        super().mousePressEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()
        if self.tab_close:
            self.parentWidget().update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()
        if self.tab_close:
            self.parentWidget().update()


class FluentButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setAutoDefault(False)


class Segments(QWidget):
    changed = Signal(str)

    def __init__(self, items, language):
        super().__init__()
        self.language, self.items = language, items
        self.group = QButtonGroup(self)
        self.buttons = {}
        box = QHBoxLayout(self); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(2)
        for value, key in items:
            button = FluentButton(); button.setCheckable(True); button.setMinimumWidth(42)
            self.buttons[value] = button; self.group.addButton(button); box.addWidget(button)
            button.clicked.connect(lambda checked=False, v=value: self.changed.emit(v))
        self.buttons[items[0][0]].setChecked(True)
        language.changed.connect(self.retranslate); self.retranslate()

    def value(self): return next(v for v, b in self.buttons.items() if b.isChecked())
    def select(self, value): self.buttons[value].setChecked(True)
    def retranslate(self):
        for value, key in self.items:
            text = self.language.text(key)
            self.buttons[value].setText(text); self.buttons[value].setAccessibleName(text)


def label_font(widget, size=16, bold=False):
    widget.setFont(ui_font(size, semibold=bold))
