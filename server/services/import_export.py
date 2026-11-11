"""Excel içe/dışa aktarma (openpyxl). (Sahibi: D)

export_results_xlsx(): sınav sonuçlarını üç sayfalı bir .xlsx dosyasına yazar:
  1. "Özet"         — katılım, ortalama, medyan, en yüksek/düşük, standart sapma
  2. "Öğrenciler"   — öğrenci bazlı puan listesi
  3. "Soru Analizi" — soru bazlı başarı oranları ve test sorularında şık dağılımı
Veriler results.py'den alınır; bu dosya sadece biçimlendirme ile ilgilenir.

Öğrenci içe aktarma, iki adım:
  1. preview_student_import(dosya) — dosyayı okur, satırları doğrular; veri tabanına YAZMAZ.
     Sonuç: eklenecekler / zaten var olanlar / hatalı satırlar (nedeniyle). Arayüz bunu önizlemede gösterir.
  2. apply_student_import(eklenecekler, sınıf) — onaydan sonra öğrencileri ekler (şifre = öğrenci no).
Başlık satırı esnek tanınır ("Öğrenci No", "Numara", "No", "Adı Soyadı", ayrı "Adı" + "Soyadı" ...)
ve dosyanın ilk 10 satırında aranır (okul listelerinde üstte başlık/okul adı satırları olabilir).
write_student_template(): doğru başlıklı boş şablon.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from server.db.models import User
from server.db.session import write_session
from server.services import results, students
from server.services.auth import hash_password
from server.services.question_bank import TYPE_LABELS, turkish_lower
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



# ---------------------------------------------------------------------------
# Öğrenci listesi içe aktarma
# ---------------------------------------------------------------------------

HEADER_SEARCH_ROWS = 10
STUDENT_HEADERS = ["Öğrenci No", "Ad Soyad"]

# Başlıklar normalize edilerek karşılaştırılır: küçük harf, Türkçe harfler → ASCII, boşluk/noktalama yok.
# Ör. "Öğrenci No." → "ogrencino", "ADI SOYADI" → "adisoyadi"
NO_HEADERS = {"ogrencino", "ogrencinumarasi", "ogrencinumara", "numara", "numarasi", "no", "okulno",
              "ogrno", "ogrencinum", "sicilno", "ogrenciokulno"}
NAME_HEADERS = {"adsoyad", "adisoyadi", "adsoyadi", "adisoyad", "adivesoyadi", "advesoyad", "isimsoyisim",
                "isimsoyad", "adsoyisim", "ogrenciadisoyadi", "ogrenciadsoyad"}
FIRST_NAME_HEADERS = {"ad", "adi", "isim", "ogrenciadi"}
LAST_NAME_HEADERS = {"soyad", "soyadi", "soyisim"}

_ASCII_MAP = str.maketrans("çğıöşü", "cgiosu")


class ImportFileError(Exception):
    """Dosya hiç okunamadı / başlık bulunamadı. message: Türkçe açıklama."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class ImportRow:
    row_number: int   # dosyadaki satır numarası (Excel'de görünen)
    student_no: str
    full_name: str


@dataclass
class ExistingRow:
    row_number: int
    student_no: str
    full_name: str
    place: str        # veri tabanındaki sınıfı, ör. "1. Öğretim A"


@dataclass
class RowError:
    row_number: int
    reason: str


