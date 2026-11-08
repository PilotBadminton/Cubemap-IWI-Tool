GUTTER_ATLAS_FACE_CELLS = {
    "up": (1, 0),
    "lf": (0, 1),
    "ft": (1, 1),
    "rt": (2, 1),
    "bk": (3, 1),
    "dn": (1, 2),
}

CUBE_SEAMS = [
    ("rt", "left", "ft", "right", False),
    ("rt", "right", "bk", "left", False),
    ("rt", "top", "up", "right", True),
    ("rt", "bottom", "dn", "right", False),
    ("lf", "left", "bk", "right", False),
    ("lf", "right", "ft", "left", False),
    ("lf", "top", "up", "left", False),
    ("lf", "bottom", "dn", "left", True),
    ("up", "top", "bk", "top", True),
    ("up", "bottom", "ft", "top", False),
    ("dn", "top", "ft", "bottom", False),
    ("dn", "bottom", "bk", "bottom", True),
]

# Outward normal, image-right and image-down axes in cube texture coordinates.
# OpenGL's cube targets use these axes when rows are uploaded top first.
CUBE_AXES = {
    "rt": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "lf": ((-1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "up": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "dn": ((0, -1, 0), (1, 0, 0), (0, 0, -1)),
    "ft": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "bk": ((0, 0, -1), (-1, 0, 0), (0, -1, 0)),
}
