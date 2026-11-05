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