@dataclass
class ImportPreview:
    to_add: list[ImportRow] = field(default_factory=list)
    existing: list[ExistingRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


@dataclass
class _Columns:
    """Başlık satırında bulunan sütunların sırası (0'dan başlar)."""

    no: int
    name: int | None = None      # "Ad Soyad" tek sütun
    first: int | None = None     # ya da ayrı "Adı" ...
    last: int | None = None      # ... ve "Soyadı"


def preview_student_import(path: Path | str) -> ImportPreview:
    """Dosyayı okur ve doğrular; veri tabanına yazmaz. Okunamazsa ImportFileError."""
    rows = _read_rows(Path(path))
    header_index, columns = _find_header(rows)
    preview = ImportPreview()
    # Satır numaraları Excel'deki gibi 1'den başlar; veri, başlığın bir altından başlar.
    valid = _validate_rows(rows[header_index + 1:], header_index + 2, columns, preview.errors)
    existing = students.existing_usernames([r.student_no for r in valid])
    for row in valid:
        if row.student_no in existing:
            preview.existing.append(
                ExistingRow(row.row_number, row.student_no, row.full_name, existing[row.student_no])
            )
        else:
            preview.to_add.append(row)
    return preview


def apply_student_import(rows: list[ImportRow], class_id: int) -> int:
    """Önizlemedeki "eklenecek" satırları ekler; eklenen öğrenci sayısını döner.

    Şifre hash'leri yavaş olduğu için önce (kilitsiz) hesaplanır, sonra tek yazma işleminde eklenir.
    Önizlemeden bu yana aynı no başka yoldan eklendiyse o satır atlanır.
    """
    hashed = [(row, hash_password(row.student_no)) for row in rows]
    with write_session() as session:
        students.get_class(session, class_id)
        taken = set(session.scalars(select(User.username).where(User.username.in_([r.student_no for r in rows]))))
        added = 0
        for row, password_hash in hashed:
            if row.student_no in taken:
                continue
            session.add(User(username=row.student_no, full_name=row.full_name, password_hash=password_hash,
                             role="student", class_id=class_id))
            taken.add(row.student_no)
            added += 1
        return added


def write_student_template(path: Path | str) -> None:
    """Doğru başlıklı boş içe aktarma şablonu. No sütunu metin biçimli (baştaki 0'lar kaybolmasın)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Öğrenciler"
    _write_header(sheet, STUDENT_HEADERS)
    for row in range(2, 202):
        sheet.cell(row=row, column=1).number_format = "@"
    sheet.column_dimensions["A"].width = 16
    sheet.column_dimensions["B"].width = 36
    sheet.freeze_panes = "A2"
    workbook.save(path)


# --- Dosya okuma -------------------------------------------------------------

def _read_rows(path: Path) -> list[list[str]]:
    """Dosyadaki tüm satırları metin listesi olarak döner (satır numarası = index + 1)."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise ImportFileError("Eski .xls biçimi desteklenmiyor. Dosyayı Excel'de "
                              "\"Farklı Kaydet → Excel Çalışma Kitabı (.xlsx)\" ile kaydedip tekrar deneyin.")
    try:
        if suffix in (".xlsx", ".xlsm"):
            return _read_xlsx(path)
        if suffix in (".csv", ".txt"):
            return _read_csv(path)
    except (OSError, InvalidFileException, zipfile.BadZipFile, KeyError) as error:
        raise ImportFileError("Dosya okunamadı. Dosyanın başka bir programda açık olmadığından "
                              "ve bozuk olmadığından emin olun.") from error
    raise ImportFileError("Desteklenmeyen dosya türü. .xlsx veya .csv dosyası seçin.")


def _read_xlsx(path: Path) -> list[list[str]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return [[_cell_text(v) for v in row] for row in workbook.active.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _read_csv(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1254")  # Türkçe Windows'ta Excel'in kaydettiği CSV
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if ";" in text[:4096] else ","
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _cell_text(value: object) -> str:
    """Excel hücresini metne çevirir. Sayı olarak girilmiş no: 260101001.0 → '260101001'."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# --- Başlık ve satırlar ------------------------------------------------------

def _normalize_header(text: str) -> str:
    text = turkish_lower(text).translate(_ASCII_MAP)
    return "".join(ch for ch in text if ch.isalnum())


def _find_header(rows: list[list[str]]) -> tuple[int, _Columns]:
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns = _match_columns([_normalize_header(c) for c in row])
        if columns is not None:
            return index, columns
    raise ImportFileError("Başlık satırı bulunamadı. İlk satırlardan birinde \"Öğrenci No\" ve "
                          "\"Ad Soyad\" sütun başlıkları olmalı (örnek şablonu indirip kullanabilirsiniz).")


def _match_columns(headers: list[str]) -> _Columns | None:
    def find(names: set[str]) -> int | None:
        return next((i for i, h in enumerate(headers) if h in names), None)

    no = find(NO_HEADERS)
    if no is None:
        return None
    name = find(NAME_HEADERS)
    if name is not None:
        return _Columns(no=no, name=name)
    first, last = find(FIRST_NAME_HEADERS), find(LAST_NAME_HEADERS)
    if first is not None and last is not None:
        return _Columns(no=no, first=first, last=last)
    return None


def _validate_rows(rows: list[list[str]], first_row_number: int, columns: _Columns,
                   errors: list[RowError]) -> list[ImportRow]:
    """Geçerli satırları döner; hatalıları errors'a ekler. Tamamen boş satırlar sessizce atlanır."""
    valid: list[ImportRow] = []
    seen: dict[str, int] = {}  # no → ilk görüldüğü satır
    for row_number, row in enumerate(rows, start=first_row_number):
        student_no = students.clean_text(_get(row, columns.no))
        full_name = students.clean_text(_full_name(row, columns))
        if not student_no and not full_name:
            continue
        reason = students.check_student_no(student_no) or students.check_full_name(full_name)
        if reason is None and student_no in seen:
            reason = f"Bu öğrenci no dosyada daha önce geçiyor (satır {seen[student_no]})."
        if reason:
            errors.append(RowError(row_number, reason))
            continue
        seen[student_no] = row_number
        valid.append(ImportRow(row_number, student_no, full_name))
    return valid


def _full_name(row: list[str], columns: _Columns) -> str:
    if columns.name is not None:
        return _get(row, columns.name)
    assert columns.first is not None and columns.last is not None
    return f"{_get(row, columns.first)} {_get(row, columns.last)}"


def _get(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""
