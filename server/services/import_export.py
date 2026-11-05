"""Excel içe/dışa aktarma (openpyxl). (Sahibi: D — P4/P6)

export_results_xlsx(): sınav sonuçlarını üç sayfalı bir .xlsx dosyasına yazar:
  1. "Özet"         — katılım, ortalama, medyan, en yüksek/düşük, standart sapma
  2. "Öğrenciler"   — öğrenci bazlı puan listesi
  3. "Soru Analizi" — soru bazlı başarı oranları ve test sorularında şık dağılımı
Veriler results.py'den alınır; bu dosya sadece biçimlendirme ile ilgilenir.
"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from server.services import results
from server.services.question_bank import TYPE_LABELS
from server.services.results import STATUS_LABELS, ExamSummary, QuestionStat, StudentResultRow

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2563EB")
TITLE_FONT = Font(bold=True, size=14)
LABEL_FONT = Font(bold=True)
CORRECT_FILL = PatternFill("solid", fgColor="DCFCE7")   # doğru şık
MUTED_FONT = Font(color="6B7280")                        # sınava girmeyenler

DATE_FORMAT = "dd.mm.yyyy hh:mm"
POINTS_FORMAT = "0.##"
PERCENT_FORMAT = "0%"
MAX_TEXT_WIDTH = 60  # uzun soru metinleri sütunu aşırı genişletmesin


def export_results_xlsx(exam_id: int, path: Path | str) -> None:
    """Sınav sonuçlarını Excel dosyasına yazar. Dosya açıksa/yazılamıyorsa OSError fırlar."""
    summary = results.exam_summary(exam_id)
    workbook = Workbook()
    _write_summary(workbook.active, summary)
    _write_students(workbook.create_sheet("Öğrenciler"), results.student_results(exam_id))
    _write_questions(workbook.create_sheet("Soru Analizi"), results.question_stats(exam_id))
    workbook.save(path)


# ---------------------------------------------------------------------------
# Sayfalar
# ---------------------------------------------------------------------------

def _write_summary(sheet: Worksheet, summary: ExamSummary) -> None:
    sheet.title = "Özet"
    sheet["A1"] = summary.title
    sheet["A1"].font = TITLE_FONT
    rows: list[tuple[str, object, str | None]] = [
        ("Sınıf", summary.class_name, None),
        ("Tam puan", summary.max_score, POINTS_FORMAT),
        ("Sınıf mevcudu", summary.expected_count, None),
        ("Katılan (gönderen)", summary.participant_count, None),
        ("Puanlanan", summary.graded_count, None),
        ("Ortalama", summary.average, "0.00"),
        ("Medyan", summary.median, "0.00"),
        ("En yüksek", summary.highest, POINTS_FORMAT),
        ("En düşük", summary.lowest, POINTS_FORMAT),
        ("Standart sapma", summary.std_dev, "0.00"),
        ("Rapor tarihi", _local(datetime.now().astimezone()), DATE_FORMAT),
    ]
    for offset, (label, value, number_format) in enumerate(rows):
        row = offset + 3
        sheet.cell(row=row, column=1, value=label).font = LABEL_FONT
        cell = sheet.cell(row=row, column=2, value="—" if value is None else value)
        cell.alignment = Alignment(horizontal="left")
        if number_format and value is not None:
            cell.number_format = number_format
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 30


def _write_students(sheet: Worksheet, rows: list[StudentResultRow]) -> None:
    headers = ["Öğrenci No", "Ad Soyad", "Durum", "Puan", "Doğru", "Yanlış", "Boş",
               "Gönderim Saati", "Otomatik Gönderildi"]
    _write_header(sheet, headers)
    for row in rows:
        sheet.append([
            row.student_no,
            row.full_name,
            STATUS_LABELS[row.status],
            row.score,
            row.correct if row.submission_id else None,
            row.wrong if row.submission_id else None,
            row.blank if row.submission_id else None,
            _local(row.submitted_at),
            ("Evet" if row.auto_submitted else "Hayır") if row.submitted_at else None,
        ])
        if row.status == "absent":
            for cell in sheet[sheet.max_row]:
                cell.font = MUTED_FONT
    _format_column(sheet, 4, POINTS_FORMAT)
    _format_column(sheet, 8, DATE_FORMAT)
    _finish_table(sheet)


def _write_questions(sheet: Worksheet, stats: list[QuestionStat]) -> None:
    headers = ["No", "Tür", "Soru", "Puan", "Doğru", "Yanlış", "Boş",
               "Doğru Oranı", "Ort. Puan Oranı"]
    _write_header(sheet, headers)
    for stat in stats:
        sheet.append([
            stat.order, TYPE_LABELS.get(stat.question_type, stat.question_type), stat.text,
            stat.max_points, stat.correct, stat.wrong, stat.blank,
            stat.correct_rate, stat.average_rate,
        ])
    _format_column(sheet, 4, POINTS_FORMAT)
    _format_column(sheet, 8, PERCENT_FORMAT)
    _format_column(sheet, 9, PERCENT_FORMAT)
    _finish_table(sheet)
    _write_option_table(sheet, stats)


def _write_option_table(sheet: Worksheet, stats: list[QuestionStat]) -> None:
    """Soru tablosunun altına test sorularının şık dağılımını yazar. Doğru şık yeşil."""
    mcqs = [s for s in stats if s.options]
    if not mcqs:
        return
    row = sheet.max_row + 3
    sheet.cell(row=row, column=1, value="Şık Dağılımı (test soruları)").font = TITLE_FONT
    row += 1
    for col, title in enumerate(["Soru No", "Şık", "Şık Metni", "Seçilme", "Doğru Şık"], start=1):
        _style_header(sheet.cell(row=row, column=col, value=title))
    for stat in mcqs:
        for option in stat.options:
            row += 1
            values = [stat.order, option.letter, option.text, option.count,
                      "✓" if option.is_correct else ""]
            for col, value in enumerate(values, start=1):
                cell = sheet.cell(row=row, column=col, value=value)
                if option.is_correct:
                    cell.fill = CORRECT_FILL


# ---------------------------------------------------------------------------
# Biçimlendirme yardımcıları
# ---------------------------------------------------------------------------

def _write_header(sheet: Worksheet, headers: list[str]) -> None:
    sheet.append(headers)
    for cell in sheet[1]:
        _style_header(cell)


def _style_header(cell) -> None:
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _format_column(sheet: Worksheet, column: int, number_format: str) -> None:
    for (cell,) in sheet.iter_rows(min_row=2, min_col=column, max_col=column):
        cell.number_format = number_format


def _finish_table(sheet: Worksheet) -> None:
    """Başlığı dondurur, filtre ekler, sütun genişliklerini içeriğe göre ayarlar."""
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, column in enumerate(sheet.iter_cols(), start=1):
        longest = max((len(_display(c.value)) for c in column), default=0)
        sheet.column_dimensions[get_column_letter(index)].width = min(longest + 3, MAX_TEXT_WIDTH)


def _display(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return "00.00.0000 00:00"
    return str(value)


def _local(moment: datetime | None) -> datetime | None:
    """UTC → yerel saat. Excel saat dilimi bilmediği için tzinfo kaldırılır."""
    if moment is None:
        return None
    return moment.astimezone().replace(tzinfo=None)
