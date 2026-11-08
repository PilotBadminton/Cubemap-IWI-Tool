"""Atlas topology, seam repair and bounded-memory panorama sampling."""
from pathlib import Path
import numpy as np
from PIL import Image
from .models import FACE_ORDER, PixelFace, ToolError
from .messages import Progress, msg
from .topology import CUBE_AXES, CUBE_SEAMS, GUTTER_ATLAS_FACE_CELLS

# A valid 4096-face atlas exceeds Pillow's generic photograph pixel heuristic.
Image.MAX_IMAGE_PIXELS = None


def geometry(width: int, height: int) -> tuple[int, int]:
    size = width - height
    padding = height - 3 * size
    if size <= 0 or padding < 0 or padding % 2:
        raise ToolError('error.images.atlas_geometry', width=width, height=height)
    return size, padding // 2


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ToolError('error.images.png_required')
        # RGB values remain independent of embedded transparency.
        return image.convert("RGB")


def read_png_face(path: Path) -> PixelFace:
    with Image.open(path) as image:
        if image.format != 'PNG':
            raise ToolError('error.images.png_required')
        alpha = None
        if 'A' in image.getbands() or 'transparency' in image.info:
            channel = image.convert('RGBA').getchannel('A')
            if channel.getextrema()[0] < 255:
                alpha = np.array(channel)
        return PixelFace(np.array(image.convert('RGB')), alpha)


def open_alpha(path: Path) -> Image.Image:
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "L":
            raise ToolError('error.images.alpha_png')
        return image.copy()


def split_atlas(rgb_path: Path, alpha_path: Path | None = None, previews=None) -> tuple[int, int, dict[str, PixelFace]]:
    rgb = open_rgb(rgb_path)
    alpha = None
    try:
        size, gutter = geometry(*rgb.size)
        if alpha_path is not None:
            alpha = open_alpha(alpha_path)
            if alpha.size != rgb.size:
                raise ToolError('error.images.atlas_sizes')
        if previews is not None:
            scale = min(1, 1200 / rgb.width, 900 / rgb.height)
            thumb_size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
            previews[("atlas", "RGB")] = rgb.resize(thumb_size, Image.Resampling.LANCZOS)
            if alpha is not None:
                previews[("atlas", "Alpha")] = alpha.resize(thumb_size, Image.Resampling.LANCZOS)
        faces = {}
        for suffix, (col, row) in GUTTER_ATLAS_FACE_CELLS.items():
            x, y = gutter + col * size, gutter + row * size
            box = (x, y, x + size, y + size)
            faces[suffix] = PixelFace(np.array(rgb.crop(box)), np.array(alpha.crop(box)) if alpha else None)
    finally:
        rgb.close()
        if alpha is not None:
            alpha.close()
    repair_seams(faces)
    return size, gutter, faces


def edge_positions(side, size, width):
    along = np.broadcast_to(np.arange(size)[:, None], (size, width))
    depth = np.broadcast_to(np.arange(width)[None, :], (size, width))
    if side == "left":
        x, y = depth, along
    elif side == "right":
        x, y = size - 1 - depth, along
    elif side == "top":
        x, y = along, depth
    else:
        x, y = along, size - 1 - depth
    return y * size + x


def repair_seams(faces: dict[str, PixelFace]):
    """Original four-pixel algorithm; snapshot only edge strips, then combine corners."""
    size = faces["rt"].size
    proposals = seam_proposals(size, lambda face, side, width: _edge_strip(faces[face].rgb, side, width))
    for suffix in FACE_ORDER:
        apply_seams(faces[suffix].rgb, proposals[suffix])


