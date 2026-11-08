import struct
import numpy as np
from .models import PixelFace, RawCubemap
from pathlib import Path
from .models import ToolError as CubemapIwiError, FACE_ORDER, CompressedFace, Cubemap, Game

IWI_VERSION_COD4 = 6
IWI_VERSION_MW2 = 8

IWI_HEADER_SIZE_COD4 = 28
IWI_HEADER_SIZE_MW2 = 32

IWI_FORMAT_RGB24 = 0x02
IWI_FLAGS_RGB24_V8 = 0x10032  # Cube, no mipmaps, clamp U/V.

IWI_FORMAT_DXT1 = 0x0B
IWI_FORMAT_DXT5 = 0x0D

# MW2/COD6 (IWI V8) skybox flags:
IWI_FLAGS_SKY_DXT1 = 0x00010372
IWI_FLAGS_SKY_DXT5 = 0x00090372

DDS_MAGIC = b"DDS "
DDS_HEADER_SIZE = 124
DDS_PIXELFORMAT_SIZE = 32
DDS_FOURCC = 0x00000004
DDSD_CAPS = 0x00000001
DDSD_HEIGHT = 0x00000002
DDSD_WIDTH = 0x00000004
DDSD_LINEARSIZE = 0x00080000
DDSD_PIXELFORMAT = 0x00001000
DDSD_MIPMAPCOUNT = 0x00020000
DDSCAPS_TEXTURE = 0x00001000
DDSCAPS2_CUBEMAP = 0x00000200
DDS_FOURCC_DX10 = b"DX10"


def _block_size(fourcc: bytes) -> int:
    if fourcc == b"DXT1":
        return 8
    if fourcc == b"DXT5":
        return 16
    raise CubemapIwiError('error.formats.unsupported_fourcc', format=fourcc.decode('ascii', errors='replace'))

def _iwi_format_and_flags(fourcc: bytes) -> tuple[int, int, str]:
    if fourcc == b"DXT1":
        return IWI_FORMAT_DXT1, IWI_FLAGS_SKY_DXT1, "DDS / DXT1"
    if fourcc == b"DXT5":
        return IWI_FORMAT_DXT5, IWI_FLAGS_SKY_DXT5, "DDS / DXT5"
    raise CubemapIwiError('error.formats.dds_format', format=repr(fourcc))

def _fourcc_from_iwi_format(iwi_format: int) -> tuple[bytes, str]:
    if iwi_format == IWI_FORMAT_DXT1:
        return b"DXT1", "DDS / DXT1"
    if iwi_format == IWI_FORMAT_DXT5:
        return b"DXT5", "DDS / DXT5"
    raise CubemapIwiError('error.formats.iwi_format', format=iwi_format)

