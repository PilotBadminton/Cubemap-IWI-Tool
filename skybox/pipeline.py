"""Document inspection, per-face compression and export; no GUI ownership."""
from dataclasses import dataclass, field
from contextlib import contextmanager, ExitStack
from tempfile import NamedTemporaryFile
from pathlib import Path
from threading import Event
from PIL import Image
from .document import Source, Encoding, EncodedFace, PreviewKey, PreviewEntry, ImageSource, PREVIEW_CHANNELS
from .models import FACE_ORDER, Game, Cubemap, PixelFace, RawCubemap, ToolError
from .formats import parse_dds, parse_iwi, dds_bytes, iwi_bytes, rgb24_header
from .nvtt import Codec
from .messages import Progress, msg
from . import images


class Cancelled(Exception):
    pass


def checkpoint(cancel):
    if cancel.is_set(): raise Cancelled()


@dataclass(frozen=True)
class Job:
    action: str
    source: Source
    settings: Encoding = field(default_factory=Encoding)
    face: str = 'ft'
    output: Path | None = None
    name: str = ''
    game: str = 'COD4'
    policy: str = 'encode'
    native: tuple = ()
    cached: tuple = ()
    cancel: Event = field(default_factory=Event, compare=False)
    channel: str = 'RGB'


@dataclass
class Result:
    message: object
    entries: dict = field(default_factory=dict)
    native: tuple = ()
    size: int = 0
    fourcc: bytes = b''
    paths: list = field(default_factory=list)
    thumbnails: dict = field(default_factory=dict)
    iwi_version: int = 0


def thumbnail(image):
    result = image.copy()
    result.thumbnail((384, 384), Image.Resampling.LANCZOS)
    return result


def face_entries(entries, face, source, pixel=None, size=0, alpha=False, stage='source'):
    for channel in PREVIEW_CHANNELS if alpha else ('RGB',):
        key = PreviewKey('face', face, channel, stage)
        thumb = thumbnail(Image.fromarray(pixel.rgb if channel == 'RGB' else pixel.alpha)) if pixel is not None and channel != 'RGBA' else None
        entries[key] = PreviewEntry(key, source, pixel.size if pixel else size, pixel.size if pixel else size, thumb)


def layout_entries(entries, source, size, alpha):
    g = min(16, size-1)
    for layout, width, height in (('atlas', size*4+2*g, size*3+2*g), ('mosaic', size*3, size*2), ('panorama', size*4, size*2)):
        for channel in PREVIEW_CHANNELS if alpha else ('RGB',):
            key = PreviewKey(layout, '', channel, 'source')
            entries[key] = PreviewEntry(key, source, width, height)


