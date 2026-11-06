"""Örnek veri: python -m scripts.seed [--students N]

UYARI: Her çalıştırıldığında veri tabanındaki TÜM veriyi siler ve baştan oluşturur.

Giriş bilgileri:
    Eğitmen:   egitmen / egitmen123
    Öğrenciler: 260101001 … (varsayılan 30 öğrenci), şifre = öğrenci no
    İlk yarısı "1. Öğretim A", ikinci yarısı "1. Öğretim B" sınıfındadır.

Yük testi için: python -m scripts.seed --students 80  → A sınıfında 40 öğrenci.
"""

import argparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db.models import (
    Category,
    ClassicAcceptedAnswer,
    Exam,
    ExamQuestion,
    Question,
    QuestionOption,
    SchoolClass,
    User,
)
from server.db.session import get_session, reset_db
from server.services.auth import hash_password
from shared import config

INSTRUCTOR = ("egitmen", "egitmen123", "Dr. Öğr. Üyesi Ayşe Korkmaz")
CLASS_A = "1. Öğretim A"
CLASS_B = "1. Öğretim B"
FIRST_STUDENT_NO = 260101001
STUDENT_NAMES = [
    "Ahmet Yılmaz", "Elif Kaya", "Mehmet Demir", "Zeynep Şahin", "Mustafa Çelik",
    "Ayşe Yıldız", "Emre Aydın", "Merve Öztürk", "Burak Arslan", "Selin Doğan",
    "Can Kılıç", "Büşra Aslan", "Oğuzhan Çetin", "İrem Koç", "Yusuf Kurt",
    "Ece Özdemir", "Furkan Şimşek", "Gizem Polat", "Kerem Erdoğan", "Dilara Güneş",
    "Hakan Aksoy", "Melike Uçar", "Serkan Tekin", "Nisa Karaca", "Barış Özkan",
    "Şeyma Yalçın", "Onur Bulut", "Gamze Acar", "İbrahim Avcı", "Tuğba Ünal",
]

CAT_ARRAYS = "Diziler"
CAT_POINTERS = "İşaretçiler"
CAT_LOOPS = "Döngüler ve Koşullar"

# (kategori, soru metni, [şıklar]) — okunması kolay olsun diye DOĞRU ŞIK HER ZAMAN İLK SIRADA yazılır;
# veri tabanına eklerken şıklar döndürülür, böylece doğru cevap hep "A" olmaz.
MCQ_QUESTIONS: list[tuple[str, str, list[str]]] = [
    (CAT_ARRAYS, "int a[5] = {1, 2, 3}; tanımından sonra a[4]'ün değeri nedir?",
     ["0", "3", "Belirsiz (çöp değer)", "Derleme hatası verir"]),
    (CAT_ARRAYS, "int dizi[10]; için sizeof(dizi) / sizeof(dizi[0]) ifadesinin değeri nedir?",
     ["10", "40", "4", "Platforma göre değişir"]),
    (CAT_ARRAYS, "C'de bir diziyi fonksiyona parametre olarak verdiğimizde fonksiyona ne aktarılır?",
     ["Dizinin ilk elemanının adresi", "Dizinin tamamının kopyası",
      "Dizinin eleman sayısı", "Dizinin son elemanı"]),
    (CAT_ARRAYS, "char s[] = \"Merhaba\"; için sizeof(s) kaçtır?",
     ["8", "7", "4", "1"]),
    (CAT_POINTERS, "int x = 5; int *p = &x; *p = 10; işlemlerinden sonra x kaçtır?",
     ["10", "5", "x'in adresi", "Tanımsız davranış"]),
    (CAT_POINTERS, "int a[] = {10, 20, 30}; int *p = a; ise *(p + 2) ifadesinin değeri nedir?",
     ["30", "12", "20", "a dizisinin adresi + 2"]),
    (CAT_POINTERS, "malloc ile ayrılan bellek işi bitince hangi fonksiyonla geri verilmelidir?",
     ["free", "delete", "release", "dealloc"]),
    (CAT_POINTERS, "Hiçbir geçerli adresi göstermeyen işaretçiye hangi değer atanması önerilir?",
     ["NULL", "0xFFFF", "-1", "void"]),
    (CAT_LOOPS, "for (int i = 0; i < 5; i++) printf(\"*\"); kaç tane * yazdırır?",
     ["5", "4", "6", "Sonsuz döngüye girer"]),
    (CAT_LOOPS, "Döngünün o anki adımını atlayıp bir sonraki adıma geçen anahtar kelime hangisidir?",
     ["continue", "break", "goto", "return"]),
    (CAT_LOOPS, "int x = 7; printf(\"%d\", x % 3); ifadesi ne yazdırır?",
     ["1", "2", "0", "2.33"]),
    (CAT_LOOPS, "Gövdesi en az bir kez çalışması garanti olan döngü hangisidir?",
     ["do-while", "while", "for", "Hiçbiri"]),
]