def expected_face_payload_size(width: int, height: int, fourcc: bytes) -> int:
    block = _block_size(fourcc)
    bw = max(1, (width + 3) // 4)
    bh = max(1, (height + 3) // 4)
    return bw * bh * block

def _parse_dds(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 128:
        raise CubemapIwiError('error.formats.dds_short')

    if data[:4] != DDS_MAGIC:
        raise CubemapIwiError('error.formats.dds_magic')

    header_size = struct.unpack_from("<I", data, 4)[0]
    if header_size != DDS_HEADER_SIZE:
        raise CubemapIwiError('error.formats.dds_header', actual=header_size)

    flags = struct.unpack_from("<I", data, 8)[0]
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mipmap_count = struct.unpack_from("<I", data, 28)[0]

    pf_size = struct.unpack_from("<I", data, 76)[0]
    if pf_size != DDS_PIXELFORMAT_SIZE:
        raise CubemapIwiError('error.formats.dds_pixel_header', actual=pf_size)

    pf_flags = struct.unpack_from("<I", data, 80)[0]
    fourcc = data[84:88]
    caps2 = struct.unpack_from("<I", data, 112)[0]

    if width <= 0 or height <= 0:
        raise CubemapIwiError('error.formats.dds_dimensions')
    if width != height:
        raise CubemapIwiError('error.formats.dds_square', width=width, height=height)

    if pf_flags & DDS_FOURCC == 0:
        raise CubemapIwiError('error.formats.dds_fourcc')

    if fourcc == DDS_FOURCC_DX10:
        raise CubemapIwiError('error.formats.dds_dx10')

    if caps2 & DDSCAPS2_CUBEMAP:
        raise CubemapIwiError('error.formats.dds_cube')

    effective_mips = mipmap_count if (flags & DDSD_MIPMAPCOUNT) else 1
    if effective_mips != 1:
        raise CubemapIwiError('error.formats.dds_mips', count=effective_mips)

    payload = data[128:]
    expected_size = expected_face_payload_size(width, height, fourcc)
    if len(payload) != expected_size:
        raise CubemapIwiError('error.formats.dds_payload', actual=len(payload), expected=expected_size)

    iwi_format, stock_flags, format_name = _iwi_format_and_flags(fourcc)
    return {
        "path": path,
        "width": width,
        "height": height,
        "fourcc": fourcc,
        "format_name": format_name,
        "iwi_format": iwi_format,
        "flags": stock_flags,
        "payload": payload,
        "payload_size": len(payload),
    }

def _build_iwi(face_infos: list[dict], version: int) -> bytes:
    if len(face_infos) != 6:
        raise CubemapIwiError('error.formats.dds_faces')

    first = face_infos[0]
    width = first["width"]
    height = first["height"]
    fourcc = first["fourcc"]

    for info in face_infos[1:]:
        if info["width"] != width or info["height"] != height:
            raise CubemapIwiError('error.formats.dds_sizes')
        if info["fourcc"] != fourcc:
            raise CubemapIwiError('error.formats.dds_formats')

    iwi_format, stock_flags, _ = _iwi_format_and_flags(fourcc)
    total_payload_size = sum(info["payload_size"] for info in face_infos)

    if version == 6:
        header_size = IWI_HEADER_SIZE_COD4
        total_file_size = header_size + total_payload_size
        header = struct.pack(
            "<3sBBBhhh4i",
            b"IWi",
            IWI_VERSION_COD4,
            iwi_format,
            0xC6,                    # unknown byte
            width, height, 1,
            total_file_size,
            total_file_size,
            total_file_size,
            total_file_size,
        )
    elif version == 8:
        header_size = IWI_HEADER_SIZE_MW2
        total_file_size = header_size + total_payload_size
        header = struct.pack(
            "<3sBiBxhhh4i",
            b"IWi",
            IWI_VERSION_MW2,
            stock_flags,
            iwi_format,
            width, height, 1,
            total_file_size,
            total_file_size,
            total_file_size,
            total_file_size,
        )

    else:
        raise CubemapIwiError('error.formats.iwi_version', version=version)

    if len(header) != header_size:
        raise CubemapIwiError('error.formats.iwi_header_size', actual=len(header), expected=header_size)

    return header + b"".join(info["payload"] for info in face_infos)

def _parse_iwi(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < IWI_HEADER_SIZE_COD4:
        raise CubemapIwiError('error.formats.iwi_short')

    # Read version byte first to decide header format
    version = data[3]

    if version == IWI_VERSION_COD4:
        header_size = IWI_HEADER_SIZE_COD4
        # COD4 V6 header: <3sBBBhhh4i  (28 bytes)
        # +00: IWi(3B) + ver(1B) + fmt(1B) + unk(1B) + w(2B) + h(2B) + d(2B) + size0-3(16B)
        magic, _, iwi_format, unk_byte, width, height, depth, \
            s0, s1, s2, s3 = struct.unpack(
            "<3sBBBhhh4i", data[:header_size]
        )
        # For COD4 V6 there are no flags (replaced by format + unknown byte)
        flags_val = unk_byte  # store unknown byte as "flags" for reference
    elif version == IWI_VERSION_MW2:
        if len(data) < IWI_HEADER_SIZE_MW2:
            raise CubemapIwiError('error.formats.iwi_v8_short')
        header_size = IWI_HEADER_SIZE_MW2
        magic, _, flags_val, iwi_format, width, height, depth, \
            s0, s1, s2, s3 = struct.unpack(
            "<3sBiBxhhh4i", data[:header_size]
        )
        flags_val = flags_val  # actual flags int
    else:
        raise CubemapIwiError('error.formats.iwi_version', version=version)

    if magic != b"IWi":
        raise CubemapIwiError('error.formats.iwi_magic')

    if width <= 0 or height <= 0:
        raise CubemapIwiError('error.formats.iwi_dimensions', width=width, height=height)
    if width != height:
        raise CubemapIwiError('error.formats.iwi_square', width=width, height=height)
    if depth != 1:
        raise CubemapIwiError('error.formats.iwi_depth', depth=depth)

    if iwi_format == IWI_FORMAT_RGB24:
        cube = bool(flags_val & 4) if version == IWI_VERSION_COD4 else (flags_val & 0x30000) == 0x10000
        if not cube or not flags_val & 2:
            raise CubemapIwiError('error.rgb24_flags')
        fourcc, format_name = b'RGB24', 'RGB24'
        face_payload_size = width * height * 3
    else:
        fourcc, format_name = _fourcc_from_iwi_format(iwi_format)
        face_payload_size = expected_face_payload_size(width, height, fourcc)
    payload = data[header_size:]
    expected_payload_size = face_payload_size * 6

    if len(payload) != expected_payload_size:
        raise CubemapIwiError('error.formats.iwi_payload', actual=len(payload), expected=expected_payload_size)

    total_file_size = len(data)
    stored_sizes = (s0, s1, s2, s3)
    if any(size != total_file_size for size in stored_sizes[:3]):
        raise CubemapIwiError('error.formats.iwi_sizes')

    faces = []
    for index, suffix in enumerate(FACE_ORDER):
        start = index * face_payload_size
        end = start + face_payload_size
        faces.append(
            {
                "suffix": suffix,
                "payload": payload[start:end],
                "payload_size": face_payload_size,
            }
        )

    return {
        "path": path,
        "width": width,
        "height": height,
        "depth": depth,
        "flags": flags_val,
        "format_name": format_name,
        "fourcc": fourcc,
        "iwi_format": iwi_format,
        "face_payload_size": face_payload_size,
        "faces": faces,
        "total_file_size": total_file_size,
        "iwi_version": version,
    }

def build_dds_header(width: int, height: int, fourcc: bytes, payload_size: int) -> bytes:
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE
    parts = [
        struct.pack("<I", DDS_HEADER_SIZE),
        struct.pack("<I", flags),
        struct.pack("<I", height),
        struct.pack("<I", width),
        struct.pack("<I", payload_size),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        b"\x00" * 44,
        struct.pack("<I", DDS_PIXELFORMAT_SIZE),
        struct.pack("<I", DDS_FOURCC),
        fourcc,
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", DDSCAPS_TEXTURE),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
        struct.pack("<I", 0),
    ]
    header = DDS_MAGIC + b"".join(parts)
    if len(header) != 128:
        raise CubemapIwiError('error.formats.dds_header_size', actual=len(header))
    return header

def build_dds_file(width: int, height: int, fourcc: bytes, payload: bytes) -> bytes:
    return build_dds_header(width, height, fourcc, len(payload)) + payload


def parse_dds(path: Path) -> CompressedFace:
    info = _parse_dds(path)
    return CompressedFace(info["width"], info["fourcc"], info["payload"])


def parse_iwi(path: Path) -> Cubemap | RawCubemap:
    info = _parse_iwi(path)
    if info['fourcc'] == b'RGB24':
        size = info['width']
        faces = tuple(PixelFace(np.frombuffer(face['payload'], dtype=np.uint8)
                                .reshape(size, size, 3)[..., ::-1].copy())
                      for face in info['faces'])
        return RawCubemap(faces, info['iwi_version'], info['flags'])
    faces = tuple(CompressedFace(info["width"], info["fourcc"], f["payload"]) for f in info["faces"])
    return Cubemap(faces, info["iwi_version"], info["flags"])


def dds_bytes(face: CompressedFace) -> bytes:
    return build_dds_file(face.size, face.size, face.fourcc, face.payload)


def iwi_bytes(faces: tuple[CompressedFace, ...], game: Game) -> bytes:
    Cubemap(tuple(faces), game.iwi_version, 0)
    infos = [dict(width=f.size, height=f.size, fourcc=f.fourcc, payload=f.payload,
                  payload_size=len(f.payload)) for f in faces]
    return _build_iwi(infos, game.iwi_version)


def rgb24_header(size: int, game: Game) -> bytes:
    if not 1 <= size <= 0x7FFF:
        raise CubemapIwiError('error.rgb24_size', size=size)
    header_size = IWI_HEADER_SIZE_COD4 if game.iwi_version == IWI_VERSION_COD4 else IWI_HEADER_SIZE_MW2
    total = header_size + 18 * size * size
    if total > 0x7FFFFFFF:
        raise CubemapIwiError('error.rgb24_length', size=size, total=total)
    if game.iwi_version == IWI_VERSION_COD4:
        total = IWI_HEADER_SIZE_COD4 + 18 * size * size
        return struct.pack('<3sBBBHHH4I', b'IWi', IWI_VERSION_COD4, IWI_FORMAT_RGB24,
                           0xC6, size, size, 1, *([total] * 4))
    total = IWI_HEADER_SIZE_MW2 + 18 * size * size
    return struct.pack('<3sBIBxHHH4I', b'IWi', IWI_VERSION_MW2, IWI_FLAGS_RGB24_V8,
                       IWI_FORMAT_RGB24, size, size, 1, *([total] * 4))
