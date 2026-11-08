"""Stable preview identities and deferred image sources; no translated keys."""
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4
from PIL import Image
from .models import CompressedFace, PixelFace

PREVIEW_CHANNELS = ('RGB', 'Alpha', 'RGBA')


@dataclass(frozen=True)
class PreviewKey:
    layout: str = "face"
    face: str = "ft"
    channel: str = "RGB"
    stage: str = "source"


@dataclass(frozen=True)
class ImageSource:
    kind: str
    path: Path | None = None
    alpha_path: Path | None = None
    face: str = ""
    compressed: CompressedFace | None = None
    cube: tuple[CompressedFace | PixelFace, ...] = ()
    pixel: PixelFace | None = None
    files: tuple[Path, ...] = ()
    panorama_size: int = 0
    panorama_yaw: float = 0.
    repair_seams: bool = True


@dataclass
class PreviewEntry:
    key: PreviewKey
    source: ImageSource
    width: int
    height: int
    thumbnail: Image.Image | None = None


@dataclass(frozen=True)
class Source:
    kind: str
    path: Path | None = None
    alpha: Path | None = None
    face_files: tuple[Path | None, ...] = ()
    panorama_size: int = 0
    panorama_yaw: float = 0.
    repair_seams: bool = True

    @property
    def name(self):
        if self.path: return self.path.name
        return next((p.stem for p in self.face_files if p), 'Cubemap')

    def paths(self):
        return [p for p in (self.path, self.alpha, *self.face_files) if p]

    def record(self):
        return dict(kind=self.kind, path=str(self.path or ''), alpha=str(self.alpha or ''),
                    face_files=[str(p or '') for p in self.face_files],
                    panorama_size=self.panorama_size, panorama_yaw=self.panorama_yaw, repair_seams=self.repair_seams)

    @classmethod
    def restore(cls, record):
        return cls(record['kind'], Path(record['path']) if record['path'] else None,
                   Path(record['alpha']) if record['alpha'] else None,
                   tuple(Path(p) if p else None for p in record.get('face_files', record.get('dds_files', ()))),
                   record.get('panorama_size', 0), record.get('panorama_yaw', 0.), record.get('repair_seams', True))


@dataclass(frozen=True)
class Encoding:
    fourcc: bytes = b'DXT1'
    mode: str = 'CPU'
    quality: str = 'Production'


@dataclass(frozen=True)
class EncodedFace:
    settings: Encoding
    block: CompressedFace


@dataclass
class Document:
    source: Source
    uid: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 1
    ready: bool = False
    entries: dict = field(default_factory=dict)
    thumbnails: dict = field(default_factory=dict)
    encoded: dict[str, EncodedFace] = field(default_factory=dict)
    info: object = None
    size: int = 0
    native_format: bytes = b''
    native: tuple = ()
    error: object = None
    settings: dict = field(default_factory=lambda: dict(output='iwi', game='COD4', fourcc='DXT1',
        mode='CPU', quality='Production', policy='encode', directory='', name='', channel='RGB'))
    view: dict = field(default_factory=lambda: dict(layout='face', face='ft', channel='RGB',
        stage='source', compare='wipe', zoom=1., center=None, fit=True, wipe=.5, camera_z_up=[0., 0., 75.]))
    paths: list = field(default_factory=list)
    settings_initialized: bool = False

    def encoding(self):
        return Encoding(self.settings['fourcc'].encode(), self.settings['mode'], self.settings['quality'])

    def record(self):
        return dict(source=self.source.record(), settings=self.settings, view=self.view)