def seam_proposals(size, read_strip):
    """Read original edge strips once; the repair math is shared by both loaders."""
    width = min(4, size)
    falloff = np.array([1, .75, .5, .25], dtype=np.float64)[:width, None]
    proposals = {suffix: [] for suffix in FACE_ORDER}
    for af, aside, bf, bside, reverse in CUBE_SEAMS:
        ai, bi = edge_positions(aside, size, width), edge_positions(bside, size, width)
        if reverse:
            bi = bi[::-1]
        av = read_strip(af, aside, width).astype(np.float64)
        bv = read_strip(bf, bside, width).astype(np.float64)
        if reverse:
            bv = bv[::-1]
        diff = av.mean(axis=1) - bv.mean(axis=1)
        padded = np.pad(diff, ((2, 2), (0, 0)), mode="edge")
        smooth = sum(padded[i:i + size] for i in range(5)) / 5
        anew = np.clip(np.rint(av - smooth[:, None, :] * .5 * falloff), 0, 255)
        bnew = np.clip(np.rint(bv + smooth[:, None, :] * .5 * falloff), 0, 255)
        average = np.floor((av[:, 0] + bv[:, 0]) / 2)
        anew[:, 0] = bnew[:, 0] = average
        proposals[af].append((ai.ravel(), anew.reshape(-1, 3)))
        proposals[bf].append((bi.ravel(), bnew.reshape(-1, 3)))
    return proposals


def apply_seams(rgb, parts):
    indices = np.concatenate([p[0] for p in parts])
    values = np.concatenate([p[1] for p in parts])
    unique, inverse, counts = np.unique(indices, return_inverse=True, return_counts=True)
    for channel in range(3):
        summed = np.bincount(inverse, weights=values[:, channel])
        rgb.reshape(-1, 3)[unique, channel] = np.rint(summed / counts).astype(np.uint8)


class AtlasReader:
    """One decoded cross, one face at a time; Alpha never enters RGB repair."""
    def __init__(self, path, alpha_path=None, repair=True):
        self.rgb = open_rgb(path)
        self.alpha = None
        try:
            self.size, self.gutter = geometry(*self.rgb.size)
            if alpha_path:
                self.alpha = open_alpha(alpha_path)
                if self.alpha.size != self.rgb.size:
                    raise ToolError('error.images.atlas_sizes')
            self.proposals = seam_proposals(self.size, self.strip) if repair else None
        except Exception:
            self.close()
            raise

    def box(self, face):
        col, row = GUTTER_ATLAS_FACE_CELLS[face]
        x, y = self.gutter + col*self.size, self.gutter + row*self.size
        return x, y, x+self.size, y+self.size

    def strip(self, face, side, width):
        x, y, right, bottom = self.box(face)
        if side == 'left': box = x, y, x+width, bottom
        elif side == 'right': box = right-width, y, right, bottom
        elif side == 'top': box = x, y, right, y+width
        else: box = x, bottom-width, right, bottom
        array = np.array(self.rgb.crop(box))
        if side == 'right': return array[:, ::-1]
        if side == 'top': return array.transpose(1, 0, 2)
        if side == 'bottom': return array[::-1].transpose(1, 0, 2)
        return array

    def face(self, name):
        rgb = np.array(self.rgb.crop(self.box(name)))
        if self.proposals is not None:
            apply_seams(rgb, self.proposals[name])
        alpha = np.array(self.alpha.crop(self.box(name))) if self.alpha else None
        return PixelFace(rgb, alpha)

    def close(self):
        self.rgb.close()
        if self.alpha is not None: self.alpha.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()



