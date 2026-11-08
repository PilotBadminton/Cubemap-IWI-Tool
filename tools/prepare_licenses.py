"""Collect notices for the installed versions used to build the portable app."""
import shutil
import os
import sys
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sdk_dir = os.environ.get('NVTT_SDK_DIR')
    if not sdk_dir:
        raise SystemExit('Set NVTT_SDK_DIR to the NVTT SDK directory before collecting licenses.')
    sdk = Path(sdk_dir)
    output = ROOT / "licenses"
    output.mkdir(exist_ok=True)
    shutil.copyfile(sdk / "LICENSE.TXT", output / "NVIDIA-NVTT.txt")
    shutil.copyfile(sdk / "license_information.txt", output / "NVIDIA-third-party.txt")
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", output / "Python.txt")
    for name in ("numpy", "Pillow", "PyInstaller"):
        dist = distribution(name)
        sections = []
        for file in dist.files:
            if "dist-info/licenses/" in str(file).replace("\\", "/"):
                path = Path(dist.locate_file(file))
                sections.append(f"{file}\n\n" + path.read_text(encoding="utf-8"))
        (output / f"{name}.txt").write_text("\n\n".join(sections), encoding="utf-8")


if __name__ == "__main__":
    main()
