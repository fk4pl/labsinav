"""Soru metnini ekranda gösterilecek HTML'e çevirir. (Sahibi: C)

Kural (soru bankasında da aynı yazım kullanılmalı):
    `x++`          -> satır içi kod (eşit genişlikli font)
    ```            -> çok satırlı kod bloğu başlangıcı / bitişi
    int a = 5;
    ```
Metin önce HTML-escape edilir: soruda "<" veya "&" yazsa da ekran bozulmaz.
"""

import html
import re

MONO_FONT = "'Consolas', 'DejaVu Sans Mono', 'Courier New', monospace"
_INLINE_CODE = re.compile(r"`([^`\n]+)`")


def _render_plain(text: str) -> str:
    escaped = html.escape(text)
    escaped = _INLINE_CODE.sub(
        lambda m: f'<code style="font-family:{MONO_FONT}; background:#eef2f9;">{m.group(1)}</code>',
        escaped,
    )
    return escaped.replace("\n", "<br>")


def _render_code_block(code: str) -> str:
    code = code.strip("\n")
    return (
        f'<pre style="font-family:{MONO_FONT}; background:#f3f4f6; '
        f'padding:8px; margin:6px 0;">{html.escape(code)}</pre>'
    )


def question_to_html(text: str) -> str:
    """``` ile ayrılan parçalar sırayla: düz metin, kod, düz metin, kod, ..."""
    parts = text.split("```")
    pieces = []
    for index, part in enumerate(parts):
        is_code = index % 2 == 1 and index < len(parts) - 1  # kapanmamış ``` düz metin sayılır
        if is_code:
            # ```c gibi dil adı yazılmışsa ilk satırı at
            first_line, _, rest = part.partition("\n")
            if first_line.strip().isalnum() and rest:
                part = rest
            pieces.append(_render_code_block(part))
        else:
            if index % 2 == 1:
                part = "```" + part
            pieces.append(_render_plain(part))
    return "".join(pieces)
