"""NVTT 3.2.5 C API. A codec and all of its native handles belong to one thread."""
import ctypes as c
import sys
import os
import threading
from pathlib import Path
import numpy as np
from .models import CompressedFace, PixelFace, ToolError
from .messages import Message

DLL_NAME = "nvtt30205.dll"
QUALITY_NAMES = ("Fastest", "Normal", "Production", "Highest")


def runtime_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "nvtt" / DLL_NAME
    sdk_dir = os.environ.get('NVTT_SDK_DIR')
    if not sdk_dir:
        raise ToolError('error.nvtt.sdk_directory')
    return Path(sdk_dir) / DLL_NAME


class Codec:
    def __init__(self, mode="CPU", quality="Production"):
        if mode not in ("CPU", "CUDA") or quality not in QUALITY_NAMES:
            raise ToolError('error.nvtt.options')
        self.thread = threading.get_ident()
        self.mode = mode
        self.messages = []
        self.dll = c.CDLL(str(runtime_path()))
        P, I = c.c_void_p, c.c_int
        self.handles = []
        self._functions = {}
        self.MESSAGE = c.CFUNCTYPE(None, I, I, c.c_char_p, P)
        self.BEGIN = c.CFUNCTYPE(None, I, I, I, I, I, I)
        self.WRITE = c.CFUNCTYPE(I, P, I)
        self.END = c.CFUNCTYPE(None)
        self.callback = self.MESSAGE(self._message)
        self._bind("nvttSetMessageCallback", I, [self.MESSAGE, P])(self.callback, None)
        try:
            self.context = self._new("Context")
            self._bind("nvttSetContextCudaAcceleration", None, [P, I])(self.context, mode == "CUDA")
            if mode == "CUDA" and not self._bind("nvttContextIsCudaAccelerationEnabled", I, [P])(self.context):
                raise ToolError('error.nvtt.cuda')
            self.compression = self._new("CompressionOptions")
            self.output = self._new("OutputOptions")
            self._bind("nvttSetCompressionOptionsQuality", None, [P, I])(
                self.compression, QUALITY_NAMES.index(quality))
            self._bind("nvttSetCompressionOptionsColorWeights", None, [P] + [c.c_float] * 4)(
                self.compression, 1, 1, 1, 1)
            self.chunks = []
            self.begin = self.BEGIN(lambda *args: None)
            self.write = self.WRITE(self._write)
            self.end = self.END(lambda: None)
            self._bind("nvttSetOutputOptionsOutputHandler", None,
                       [P, self.BEGIN, self.WRITE, self.END])(self.output, self.begin, self.write, self.end)
            self._check(True, "initialize")
        except Exception:
            self.close()
            raise

    def _bind(self, name, result, args):
        if name not in self._functions:
            fn = getattr(self.dll, name)
            fn.restype, fn.argtypes = result, args
            self._functions[name] = fn
        return self._functions[name]

    def _new(self, kind):
        handle = self._bind("nvttCreate" + kind, c.c_void_p, [])()
        if not handle:
            raise ToolError('error.nvtt.create', kind=kind)
        self.handles.append((kind, handle))
        return handle

    def _message(self, severity, error, message, _):
        self.messages.append((severity, error, message.decode("utf-8", errors="replace")))

    def _write(self, data, size):
        self.chunks.append(c.string_at(data, size))
        return 1

    def _check(self, success, operation):
        errors = [m[2] for m in self.messages if m[0] == 2]
        self.messages.clear()
        if not success or errors:
            raise ToolError('error.nvtt.operation', mode=self.mode, operation=Message('op.' + operation), detail='; '.join(errors))

    def _same_thread(self):
        if threading.get_ident() != self.thread:
            raise ToolError('error.nvtt.thread')

    def encode(self, face: PixelFace, fourcc: bytes) -> CompressedFace:
        self._same_thread()
        self._check(self._bind("nvttSetMessageCallback", c.c_int, [self.MESSAGE, c.c_void_p])(self.callback, None), "initialize")
        if fourcc not in (b"DXT1", b"DXT5"):
            raise ToolError('error.nvtt.compression')
        if fourcc == b"DXT5" and face.alpha is None:
            raise ToolError('error.nvtt.alpha')
        P, I = c.c_void_p, c.c_int
        surface = self._new("Surface")
        try:
            bgra = np.empty((face.size, face.size, 4), dtype=np.uint8)
            bgra[:, :, :3] = face.rgb[:, :, ::-1]
            bgra[:, :, 3] = face.alpha if fourcc == b"DXT5" else 255
            ok = self._bind("nvttSurfaceSetImageData", I, [P, I, I, I, I, P, I, P])(
                surface, 0, face.size, face.size, 1, bgra.ctypes.data, 0, None)
            self._check(ok, "upload")
            # Data alpha is independent of color. Transparency mode would weight RGB by alpha.
            self._bind("nvttSetSurfaceAlphaMode", None, [P, I])(surface, 0)
            self._bind("nvttSetCompressionOptionsFormat", None, [P, I])(
                self.compression, 1 if fourcc == b"DXT1" else 4)
            self.chunks.clear()
            ok = self._bind("nvttContextCompress", I, [P, P, I, I, P, P])(
                self.context, surface, 0, 0, self.compression, self.output)
            self._check(ok, "encode")
            return CompressedFace(face.size, fourcc, b"".join(self.chunks))
        finally:
            self.chunks.clear()
            self._free("Surface", surface)

    def decode(self, face: CompressedFace) -> PixelFace:
        self._same_thread()
        self._check(self._bind("nvttSetMessageCallback", c.c_int, [self.MESSAGE, c.c_void_p])(self.callback, None), "initialize")
        P, I = c.c_void_p, c.c_int
        surface = self._new("Surface")
        try:
            data = c.c_char_p(face.payload)
            ok = self._bind("nvttSurfaceSetImage2D", I, [P, I, I, I, P, P])(
                surface, 1 if face.fourcc == b"DXT1" else 4, face.size, face.size, data, None)
            self._check(ok, "decode")
            pointer = self._bind("nvttSurfaceData", c.POINTER(c.c_float), [P])(surface)
            planes = np.ctypeslib.as_array(pointer, shape=(4 * face.size * face.size,)).reshape(4, face.size, face.size)
            rgb = np.empty((face.size, face.size, 3), dtype=np.uint8)
            for channel in range(3):
                rgb[:, :, channel] = np.clip(np.rint(planes[channel] * 255), 0, 255).astype(np.uint8)
            alpha = (np.clip(np.rint(planes[3] * 255), 0, 255).astype(np.uint8)
                     if face.fourcc == b"DXT5" else None)
            return PixelFace(rgb, alpha)
        finally:
            self._free("Surface", surface)

    def _free(self, kind, handle):
        self._bind("nvttDestroy" + kind, None, [c.c_void_p])(handle)
        self.handles.remove((kind, handle))

    def close(self):
        self._same_thread()
        for kind, handle in reversed(self.handles[:]):
            self._free(kind, handle)
        self._bind("nvttSetMessageCallback", c.c_int, [self.MESSAGE, c.c_void_p])(self.MESSAGE(), None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
