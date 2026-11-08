"""Keep Qt's Windows 11 control style without other style plugins."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if Path(entry[0]).name == 'qmodernwindowsstyle.dll']
