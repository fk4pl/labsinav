# PyInstaller tarifi: öğrenci uygulaması (Windows, tek klasör, konsolsuz).
# Derleme (repo kökünde):  pyinstaller build_tools/LabSinav-Ogrenci.spec
# Çıktı: dist/LabSinav-Ogrenci/LabSinav-Ogrenci.exe  (klasörün tamamı birlikte dağıtılır)
from pathlib import Path

ROOT = Path(SPECPATH).parent  # SPECPATH: bu dosyanın bulunduğu klasör (build_tools)

a = Analysis(
    [str(ROOT / "build_tools" / "run_student.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "shared" / "assets"), "shared/assets"),
        (str(ROOT / "student_app" / "demo_exam.json"), "student_app"),  # --demo modu
    ],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabSinav-Ogrenci",
    console=False,  # siyah konsol penceresi açılmasın
    icon=str(ROOT / "build_tools" / "icons" / "ogrenci.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="LabSinav-Ogrenci")
