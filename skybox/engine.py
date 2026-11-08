"""Independent preview mailbox and serial authoring worker."""
from threading import Lock, Event
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage
from .messages import exception_message, msg
from .pipeline import inspect, load_preview, run, Cancelled, checkpoint, PixelReader
from .models import FACE_ORDER, ToolError


def display_image(image):
    if image.mode == 'RGBA':
        return QImage(image.tobytes(), image.width, image.height, image.width*4,
                      QImage.Format.Format_RGBA8888).copy()
    if image.mode not in ('RGB', 'L'): image = image.convert('RGB')
    channels = 1 if image.mode == 'L' else 3
    fmt = QImage.Format.Format_Grayscale8 if channels == 1 else QImage.Format.Format_RGB888
    result = QImage(image.tobytes(), image.width, image.height, image.width*channels, fmt).copy()
    return result.convertToFormat(QImage.Format.Format_RGB32)


class PreviewWorker(QObject):
    wake = Signal()
    inspected = Signal(object, object)
    loaded = Signal(object, object)
    cube_loaded = Signal(object, object)
    failed = Signal(object, object)
    progress = Signal(object, object)
    stopped = Signal()

    def __init__(self):
        super().__init__()
        self.lock = Lock(); self.pending = None; self.cancel = None
        self.stopping = False; self.cache = {}
        self.wake.connect(self.drain)

    def request(self, kind, token, payload):
        # Called by the GUI; only mailbox metadata is shared with the worker.
        with self.lock:
            if self.cancel is not None: self.cancel.set()
            event = Event(); self.cancel = event
            self.pending = (kind, token, payload, event)
        self.wake.emit()

    def stop(self):
        with self.lock:
            self.stopping = True; self.pending = None
            if self.cancel is not None: self.cancel.set()
        self.wake.emit()

    @Slot()
    def drain(self):
        while True:
            with self.lock:
                if self.stopping:
                    self.cache.clear(); self.stopped.emit(); return
                item, self.pending = self.pending, None
            if item is None: return
            kind, token, payload, event = item
            try:
                if kind == 'inspect':
                    self.cache.clear()
                    result = inspect(payload, lambda value: self.progress.emit(token, value), event)
                    for entry in result.entries.values():
                        checkpoint(event)
                        if entry.thumbnail is not None:
                            result.thumbnails[entry.key] = display_image(entry.thumbnail)
                            entry.thumbnail = None
                    checkpoint(event); self.inspected.emit(token, result)
                elif kind == 'cube':
                    self.cache.clear()
                    source, native = payload
                    faces = {}
                    with PixelReader(source, native, event) as reader:
                        for face in FACE_ORDER:
                            checkpoint(event)
                            pixel = reader.face(face)
                            faces[face] = (pixel.size, pixel.rgb.tobytes())
                    checkpoint(event)
                    if len({size for size, _ in faces.values()}) != 1:
                        raise ToolError('error.models.matching_faces')
                    self.cube_loaded.emit(token, faces)
                else:
                    keys = [(token[0], token[1], entry.key, id(entry.source)) for entry in payload]
                    if payload and payload[0].key.layout == 'face':
                        selected = payload[0].key
                        wanted = {entry.key for entry in payload}
                        self.cache = {key: value for key, value in self.cache.items()
                            if key[:2] == token[:2] and (key[2].layout, key[2].face, key[2].channel) == ('face', selected.face, selected.channel)
                            and (key[2] not in wanted or key in keys)}
                    else:
                        self.cache = {key: value for key, value in self.cache.items() if key in keys}
                    result = []
                    for key, entry in zip(keys, payload):
                        checkpoint(event)
                        if key not in self.cache:
                            image = load_preview(entry, event)
                            checkpoint(event); self.cache[key] = display_image(image)
                        result.append((entry.key, self.cache[key]))
                    checkpoint(event); self.loaded.emit(token, result)
            except Cancelled:
                pass
            except Exception as error:
                if not event.is_set(): self.failed.emit(token, exception_message(error))


class AuthorWorker(QObject):
    progress = Signal(object, object)
    face_ready = Signal(object, str, object)
    completed = Signal(object, object)
    failed = Signal(object, object)
    cancelled = Signal(object)
    finished = Signal(object)

    @Slot(object, object)
    def execute(self, token, job):
        stage = msg('status.started')
        def progress(event):
            nonlocal stage
            stage = event.message
            self.progress.emit(token, event)
        try:
            result = run(job, progress,
                         lambda face, value: self.face_ready.emit(token, face, value))
            self.completed.emit(token, result)
        except Cancelled:
            self.cancelled.emit(token)
        except Exception as error:
            self.failed.emit(token, msg('error.task_stage', stage=stage, reason=exception_message(error)))
        finally:
            self.finished.emit(token)