# (kategori, soru metni, [kabul edilen cevaplar])
CLASSIC_QUESTIONS: list[tuple[str, str, list[str]]] = [
    (CAT_ARRAYS, "C'de dizilerin ilk elemanının indisi kaçtır?", ["0", "sıfır"]),
    (CAT_ARRAYS, "C'de karakter dizilerinin (string) sonunu belirten özel karakterin adı nedir?",
     ["null karakter", "\\0", "null"]),
    (CAT_ARRAYS, "Bir string'in uzunluğunu (sonlandırıcı hariç) döndüren standart kütüphane fonksiyonu hangisidir?",
     ["strlen"]),
    (CAT_POINTERS, "Bir değişkenin bellek adresini almak için kullanılan operatör hangisidir?", ["&"]),
    (CAT_POINTERS, "İşaretçinin gösterdiği adresteki değere erişmek için kullanılan operatör hangisidir?",
     ["*"]),
    (CAT_POINTERS, "malloc, calloc ve free fonksiyonları hangi başlık dosyasında tanımlıdır?",
     ["stdlib.h", "<stdlib.h>"]),
    (CAT_LOOPS, "switch yapısında hiçbir case eşleşmediğinde çalışan bölümün anahtar kelimesi nedir?",
     ["default"]),
    (CAT_LOOPS, "int i = 0; while (i < 3) i++; döngüsü bittiğinde i'nin değeri kaçtır?", ["3", "üç"]),
]

DEFAULT_STUDENT_COUNT = len(STUDENT_NAMES)

DRAFT_EXAM_TITLE = "C Programlama — Ara Sınav Denemesi"
DRAFT_EXAM_MCQ_COUNT = 6
DRAFT_EXAM_CLASSIC_COUNT = 4


def _student_no(index: int) -> str:
    return str(FIRST_STUDENT_NO + index)


