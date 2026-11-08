"""Pixel buffers and block-compressed faces have separate ownership and types."""
from dataclasses import dataclass
from enum import Enum
import numpy as np
from .messages import Message


class ToolError(ValueError):
    def __init__(self, code, *, detail="", **params):
        self.message = Message(code, params, detail)
        super().__init__(code)


FACE_ORDER = ("rt", "lf", "up", "dn", "ft", "bk")


class Game(Enum):
    COD4 = "COD4"
    MW2 = "MW2"
    MW3 = "MW3"

    @property
    def iwi_version(self) -> int:
        return 6 if self is Game.COD4 else 8


@dataclass(frozen=True)
class CompressedFace:
    size: int
    fourcc: bytes
    payload: bytes

    def __post_init__(self):
        if self.size <= 0 or self.size > 32767:
            raise ToolError('error.models.face_size')
        if self.fourcc not in (b"DXT1", b"DXT5"):
            raise ToolError('error.models.compression')
        expected = ((self.size + 3) // 4) ** 2 * (8 if self.fourcc == b"DXT1" else 16)
        if len(self.payload) != expected:
            raise ToolError('error.models.payload', actual=len(self.payload), expected=expected)


@dataclass
class PixelFace:
    rgb: np.ndarray
    alpha: np.ndarray | None = None

    def __post_init__(self):
        if self.rgb.dtype != np.uint8 or self.rgb.ndim != 3 or self.rgb.shape[2] != 3:
            raise ToolError('error.models.rgb_array')
        if self.rgb.shape[0] != self.rgb.shape[1] or not self.rgb.shape[0]:
            raise ToolError('error.models.square')
        if self.alpha is not None and (self.alpha.dtype != np.uint8 or self.alpha.shape != self.rgb.shape[:2]):
            raise ToolError('error.models.alpha_array')

    @property
    def size(self):
        return self.rgb.shape[0]


@dataclass(frozen=True)
class Cubemap:
    faces: tuple[CompressedFace, ...]
    version: int
    flags: int

    def __post_init__(self):
        if len(self.faces) != 6:
            raise ToolError('error.models.six_faces')
        first = self.faces[0]
        if any((f.size, f.fourcc) != (first.size, first.fourcc) for f in self.faces):
            raise ToolError('error.models.matching_faces')

@dataclass(frozen=True)
class RawCubemap:
    faces: tuple[PixelFace, ...]
    version: int
    flags: int
