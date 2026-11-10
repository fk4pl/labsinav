"""Şablon + md bölümleri + PNG şekiller → docs/rapor/LabSinav_Rapor.docx (python-docx).

Kullanım: python docs/rapor/build_rapor.py   (şablon değişmez; çıktı her seferinde baştan üretilir)
"""
import copy
import re
import shutil
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parents[2]  # docs/rapor/build_rapor.py → proje kökü
RAPOR = ROOT / "docs/rapor"
MD = RAPOR / "bolumler"
FIG = ROOT / "docs/sekiller"
TEMPLATE = RAPOR / "LabSinav_Rapor_Sablon.docx"
OUT = RAPOR / "LabSinav_Rapor.docx"
GRAY = "7F7F7F"
CODE_FONT = "Courier New"

# ---------------------------------------------------------------- md okuma

def md_sections(path: Path, level: str = "## ") -> dict[str, list[str]]:
    """Başlık → satırlar. Bölüm bir sonraki aynı düzey başlıkta veya '---' satırında biter."""
    out: dict[str, list[str]] = {}
    cur = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(level):
            cur = line[len(level):].strip()
            out[cur] = []
        elif line.strip() == "---":
            cur = None
        elif cur is not None:
            out[cur].append(line)
    return out


def md_blocks(lines: list[str]) -> list[tuple]:
    """Satırları bloklara ayırır: ('p', metin) ('bullet', metin) ('code', satırlar) ('table', satırlar)."""
    blocks: list[tuple] = []
    buf: list[str] = []

    def flush():
        if buf:
            blocks.append(("p", " ".join(s.strip() for s in buf)))
            buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            code = []
            i += 1
            while not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", code))
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        elif s.startswith("- "):
            flush()
            blocks.append(("bullet", s[2:]))
        elif s.startswith(">") or s.startswith("**Tablo") or s.startswith("#"):
            flush()  # ölçüm notu, md tablo başlığı ve alt başlıklar rapora girmez
        elif not s:
            flush()
        else:
            buf.append(line)
        i += 1
    flush()
    return blocks


# ---------------------------------------------------------------- Word yardımcıları

def set_font(run, name: str) -> None:
    rpr = run._r.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), name)


def add_inline(par: Paragraph, text: str, size: float | None = None,
               code_size: float | None = None, bold: bool = False) -> None:
    """`kod` → Courier New, **kalın** → kalın; işaretler metne girmez."""
    for tok in re.split(r"(\*\*.+?\*\*|`[^`]+`)", text):
        if not tok:
            continue
        if tok.startswith("**"):
            run = par.add_run(tok[2:-2])
            run.bold = True
        elif tok.startswith("`"):
            run = par.add_run(tok[1:-1])
            set_font(run, CODE_FONT)
            if code_size or size:
                run.font.size = Pt(code_size or size)
            if bold:
                run.bold = True
            continue
        else:
            run = par.add_run(tok)
            if bold:
                run.bold = True
        set_font(run, "Times New Roman")
        if size:
            run.font.size = Pt(size)


def new_par(doc) -> Paragraph:
    return Paragraph(OxmlElement("w:p"), doc._body)


def body_par(doc, text: str) -> Paragraph:
    p = new_par(doc)
    pf = p.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.first_line_indent = Cm(0.35)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    add_inline(p, text, code_size=9)
    return p


def bullet_par(doc, text: str) -> Paragraph:
    p = new_par(doc)
    p.style = doc.styles["List Paragraph"]
    ppr = p._p.get_or_add_pPr()
    num = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl"); ilvl.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId"); nid.set(qn("w:val"), "2")
    num.append(ilvl); num.append(nid)
    ppr.append(num)
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(1)
    add_inline(p, text, code_size=9)
    return p