def inspect(source, progress, cancel):
    entries = {}
    for path in source.paths():
        if not path.is_file(): raise ToolError('error.source_missing', path=str(path))
    if source.kind == 'panorama':
        with images.PanoramaReader(source.path, source.panorama_size, source.panorama_yaw,
                                   lambda: checkpoint(cancel)) as reader:
            size = reader.size
            for index, face in enumerate(FACE_ORDER):
                checkpoint(cancel)
                progress(Progress(msg('progress.inspect', face=msg('face.'+face)), index, 6))
                pixel = reader.face(face, min(size, 384))
                spec = ImageSource('panorama_face', path=source.path, face=face,
                                   panorama_size=size, panorama_yaw=source.panorama_yaw)
                face_entries(entries, face, spec, size=size, alpha=reader.has_alpha)
                for channel, array in (('RGB', pixel.rgb), ('Alpha', pixel.alpha)):
                    if array is not None:
                        entries[PreviewKey('face', face, channel, 'source')].thumbnail = Image.fromarray(array)
            layout_entries(entries, ImageSource('panorama_layout', path=source.path,
                           panorama_size=size, panorama_yaw=source.panorama_yaw), size, reader.has_alpha)
            for channel in PREVIEW_CHANNELS if reader.has_alpha else ('RGB',):
                key = PreviewKey('panorama', '', channel, 'original')
                entries[key] = PreviewEntry(key, ImageSource('panorama_original', path=source.path),
                                            reader.width, reader.height)
            return Result(msg('summary.panorama', width=reader.width, height=reader.height,
                              size=size, yaw=source.panorama_yaw), entries, size=size)
    if source.kind == 'atlas':
        with images.AtlasReader(source.path, source.alpha, source.repair_seams) as reader:
            size, gutter = reader.size, reader.gutter
            for index, face in enumerate(FACE_ORDER):
                checkpoint(cancel)
                progress(Progress(msg('progress.inspect', face=msg('face.'+face)), index, 6))
                pixel = reader.face(face)
                face_entries(entries, face, ImageSource('atlas_face', path=source.path, alpha_path=source.alpha, face=face, repair_seams=source.repair_seams),
                             pixel, alpha=source.alpha is not None)
            for channel, image, path in (('RGB', reader.rgb, source.path), ('Alpha', reader.alpha, source.alpha)):
                if image is None: continue
                key = PreviewKey('atlas', '', channel, 'original')
                entries[key] = PreviewEntry(key, ImageSource('file', path=path), image.width, image.height, thumbnail(image))
            if reader.alpha is not None:
                key = PreviewKey('atlas', '', 'RGBA', 'original')
                entries[key] = PreviewEntry(key, ImageSource('file', path=source.path, alpha_path=source.alpha),
                                            reader.rgb.width, reader.rgb.height)
        layout_entries(entries, ImageSource('atlas_layout', path=source.path, alpha_path=source.alpha, repair_seams=source.repair_seams), size, source.alpha is not None)
        return Result(msg('summary.atlas', size=size, gutter=gutter), entries, size=size)
    if source.kind == 'png_faces':
        if len(source.face_files) != 6 or not all(source.face_files):
            raise ToolError('error.png_six')
        size = None
        all_alpha = True
        for index, (name, path) in enumerate(zip(FACE_ORDER, source.face_files)):
            checkpoint(cancel)
            progress(Progress(msg('progress.inspect', face=msg('face.'+name)), index, 6))
            pixel = images.read_png_face(path)
            if size is not None and size != pixel.size:
                raise ToolError('error.png_dimensions', face=msg('face.'+name))
            size = pixel.size
            all_alpha &= pixel.alpha is not None
            face_entries(entries, name, ImageSource('png_face', path=path), pixel, alpha=pixel.alpha is not None)
        layout_entries(entries, ImageSource('png_layout', files=source.face_files), size, all_alpha)
        return Result(msg('summary.png_faces', size=size), entries, size=size)
    if source.kind == 'iwi':
        cube = parse_iwi(source.path)
        native = cube.faces
        if isinstance(cube, RawCubemap):
            size = native[0].size
            for name, pixel in zip(FACE_ORDER, native):
                checkpoint(cancel)
                face_entries(entries, name, ImageSource('pixel', pixel=pixel), pixel)
            layout_entries(entries, ImageSource('layout', cube=native), size, False)
            return Result(msg('summary.iwi', size=size, format='RGB24', version=cube.version, flags=cube.flags),
                          entries, native, size, b'RGB24', iwi_version=cube.version)
        summary = msg('summary.iwi', size=native[0].size, format=native[0].fourcc.decode(), version=cube.version, flags=cube.flags)
    else:
        native = tuple(parse_dds(path) if path else None for path in source.face_files)
        if len(native) != 6: raise ToolError('error.dds_six')
        present = tuple(face for face in native if face)
        if not present: raise ToolError('error.dds_six')
        first = present[0]
        if any((f.size, f.fourcc) != (first.size, first.fourcc) for f in present):
            raise ToolError('error.models.matching_faces')
        summary = msg('summary.dds', count=len(present), size=first.size, format=first.fourcc.decode())
    first = next(f for f in native if f)
    with Codec('CPU') as codec:
        for index, (name, face) in enumerate(zip(FACE_ORDER, native)):
            checkpoint(cancel)
            if face is None: continue
            progress(Progress(msg('progress.inspect', face=msg('face.'+name)), index, 6))
            pixel = codec.decode(face)
            face_entries(entries, name, ImageSource('compressed', compressed=face), pixel, alpha=face.fourcc == b'DXT5')
    if all(native):
        Cubemap(native, 6, 0)
        layout_entries(entries, ImageSource('layout', cube=native), first.size, first.fourcc == b'DXT5')
    return Result(summary, entries, native, first.size, first.fourcc)


class PixelReader:
    def __init__(self, source, native, cancel=None):
        self.source, self.native = source, native
        if source.kind == 'panorama':
            self.reader = images.PanoramaReader(source.path, source.panorama_size, source.panorama_yaw,
                (lambda: checkpoint(cancel)) if cancel is not None else (lambda: None))
        elif source.kind == 'atlas':
            self.reader = images.AtlasReader(source.path, source.alpha, source.repair_seams)
        elif source.kind == 'png_faces' or isinstance(next((f for f in native if f is not None), None), PixelFace):
            self.reader = None
        else:
            self.reader = Codec('CPU')

    def face(self, name):
        if self.source.kind in ('atlas', 'panorama'): return self.reader.face(name)
        index = FACE_ORDER.index(name)
        if self.source.kind == 'png_faces':
            return images.read_png_face(self.source.face_files[index])
        block = self.native[index]
        if isinstance(block, PixelFace):
            return block
        if block is None: raise ToolError('error.dds_six')
        return self.reader.decode(block)

    def __enter__(self): return self
    def __exit__(self, *args):
        if self.reader is not None: self.reader.close()