def _student_name(index: int) -> str:
    """İlk 30 öğrenci listedeki isimleri alır; fazlası için ad ve soyadlar karıştırılır."""
    if index < len(STUDENT_NAMES):
        return STUDENT_NAMES[index]
    count = len(STUDENT_NAMES)
    first_name = STUDENT_NAMES[index % count].split()[0]
    last_name = STUDENT_NAMES[(index * 7 + index // count) % count].split()[-1]
    return f"{first_name} {last_name}"


def _create_users(session: Session, student_count: int) -> tuple[User, SchoolClass]:
    class_a = SchoolClass(name=CLASS_A)
    class_b = SchoolClass(name=CLASS_B)
    session.add_all([class_a, class_b])

    username, password, full_name = INSTRUCTOR
    instructor = User(
        username=username, full_name=full_name,
        password_hash=hash_password(password), role="instructor",
    )
    session.add(instructor)

    half = student_count // 2
    for i in range(student_count):
        number = _student_no(i)
        session.add(User(
            username=number, full_name=_student_name(i), password_hash=hash_password(number),
            role="student", school_class=class_a if i < half else class_b,
        ))
    return instructor, class_a


def _create_questions(session: Session) -> tuple[list[Question], list[Question]]:
    categories = {name: Category(name=name) for name in (CAT_ARRAYS, CAT_POINTERS, CAT_LOOPS)}
    session.add_all(categories.values())

    mcqs = []
    for n, (cat, text, options) in enumerate(MCQ_QUESTIONS):
        question = Question(type="mcq", text=text, category=categories[cat], default_points=10)
        correct_text = options[0]
        shift = n % len(options)
        rotated = options[-shift:] + options[:-shift] if shift else options
        question.options = [
            QuestionOption(text=opt, is_correct=(opt == correct_text), order_index=i)
            for i, opt in enumerate(rotated)
        ]
        mcqs.append(question)

    classics = []
    for cat, text, answers in CLASSIC_QUESTIONS:
        question = Question(type="classic", text=text, category=categories[cat], default_points=10)
        question.accepted_answers = [ClassicAcceptedAnswer(answer=a) for a in answers]
        classics.append(question)

    session.add_all(mcqs + classics)
    return mcqs, classics


def _create_draft_exam(
    session: Session, instructor: User, school_class: SchoolClass,
    mcqs: list[Question], classics: list[Question],
) -> None:
    session.flush()  # instructor.id ve soru id'leri oluşsun
    exam = Exam(
        title=DRAFT_EXAM_TITLE, school_class=school_class, duration_minutes=20,
        status="draft", created_by=instructor.id,
    )
    session.add(exam)
    chosen = mcqs[:DRAFT_EXAM_MCQ_COUNT] + classics[:DRAFT_EXAM_CLASSIC_COUNT]
    exam.exam_questions = [
        ExamQuestion(question_id=q.id, points=q.default_points, order_index=i)
        for i, q in enumerate(chosen)
    ]


def seed(session: Session, student_count: int = DEFAULT_STUDENT_COUNT) -> None:
    """Örnek veriyi verilen oturuma ekler (tablolar boş olmalı).

    student_count: toplam öğrenci sayısı; ilk yarısı A, ikinci yarısı B sınıfına girer.
    """
    instructor, class_a = _create_users(session, student_count)
    mcqs, classics = _create_questions(session)
    _create_draft_exam(session, instructor, class_a, mcqs, classics)


def summary(session: Session) -> dict[str, int]:
    """Tablolardaki kayıt sayıları (ekrana yazdırmak ve test için)."""
    def count(model) -> int:
        return session.scalar(select(func.count()).select_from(model)) or 0

    return {
        "kullanıcı": count(User),
        "sınıf": count(SchoolClass),
        "kategori": count(Category),
        "soru": count(Question),
        "sınav": count(Exam),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Örnek veri oluşturur (veri tabanını SIFIRLAR).")
    parser.add_argument(
        "--students", type=int, default=DEFAULT_STUDENT_COUNT,
        help="toplam öğrenci sayısı, yarısı A yarısı B sınıfına (varsayılan: %(default)s)",
    )
    args = parser.parse_args(argv)
    if not 2 <= args.students <= 999:
        parser.error("--students 2 ile 999 arasında olmalı.")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config.ensure_runtime_dirs()
    print(f"Veri tabanı sıfırlanıyor: {config.DB_PATH}")
    print(f"{args.students} öğrenci oluşturuluyor (şifreler hash'lendiği için biraz sürebilir)…")
    reset_db()
    with get_session() as session:
        seed(session, args.students)
    with get_session() as session:
        counts = summary(session)
    print("Örnek veri oluşturuldu: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    print(f"Eğitmen girişi: {INSTRUCTOR[0]} / {INSTRUCTOR[1]}")
    half = args.students // 2
    print(f"{CLASS_A}: {_student_no(0)} … {_student_no(half - 1)}")
    print(f"{CLASS_B}: {_student_no(half)} … {_student_no(args.students - 1)}")
    print("Öğrenci şifresi = öğrenci no")


if __name__ == "__main__":
    main()
