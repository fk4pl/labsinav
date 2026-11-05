from student_app.ui.question_text import question_to_html
from student_app.ui.zoom import scale_font_sizes


def test_html_is_escaped() -> None:
    assert "&lt;b&gt;" in question_to_html("a <b> c")


def test_inline_code_uses_monospace() -> None:
    html = question_to_html("`x++` nedir?")
    assert "<code" in html and "x++" in html


def test_code_block_keeps_lines_and_drops_language_name() -> None:
    html = question_to_html("Çıktı?\n```c\nint a = 1 < 2;\nprintf(\"%d\", a);\n```\nSon")
    assert "<pre" in html
    assert "int a = 1 &lt; 2;\nprintf" in html
    assert ">c\n" not in html
    assert html.endswith("<br>Son")


def test_unclosed_fence_is_plain_text() -> None:
    assert "<pre" not in question_to_html("sadece ``` bir tane")


def test_scale_font_sizes() -> None:
    assert scale_font_sizes("a{font-size: 14px;} b{font-size:20px}", 1.5) == (
        "a{font-size: 21px;} b{font-size: 30px}"
    )