def make_layout(layout, pixels, alpha, progress):
    if layout == 'atlas': return images.atlas(pixels, alpha)
    if layout == 'mosaic': return images.mosaic(pixels, alpha)
    return images.panorama(pixels, alpha, progress)


def load_preview(entry, cancel):
    source, key = entry.source, entry.key
    checkpoint(cancel)
    if source.kind == 'panorama_original':
        with Image.open(source.path) as image:
            if key.channel == 'Alpha':
                return image.convert('RGBA').getchannel('A')
            return image.convert('RGBA' if key.channel == 'RGBA' else 'RGB')
    if source.kind == 'file':
        with Image.open(source.path) as image:
            result = image.convert('L' if key.channel == 'Alpha' else 'RGB')
        if key.channel == 'RGBA':
            with Image.open(source.alpha_path) as alpha:
                result.putalpha(alpha.convert('L'))
        return result
    if source.kind == 'panorama_face':
        with images.PanoramaReader(source.path, source.panorama_size, source.panorama_yaw,
                                   lambda: checkpoint(cancel)) as reader:
            pixel = reader.face(source.face)
    elif source.kind == 'atlas_face':
        with images.AtlasReader(source.path, source.alpha_path, source.repair_seams) as reader: pixel = reader.face(source.face)
    elif source.kind == 'png_face':
        pixel = images.read_png_face(source.path)
    elif source.kind == 'pixel':
        pixel = source.pixel
    elif source.kind == 'compressed':
        with Codec('CPU') as codec: pixel = codec.decode(source.compressed)
    else:
        if source.kind == 'panorama_layout':
            spec = Source('panorama', source.path, panorama_size=source.panorama_size, panorama_yaw=source.panorama_yaw)
            native = ()
        elif source.kind == 'atlas_layout':
            spec, native = Source('atlas', source.path, source.alpha_path, repair_seams=source.repair_seams), ()
        elif source.kind == 'png_layout':
            spec, native = Source('png_faces', face_files=source.files), ()
        else:
            spec, native = Source('dds'), source.cube
        pixels = {}
        with PixelReader(spec, native, cancel) as reader:
            for face in FACE_ORDER:
                checkpoint(cancel)
                pixels[face] = reader.face(face)
        progress = lambda event: checkpoint(cancel)
        result = make_layout(key.layout, pixels, key.channel == 'Alpha', progress)
        if key.channel == 'RGBA':
            checkpoint(cancel)
            result.putalpha(make_layout(key.layout, pixels, True, progress))
        return result
    checkpoint(cancel)
    if key.channel != 'RGB' and pixel.alpha is None:
        raise ToolError('error.preview_alpha')
    result = Image.fromarray(pixel.alpha if key.channel == 'Alpha' else pixel.rgb)
    if key.channel == 'RGBA':
        result.putalpha(Image.fromarray(pixel.alpha))
    return result



def output_paths(job):
    if job.action == 'preview':
        return []
    stem = job.name or Path(job.source.name).stem
    if job.action in ('iwi', 'rgb24'):
        return [job.output / f'{stem}.iwi']
    alpha = '_alpha_data' if job.channel == 'Alpha' else ''
    if job.action in ('dds', 'png'):
        extension = 'dds' if job.action == 'dds' else 'png'
        return [job.output / f"{stem}_{face}{alpha if extension == 'png' else ''}.{extension}" for face in FACE_ORDER]
    return [job.output / f"{stem}_{'alpha_data_' if job.channel == 'Alpha' else ''}{job.action}.png"]