def code_lines_pars(doc, lines: list[str], size: float) -> list[Paragraph]:
    pars = []
    for k, line in enumerate(lines):
        p = new_par(doc)
        pf = p.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.space_before = Pt(0)
        pf.space_after = Pt(6) if k == len(lines) - 1 else Pt(0)
        pf.line_spacing = 1.0
        pf.keep_together = True
        pf.keep_with_next = k < len(lines) - 1
        run = p.add_run(line)
        set_font(run, CODE_FONT)
        run.font.size = Pt(size)
        pars.append(p)
    return pars


def is_gray_note(el) -> bool:
    """[KİŞİ …] notu veya gri madde (kenarlıklı yer tutucular hariç)."""
    if el.tag != qn("w:p") or el.find(".//" + qn("w:pBdr")) is not None:
        return False
    runs = [r for r in el.iter(qn("w:r")) if "".join(t.text or "" for t in r.iter(qn("w:t"))).strip()]
    if not runs:
        return False
    return all((c := r.find(".//" + qn("w:color"))) is not None and c.get(qn("w:val")).upper() == GRAY
               for r in runs)


def par_text(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def find_par(doc, pred) -> Paragraph:
    hits = [p for p in doc.paragraphs if pred(p)]
    assert len(hits) == 1, f"bulunamadı/çok: {len(hits)}"
    return hits[0]


def heading(doc, text: str) -> Paragraph:
    return find_par(doc, lambda p: p.style.name.startswith("Heading") and p.text.strip() == text)


def clear_notes_after(el):
    """el'den sonraki gri notları siler; içerik eklenecek çapa elemanı döner."""
    nxt = el.getnext()
    while nxt is not None and is_gray_note(nxt):
        gone, nxt = nxt, nxt.getnext()
        gone.getparent().remove(gone)
    return nxt


def insert_before(anchor, pars: list[Paragraph]) -> None:
    for p in pars:
        anchor.addprevious(p._p)


def blocks_to_pars(doc, blocks) -> list[Paragraph]:
    pars = []
    for kind, val in blocks:
        if kind == "p":
            pars.append(body_par(doc, val))
        elif kind == "bullet":
            pars.append(bullet_par(doc, val))
        elif kind == "code":  # II-B JSON örneği: sütuna sığması için uzun satır bölünür
            lines = []
            for line in val:
                if '"selected_option_id"' in line and len(line) > 48:
                    a, b = line.split(', "selected_option_id"')
                    lines += [a + ",", '  "selected_option_id"' + b]
                else:
                    lines.append(line)
            cp = code_lines_pars(doc, lines, 8)
            cp[0].paragraph_format.space_before = Pt(3)
            pars += cp
    return pars


# ---------------------------------------------------------------- bölüm sonları ve şekiller

def section_props(doc, cols: int):
    final = doc.element.body.find(qn("w:sectPr"))
    sp = copy.deepcopy(final)
    c = sp.find(qn("w:cols"))
    if cols == 1:
        sp.remove(c)
        new = OxmlElement("w:cols"); new.set(qn("w:space"), "708")
        sp.find(qn("w:docGrid")).addprevious(new)
    return sp


def attach_sectpr(par_el, sp) -> None:
    ppr = par_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        par_el.insert(0, ppr)
    ppr.append(sp)  # sectPr, pPr'nin son çocuğu olmalı


def picture_par(doc, png: Path, width_cm: float) -> Paragraph:
    p = new_par(doc)
    pf = p.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.space_before = Pt(6)
    pf.space_after = Pt(3)
    pf.keep_with_next = True
    p.add_run().add_picture(str(png), width=Cm(width_cm))
    return p


def place_figure(doc, n: int, png: str, width_cm: float, full_width: bool, intro: str | None = None):
    ph = find_par(doc, lambda p: p.text.startswith(f"Şekil {n} buraya"))._p
    caption = ph.getnext()
    assert par_text(caption).startswith(f"Şekil {n}."), par_text(caption)
    if intro:
        insert_before(ph, [body_par(doc, intro)])
    pic = picture_par(doc, FIG / png, width_cm)
    ph.addprevious(pic._p)
    prev = pic._p.getprevious()
    ph.getparent().remove(ph)
    if full_width:
        if prev.tag != qn("w:p"):
            filler = new_par(doc)._p
            pic._p.addprevious(filler)
            prev = filler
        attach_sectpr(prev, section_props(doc, 2))     # buraya kadar iki sütun
        attach_sectpr(caption, section_props(doc, 1))  # şekil + başlık tek sütun


# ---------------------------------------------------------------- algoritmalar

def algorithm_pars(doc, sec: list[str]) -> list[Paragraph]:
    sub = {}
    cur = None
    for line in sec:
        if line.startswith("### "):
            cur = line[4:].strip(); sub[cur] = []
        elif cur:
            sub[cur].append(line)
    code = next(v for k, v in md_blocks(sub["Word için düz metin"]) if k == "code")
    title_lines = []
    while not code[0].startswith(("GİRDİ", "FONKSİYON")):
        title_lines.append(code.pop(0).strip())
    explanation = [v for k, v in md_blocks(sub["Açıklama (rapor metni)"]) if k == "p"]

    t = new_par(doc)
    t.paragraph_format.space_before = Pt(6)
    t.paragraph_format.space_after = Pt(2)
    t.paragraph_format.keep_with_next = True
    add_inline(t, " ".join(title_lines), size=9, bold=True)
    return [t] + code_lines_pars(doc, code, 9) + [body_par(doc, e) for e in explanation]


def place_algorithm(doc, n: int, sec: list[str]) -> None:
    ph = find_par(doc, lambda p: p.text.startswith(f"Algoritma {n} buraya"))._p
    insert_before(ph, algorithm_pars(doc, sec))
    ph.getparent().remove(ph)


# ---------------------------------------------------------------- tablolar

def set_cell(cell, text: str) -> None:
    p = cell.paragraphs[0]
    for r in list(p._p.iter(qn("w:r"))):
        r.getparent().remove(r)
    add_inline(p, text, size=8)


def fill_table(table, md_rows: list[list[str]]) -> None:
    """md'deki veri satırlarıyla doldurur; satır sayısı farklıysa şablon satırları kopyalanır."""
    tbl = table._tbl
    rows = table.rows
    middle, last = rows[1]._tr, rows[-1]._tr
    data = md_rows[1:]
    new = [copy.deepcopy(last if i == len(data) - 1 else middle) for i in range(len(data))]
    for r in rows[1:]:
        tbl.remove(r._tr)
    for tr in new:
        tbl.append(tr)
    for row, values in zip(table.rows[1:], data):
        for cell, val in zip(row.cells, values):
            set_cell(cell, val)


# ---------------------------------------------------------------- ana akış

def main() -> None:
    shutil.copy(TEMPLATE, OUT)
    doc = docx.Document(str(OUT))
    s01 = md_sections(MD / "01_ozet_giris_sonuc.md")
    s02 = md_sections(MD / "02_mimari_ag_vt.md")
    s04 = md_sections(MD / "04_sure_puanlama.md")
    s05 = md_sections(MD / "05_pseudocode.md")
    s07 = md_sections(MD / "07_dayaniklilik_test.md")

    # Özet + Anahtar Kelimeler
    ozet_blocks = md_blocks(s01["Özet"])
    ozet_p = find_par(doc, lambda p: p.text.startswith("Özet—"))
    clear_notes_after(ozet_p._p)
    add_inline(ozet_p, ozet_blocks[0][1], size=9, bold=True)
    kw_text = s01["Özet"][[i for i, l in enumerate(s01["Özet"]) if "Anahtar Kelimeler" in l][0]]
    kw_text = kw_text.split("**", 2)[2].strip()
    kw_p = find_par(doc, lambda p: p.text.startswith("Anahtar Kelimeler"))
    kw_run = kw_p.runs[1]
    kw_run.text = kw_text
    color = kw_run._r.find(".//" + qn("w:color"))
    color.getparent().remove(color)
    for r in kw_p.runs[2:]:
        r._r.getparent().remove(r._r)

    # Düz metin bölümleri
    plain = {
        "I. Giriş": s01["I. Giriş"],
        "A. Sistem Mimarisi": s02["A. Sistem Mimarisi"],
        "B. Ağ İletişimi ve Protokol": s02["B. Ağ İletişimi ve Protokol"],
        "C. Veri Tabanı Tasarımı": s02["C. Veri Tabanı Tasarımı"],
        "D. Sınav Yürütme ve Süre Yönetimi": s04["D. Sınav Yürütme ve Süre Yönetimi"],
        "E. Otomatik Puanlama": s04["E. Otomatik Puanlama"],
        "F. Dayanıklılık ve Sınav Güvenliği": s07["F. Dayanıklılık ve Sınav Güvenliği"],
        "IV. Test ve Değerlendirme": s07["IV. Test ve Değerlendirme"],
        "V. Sonuç": s01["V. Sonuç"],
    }
    md_tables = {}
    for title, lines in plain.items():
        blocks = md_blocks(lines)
        md_tables.update({title: v for k, v in blocks if k == "table"})
        anchor = clear_notes_after(heading(doc, title)._p)
        insert_before(anchor, blocks_to_pars(doc, blocks))
    clear_notes_after(heading(doc, "III. Diyagramlar")._p)

    # Algoritmalar
    place_algorithm(doc, 1, s05["Algoritma 1. Süresi dolan sınavların otomatik gönderimi"])
    place_algorithm(doc, 2, s05["Algoritma 2. Klasik soru puanlama"])

    # Şekiller
    place_figure(doc, 1, "sekil1_mimari.png", 16.0, True)
    place_figure(doc, 2, "sekil2_akis.png", 7.0, False,
                 "Şekil 2'de eğitmenin sınavı oluşturmasından sonuçların listelenmesine kadar "
                 "sınav sürecinin adımları gösterilmiştir.")
    place_figure(doc, 3, "sekil3_sequence.png", 14.5, True,
                 "Şekil 3'te öğrenci uygulamasının sunucuyu bulmasından sınavın bitmesine kadar "
                 "öğrenci uygulaması, sunucu ve veri tabanı arasındaki mesajlaşma sırası verilmiştir.")
    place_figure(doc, 4, "class.png", 18.0, True,
                 "Şekil 4'te veri tabanı tablolarına karşılık gelen sınıflar ve aralarındaki "
                 "ilişkiler gösterilmiştir.")

    # Tablolar
    t1, t2 = doc.tables
    fill_table(t1, md_tables["B. Ağ İletişimi ve Protokol"])
    fill_table(t2, md_tables["IV. Test ve Değerlendirme"])
    note = new_par(doc)
    note.paragraph_format.space_before = Pt(2)
    add_inline(note, "Yanıt süresi, `save_answer` isteğinden `save_ok` cevabına kadar geçen süredir.", size=8)
    t2._tbl.addnext(note._p)

    # Şablon metinleri: "eş zamanlı" yazımı ve IEEE ilk atıf sırası ([3] bcrypt, [4] WAL)
    cap = find_par(doc, lambda p: p.text.startswith("Tablo II."))
    for r in cap.runs:
        r.text = r.text.replace("eşzamanlı", "eş zamanlı")
    ref3 = find_par(doc, lambda p: p.text.startswith("[3] SQLite"))
    ref4 = find_par(doc, lambda p: p.text.startswith("[4] N. Provos"))
    ref3._p.addprevious(ref4._p)
    ref4.runs[0].text = ref4.runs[0].text.replace("[4]", "[3]", 1)
    ref3.runs[0].text = ref3.runs[0].text.replace("[3]", "[4]", 1)

    doc.save(str(OUT))
    print("kaydedildi:", OUT)


if __name__ == "__main__":
    main()
