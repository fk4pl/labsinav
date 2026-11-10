# PyInstaller tarifi: eğitmen uygulaması (Windows, tek klasör, konsolsuz).
# Derleme (repo kökünde):  pyinstaller build_tools/LabSinav-Egitmen.spec
# Çıktı: dist/LabSinav-Egitmen/LabSinav-Egitmen.exe  (klasörün tamamı birlikte dağıtılır)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # SPECPATH: bu dosyanın bulunduğu klasör (build_tools)

a = Analysis(
    [str(ROOT / "build_tools" / "run_instructor.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "shared" / "assets"), "shared/assets")],
    # websockets bazı alt modüllerini çalışma anında yükler; PyInstaller bunları göremez.
    hiddenimports=collect_submodules("websockets"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabSinav-Egitmen",
    console=False,  # siyah konsol penceresi açılmasın
    icon=str(ROOT / "build_tools" / "icons" / "egitmen.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="LabSinav-Egitmen")
