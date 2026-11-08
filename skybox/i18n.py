"""The UI chooses language; the engine only produces message identifiers."""
from PySide6.QtCore import QObject, Signal
from .messages import Message


class Language(QObject):
    changed=Signal()

    def __init__(self, name):
        super().__init__()
        self.name=name

    def set(self, name):
        if name!=self.name:
            self.name=name
            self.changed.emit()

    def text(self, code, **params):
        return Message(code,params).render(self.name)

    def render(self, message):
        return message.render(self.name)


def populate(combo, items):
    items=list(items)
    if [(combo.itemText(i),combo.itemData(i)) for i in range(combo.count())]==items:
        return
    combo.setMinimumWidth(min(160, max((combo.fontMetrics().horizontalAdvance(text) for text, data in items), default=0) + 44))
    current=combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for text,data in items:combo.addItem(text,data)
    index=combo.findData(current)
    if index>=0:combo.setCurrentIndex(index)
    combo.blockSignals(False)
