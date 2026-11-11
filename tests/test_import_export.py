"""Excel dışa aktarma testi: dosya openpyxl ile geri okunup kontrol edilir."""

from pathlib import Path

from openpyxl import load_workbook

from server.services import grading
from server.services.import_export import export_results_xlsx
from tests.result_helpers import create_small_exam, take_exam


def test_export_results_xlsx(seeded_db, tmp_path: Path) -> None:
    exam = create_small_exam()
    sid = take_exam(exam, "260101001", option_id=exam.right_option, text="istanbul")
    grading.grade_submission(sid)

    path = tmp_path / "sonuclar.xlsx"
    export_results_xlsx(exam.exam_id, path)

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["Özet", "Öğrenciler", "Soru Analizi"]

    summary = workbook["Özet"]
    assert summary["A1"].value == "Puanlama Testi"
    values = {summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
              for r in range(3, summary.max_row + 1)}
    assert values["Katılan (gönderen)"] == 1
    assert values["Ortalama"] == 15

    students = workbook["Öğrenciler"]
    assert students["A1"].value == "Öğrenci No"
    assert students.freeze_panes == "A2"
    assert students["A2"].value == "260101001" and students["D2"].value == 15
    assert students.max_row == 1 + 15  # başlık + sınıftaki 15 öğrenci

    questions = workbook["Soru Analizi"]
    assert questions["H2"].value == 1.0 and questions["H2"].number_format == "0%"
    texts = [c.value for c in questions["A"]]
    assert "Şık Dağılımı (test soruları)" in texts


# ---------------------------------------------------------------------------
# Öğrenci listesi içe aktarma
# ---------------------------------------------------------------------------

import pytest  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from server.services import students  # noqa: E402
from server.services.auth import authenticate  # noqa: E402
from server.services.import_export import (  # noqa: E402
    ImportFileError,
    apply_student_import,
    preview_student_import,
    write_student_template,
)


def make_xlsx(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    workbook.save(path)
    return path


def class_a_id() -> int:
    return next(c.id for c in students.list_classes() if c.name == "1. Öğretim A")


def test_import_preview_counts_and_reasons(seeded_db, tmp_path: Path) -> None:
    path = make_xlsx(tmp_path / "liste.xlsx", [
        ["Öğrenci No", "Ad Soyad"],
        [260202001, "Ali Veli"],            # 2: eklenecek (Excel sayı olarak tutar)
        [None, None],                        # 3: boş satır → sessizce atlanır
        ["260202002", "  Ayşe   Yılmaz "],   # 4: eklenecek, boşluklar temizlenir
        ["260202001", "Tekrar Eden"],        # 5: dosyada tekrar
        ["26A", "Harfli No"],                # 6: hatalı no
        ["260202003", ""],                   # 7: ad boş
        ["", "Numarasız"],                   # 8: no boş
        ["260101001", "Zaten Var"],          # 9: veri tabanında var
    ])
    preview = preview_student_import(path)
    assert [(r.row_number, r.student_no, r.full_name) for r in preview.to_add] == [
        (2, "260202001", "Ali Veli"), (4, "260202002", "Ayşe Yılmaz"),
    ]
    assert [(e.row_number, e.place) for e in preview.existing] == [(9, "1. Öğretim A")]
    reasons = {e.row_number: e.reason for e in preview.errors}
    assert set(reasons) == {5, 6, 7, 8}
    assert "satır 2" in reasons[5]
    assert "rakam" in reasons[6]
    assert "Ad soyad boş" in reasons[7]
    assert "Öğrenci no boş" in reasons[8]


@pytest.mark.parametrize("header", [
    ["Numara", "Adı Soyadı"],
    ["NO", "AD SOYAD"],
    ["Öğrenci No.", "Adı ve Soyadı"],
    ["Sıra", "Öğrenci Numarası", "İsim Soyisim"],
])
def test_import_flexible_headers(seeded_db, tmp_path: Path, header: list[str]) -> None:
    padding = [""] * (len(header) - 2)
    path = make_xlsx(tmp_path / "liste.xlsx", [header, padding + ["260202001", "Ali Veli"]])
    preview = preview_student_import(path)
    assert [(r.student_no, r.full_name) for r in preview.to_add] == [("260202001", "Ali Veli")]


def test_import_separate_name_columns_after_title_rows(seeded_db, tmp_path: Path) -> None:
    """Okul listelerinde üstte başlık satırları ve ayrı Adı/Soyadı sütunları olabilir."""
    path = make_xlsx(tmp_path / "liste.xlsx", [
        ["XYZ ÜNİVERSİTESİ"],
        ["Programlama Lab. Sınıf Listesi"],
        [],
        ["S.No", "Öğrenci No", "Adı", "Soyadı"],
        [1, "260202001", "Ali", "Veli"],
    ])
    preview = preview_student_import(path)
    assert [(r.row_number, r.full_name) for r in preview.to_add] == [(5, "Ali Veli")]


def test_import_csv_semicolon_cp1254(seeded_db, tmp_path: Path) -> None:
    path = tmp_path / "liste.csv"
    path.write_bytes("Öğrenci No;Ad Soyad\n260202001;Çağrı Işık\n".encode("cp1254"))
    preview = preview_student_import(path)
    assert [(r.student_no, r.full_name) for r in preview.to_add] == [("260202001", "Çağrı Işık")]


def test_import_without_header_or_unsupported_file(seeded_db, tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match="Başlık satırı"):
        preview_student_import(make_xlsx(tmp_path / "a.xlsx", [["x", "y"], ["1", "2"]]))
    with pytest.raises(ImportFileError, match=".xls"):
        preview_student_import(tmp_path / "eski.xls")
    bad = tmp_path / "bozuk.xlsx"
    bad.write_text("excel değil", encoding="utf-8")
    with pytest.raises(ImportFileError, match="okunamadı"):
        preview_student_import(bad)


def test_apply_import_adds_students_who_can_log_in(seeded_db, tmp_path: Path) -> None:
    path = make_xlsx(tmp_path / "liste.xlsx", [["Öğrenci No", "Ad Soyad"],
                                                ["260202001", "Ali Veli"], ["260202002", "Ayşe Kaya"]])
    preview = preview_student_import(path)
    cid = class_a_id()
    assert apply_student_import(preview.to_add, cid) == 2
    assert authenticate("260202001", "260202001") is not None
    assert len(students.list_students(cid)) == 17
    assert apply_student_import(preview.to_add, cid) == 0  # tekrar çalıştırılırsa eklenmez


def test_student_template_round_trip(seeded_db, tmp_path: Path) -> None:
    path = tmp_path / "sablon.xlsx"
    write_student_template(path)
    sheet = load_workbook(path).active
    assert [sheet["A1"].value, sheet["B1"].value] == ["Öğrenci No", "Ad Soyad"]
    assert sheet["A2"].number_format == "@"  # baştaki 0'lar kaybolmasın
    preview = preview_student_import(path)  # boş şablon hatasız okunur
    assert not preview.to_add and not preview.errors