@contextmanager
def atomic_output(path):
    with NamedTemporaryFile(mode='wb', dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            yield stream
            stream.close()
            temporary.replace(path)
        finally:
            stream.close()
            temporary.unlink(missing_ok=True)


def run(job, progress, on_face):
    """An immutable job snapshot; cancellation is checked at face boundaries."""
    checkpoint(job.cancel)
    if job.action not in ('preview', 'iwi', 'rgb24', 'dds', 'png', 'atlas', 'mosaic', 'panorama'):
        raise ToolError('error.unknown_action', action=job.action)
    if job.channel not in PREVIEW_CHANNELS:
        raise ToolError('error.export_channel', channel=job.channel)
    if job.source.kind == 'png_faces' and (len(job.source.face_files) != 6 or not all(job.source.face_files)):
        raise ToolError('error.png_six')
    names = (job.face,) if job.action == 'preview' else FACE_ORDER
    cached = dict(job.cached)
    paths, blocks = output_paths(job), []
    encoding = job.action == 'preview' or (job.action in ('iwi', 'dds') and job.policy == 'encode')
    if job.policy == 'preserve' and job.action in ('iwi', 'dds'):
        if len(job.native) != 6 or not all(job.native): raise ToolError('error.dds_six')
    if job.action != 'preview': job.output.mkdir(parents=True, exist_ok=True)
    reader = None
    codec = None
    pixels = {}
    raw_header = None
    raw_game = Game(job.game) if job.action == 'rgb24' else None
    try:
        with ExitStack() as outputs:
            if job.action == 'rgb24' and job.source.kind == 'atlas':
                with Image.open(job.source.path) as image:
                    if 'A' in image.getbands() or 'transparency' in image.info:
                        alpha = image.convert('RGBA').getchannel('A')
                        reader = PixelReader(job.source, job.native, job.cancel)
                        for name in names:
                            if alpha.crop(reader.reader.box(name)).getextrema()[0] < 255:
                                raise ToolError('error.rgb24_alpha', face=msg('face.'+name))
            for index, name in enumerate(names):
                checkpoint(job.cancel)
                progress(Progress(msg('progress.process_face', face=msg('face.'+name)), index, len(names)))
                pixel = None
                stored = cached.get(name)
                need_pixel = job.action in ('rgb24', 'png', 'atlas', 'mosaic', 'panorama')
                need_encode = encoding and (stored is None or stored.settings != job.settings)
                if need_pixel or need_encode:
                    if reader is None: reader = PixelReader(job.source, job.native, job.cancel)
                    pixel = reader.face(name)
                if job.action == 'rgb24':
                    header = rgb24_header(pixel.size, raw_game)
                    if raw_header is not None and header != raw_header:
                        raise ToolError('error.png_dimensions', face=msg('face.'+name))
                    if pixel.alpha is not None and pixel.alpha.min() < 255:
                        raise ToolError('error.rgb24_alpha', face=msg('face.'+name))
                    if raw_header is None:
                        raw_header = header
                        raw_output = outputs.enter_context(atomic_output(paths[0]))
                        raw_output.write(header)
                    raw_output.write(pixel.rgb[..., ::-1].tobytes())
                if encoding:
                    if need_encode:
                        if job.settings.fourcc == b'DXT5' and pixel.alpha is None: raise ToolError('error.alpha_required')
                        if job.settings.fourcc == b'DXT1' and job.source.kind == 'atlas' and job.source.alpha is not None:
                            raise ToolError('error.alpha_bc1')
                        if codec is None: codec = Codec(job.settings.mode, job.settings.quality)
                        try: block = codec.encode(pixel, job.settings.fourcc)
                        except ToolError as error:
                            raise ToolError('error.face_operation', face=msg('face.'+name), reason=error.message) from error
                        stored = EncodedFace(job.settings, block)
                    block = stored.block
                    on_face(name, stored)
                elif job.action in ('iwi', 'dds'):
                    block = job.native[index]
                if job.action in ('iwi', 'dds', 'preview'):
                    blocks.append(block)
                    if job.action == 'dds':
                        paths[index].write_bytes(dds_bytes(block))
                if job.action == 'png':
                    images.save_png(images.pixel_image(pixel, job.channel), paths[index])
                elif job.action in ('atlas', 'mosaic', 'panorama'):
                    pixels[name] = pixel
                del pixel
            checkpoint(job.cancel)
            if job.action == 'iwi':
                with atomic_output(paths[0]) as output:
                    output.write(iwi_bytes(tuple(blocks), Game(job.game)))
            elif job.action in ('atlas', 'mosaic', 'panorama'):
                reader.__exit__(); reader = None
                notify = lambda event: (checkpoint(job.cancel), progress(event))
                image = make_layout(job.action, pixels, job.channel == 'Alpha', notify)
                if job.channel == 'RGBA':
                    image.putalpha(make_layout(job.action, pixels, True, notify))
                checkpoint(job.cancel)
                images.save_png(image, paths[0])
                image.close()
        progress(Progress(msg('progress.complete'), 1, 1))
        return Result(msg('result.preview_face', face=msg('face.'+job.face)) if job.action == 'preview'
                      else msg('result.exported', count=len(paths)), paths=paths)
    finally:
        if reader is not None: reader.__exit__()
        if codec is not None: codec.close()