class PanoramaReader:
    """Full sphere, +Z at the top, -Y at the center, +X to the right."""

    def __init__(self, path, size=0, yaw=0., checkpoint=lambda: None):
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise ToolError('error.images.png_required')
            self.width, self.height = image.size
            if self.width != self.height * 2:
                raise ToolError('error.panorama_geometry', width=self.width, height=self.height)
            self.has_alpha = 'A' in image.getbands() or 'transparency' in image.info
            self.pixels = np.array(image.convert('RGBA' if self.has_alpha else 'RGB'))
        self.size = size or max((s for s in (512, 1024, 2048, 4096) if s <= self.width // 4), default=512)
        if self.size not in (512, 1024, 2048, 4096):
            raise ToolError('error.panorama_size')
        self.yaw = np.radians(yaw)
        self.checkpoint = checkpoint

    def face(self, name, size=None):
        size = size or self.size
        channels = self.pixels.shape[2]
        output = np.empty((size, size, channels), dtype=np.uint8)
        normal, right, down = CUBE_AXES[name]
        u = ((np.arange(size, dtype=np.float32) + .5) * (2 / size) - 1)[None, :]
        for start in range(0, size, 32):
            self.checkpoint()
            end = min(start + 32, size)
            v = ((np.arange(start, end, dtype=np.float32) + .5) * (2 / size) - 1)[:, None]
            x, y, z = (normal[i] + u * right[i] + v * down[i] for i in range(3))
            longitude = np.arctan2(x, -y) - self.yaw
            latitude = np.arctan2(z, np.sqrt(x*x + y*y))
            sx = ((longitude / (2*np.pi) + .5) * self.width - .5) % self.width
            sy = np.clip((.5 - latitude / np.pi) * self.height - .5, 0, self.height-1)
            ix, iy = np.floor(sx).astype(np.int32), np.floor(sy).astype(np.int32)
            ix1, iy1 = (ix+1) % self.width, np.minimum(iy+1, self.height-1)
            fx, fy = (sx-ix)[..., None], (sy-iy)[..., None]
            top = self.pixels[iy, ix] * (1-fx) + self.pixels[iy, ix1] * fx
            bottom = self.pixels[iy1, ix] * (1-fx) + self.pixels[iy1, ix1] * fx
            output[start:end] = np.rint(top * (1-fy) + bottom * fy).clip(0, 255).astype(np.uint8)
        return PixelFace(output[..., :3].copy(), output[..., 3].copy() if self.has_alpha else None)

    def close(self):
        self.pixels = None

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def _edge_strip(face, side, width):
    if side == "left": return face[:, :width]
    if side == "right": return face[:, -width:][:, ::-1]
    if side == "top": return face[:width].transpose(1, 0, 2)
    return face[-width:][::-1].transpose(1, 0, 2)


def atlas(faces: dict[str, PixelFace], alpha=False, gutter=16) -> Image.Image:
    size = faces["rt"].size
    gutter = min(gutter, size - 1)
    arrays = {s: (f.alpha if f.alpha is not None else np.full((size, size), 255, np.uint8))[:, :, None]
              if alpha else f.rgb for s, f in faces.items()}
    channels = 1 if alpha else 3
    samples = [a[::max(1, size // 128), ::max(1, size // 128)].reshape(-1, channels) for a in arrays.values()]
    bg = np.concatenate(samples).mean(axis=0).round().astype(np.uint8)
    result = np.empty((3 * size + 2 * gutter, 4 * size + 2 * gutter, channels), dtype=np.uint8)
    result[:] = bg

    def paste(dst, side, src, src_side, reverse):
        if not gutter: return
        strip = _edge_strip(arrays[src], src_side, gutter)
        if reverse: strip = strip[::-1]
        col, row = GUTTER_ATLAS_FACE_CELLS[dst]
        x, y = gutter + col * size, gutter + row * size
        if side == "left": result[y:y+size, x-gutter:x] = strip[:, ::-1]
        elif side == "right": result[y:y+size, x+size:x+size+gutter] = strip
        elif side == "top": result[y-gutter:y, x:x+size] = strip[:, ::-1].transpose(1, 0, 2)
        else: result[y+size:y+size+gutter, x:x+size] = strip.transpose(1, 0, 2)
    for af, aside, bf, bside, reverse in CUBE_SEAMS:
        paste(af, aside, bf, bside, reverse)
        paste(bf, bside, af, aside, reverse)
    for suffix, (col, row) in GUTTER_ATLAS_FACE_CELLS.items():
        x, y = gutter + col * size, gutter + row * size
        result[y:y+size, x:x+size] = arrays[suffix]
    return Image.fromarray(result[:, :, 0] if alpha else result)


def mosaic(faces: dict[str, PixelFace], alpha=False) -> Image.Image:
    size = faces["rt"].size
    result = Image.new("L" if alpha else "RGB", (size * 3, size * 2))
    for i, suffix in enumerate(FACE_ORDER):
        face = faces[suffix]
        result.paste(pixel_image(face, 'Alpha' if alpha else 'RGB'), (i % 3 * size, i // 3 * size))
    return result


def panorama(faces: dict[str, PixelFace], alpha=False, progress=lambda *args: None) -> Image.Image:
    size = faces["rt"].size
    width, height = size * 4, size * 2
    result = Image.new("L" if alpha else "RGB", (width, height))
    longitude = ((np.arange(width, dtype=np.float32) + .5) / width * (2*np.pi) - np.pi)[None, :]
    for start in range(0, height, 32):
        end = min(start + 32, height)
        latitude = ((.5 - (np.arange(start, end, dtype=np.float32) + .5) / height) * np.pi)[:, None]
        dx = np.sin(longitude) * np.cos(latitude)
        dy = -np.cos(longitude) * np.cos(latitude)
        dz = np.broadcast_to(np.sin(latitude), (end-start, width))
        ax, ay, az = np.abs(dx), np.abs(dy), np.abs(dz)
        mx = (ax >= ay) & (ax >= az)
        my = (ay >= ax) & (ay >= az) & ~mx
        mz = ~mx & ~my
        directions = (dx, dy, dz)
        major = np.where(mx, 0, np.where(my, 1, 2))
        shape = dx.shape if alpha else (*dx.shape, 3)
        tile = np.empty(shape, dtype=np.uint8)
        for suffix in FACE_ORDER:
            normal, right, down = CUBE_AXES[suffix]
            axis = next(i for i, value in enumerate(normal) if value)
            depth = directions[axis] * normal[axis]
            mask = (major == axis) & (depth > 0)
            if not np.any(mask):
                continue
            u_axis = next(i for i, value in enumerate(right) if value)
            v_axis = next(i for i, value in enumerate(down) if value)
            u = directions[u_axis][mask] * right[u_axis] / depth[mask]
            v = directions[v_axis][mask] * down[v_axis] / depth[mask]
            x = np.clip((u + 1) * .5 * size - .5, 0, size - 1)
            y = np.clip((v + 1) * .5 * size - .5, 0, size - 1)
            ix, iy = x.astype(np.int32), y.astype(np.int32)
            fx, fy = x-ix, y-iy
            ix1, iy1 = np.minimum(ix+1, size-1), np.minimum(iy+1, size-1)
            image = faces[suffix].alpha if alpha else faces[suffix].rgb
            if image is None:
                tile[mask] = 255
                continue
            if not alpha: fx, fy = fx[:, None], fy[:, None]
            top = image[iy, ix] * (1-fx) + image[iy, ix1] * fx
            bottom = image[iy1, ix] * (1-fx) + image[iy1, ix1] * fx
            tile[mask] = np.clip(np.rint(top * (1-fy) + bottom * fy), 0, 255).astype(np.uint8)
        result.paste(Image.fromarray(tile), (0, start))
        progress(Progress(msg("progress.panorama", done=end, total=height), end, height))
    return result


def pixel_image(pixel, channel):
    if channel == 'Alpha':
        return Image.fromarray(pixel.alpha) if pixel.alpha is not None else Image.new('L', (pixel.size, pixel.size), 255)
    result = Image.fromarray(pixel.rgb)
    if channel == 'RGBA':
        result = result.convert('RGBA')
        if pixel.alpha is not None:
            result.putalpha(Image.fromarray(pixel.alpha))
    return result


def save_png(image: Image.Image, path: Path):
    image.save(path, format="PNG", compress_level=1)
