"""Keep upstream binding setup; the raster workbench needs no software OpenGL."""
from pathlib import Path
import runpy
import PyInstaller

upstream = runpy.run_path(str(Path(PyInstaller.__file__).parent / "hooks" / "hook-PySide6.py"))
hiddenimports = upstream["hiddenimports"]
binaries = [entry for entry in upstream["binaries"] if Path(entry[0]).name != "opengl32sw.dll"]
