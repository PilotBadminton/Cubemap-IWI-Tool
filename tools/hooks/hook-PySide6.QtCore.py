"""Use the upstream dependency analysis and retain the Chinese base catalog."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
datas = [entry for entry in datas if Path(entry[0]).name == "qtbase_zh_CN.qm"]
