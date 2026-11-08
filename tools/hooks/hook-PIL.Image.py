"""The product reads and writes PNG; other image plugins are not collected."""
from pathlib import Path
from PyInstaller.utils.hooks import get_package_paths

_, package_dir = get_package_paths("PIL")
hiddenimports = ["PIL.PngImagePlugin"]
excludedimports = [
    "PIL." + path.stem
    for path in Path(package_dir).glob("*ImagePlugin.py")
    if path.stem != "PngImagePlugin"
] + ["PIL.ImageQt", "PIL.ImageTk", "PIL.ImageCms"]
