"""Padrão de estrutura de pastas digitado pelo usuário (ver PLANO.md §2).

Exemplo: ``aaaa > mm - month > dd`` → ``2026\\10 - Outubro\\27``.

- ``>`` separa os níveis de pasta;
- tokens (sem diferenciar maiúsculas): ``aaaa``/``yyyy``, ``aa``/``yy``, ``mm``, ``month``,
  ``mon``, ``dd``;
- uma palavra só vira token quando ela inteira é formada por tokens (``aaaammdd`` vira
  ``20261027``, mas ``Montanha`` continua literal);
- texto entre aspas é sempre literal: ``"Viagem" > aaaa``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import cache

MONTHS = {
    "pt": (
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}  # fmt: skip
MONTHS_SHORT = {lang: tuple(name[:3] for name in names) for lang, names in MONTHS.items()}

# Mais longos primeiro, para "aaaa" não ser lido como "aa" + "aa".
_TOKENS = ("aaaa", "yyyy", "month", "mon", "aa", "yy", "mm", "dd")
_ALIASES = {"yyyy": "aaaa", "yy": "aa"}

PRESETS = (
    "aaaa > mm > dd",
    "aaaa > mm",
    "aaaa > month",
    "aaaa > mm - month > dd",
    "aaaa-mm-dd",
    "mm > dd",
)

_INVALID_CHARS = set('\\/:*?"<>|') | {chr(c) for c in range(32)}
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
_WORD_RE = re.compile(r"[^\W\d_]+")  # sequência de letras (inclui acentuadas)


class PatternError(ValueError):
    """Padrão inválido. ``code`` identifica o erro para a interface traduzir a mensagem."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Token:
    name: str  # nome canônico: aaaa, aa, mm, month, mon, dd


Segment = str | Token
Level = tuple[Segment, ...]


@dataclass(frozen=True, slots=True)
class FolderPattern:
    text: str
    levels: tuple[Level, ...]

    @classmethod
    def parse(cls, text: str) -> FolderPattern:
        levels = tuple(_parse_level(raw) for raw in _split_levels(text))
        if not levels:
            raise PatternError("empty", "O padrão está vazio.")
        pattern = cls(text, levels)
        for lang in MONTHS:  # valida os nomes de pasta resultantes em todos os idiomas
            for name in pattern.render(datetime(2026, 10, 27), lang):
                validate_folder_name(name)
        return pattern

    def render(self, dt: datetime, lang: str = "pt") -> list[str]:
        """Nomes das pastas, do nível mais alto para o mais baixo."""
        return ["".join(_render(seg, dt, lang) for seg in level).strip() for level in self.levels]


def _split_levels(text: str) -> list[str]:
    if text.count('"') % 2:
        raise PatternError("unclosed_quote", "Há uma aspa sem fechamento no padrão.")
    if not text.strip():
        return []
    levels, current, quoted = [], [], False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == ">" and not quoted:
            levels.append("".join(current))
            current = []
        else:
            current.append(ch)
    levels.append("".join(current))
    return levels


def _parse_level(raw: str) -> Level:
    segments: list[Segment] = []
    for i, part in enumerate(raw.split('"')):
        if i % 2:  # trecho entre aspas: literal
            segments.append(part)
        else:
            segments.extend(_tokenize(part))
    level = tuple(s for s in segments if s != "")
    if not level or all(isinstance(s, str) and not s.strip() for s in level):
        raise PatternError("empty_level", "Há um nível de pasta vazio (dois '>' seguidos?).")
    return level


def _tokenize(text: str) -> list[Segment]:
    segments: list[Segment] = []
    pos = 0
    for m in _WORD_RE.finditer(text):
        tokens = _split_word(m.group().lower())
        if tokens is None:
            continue
        segments.append(text[pos : m.start()])
        segments.extend(Token(_ALIASES.get(t, t)) for t in tokens)
        pos = m.end()
    segments.append(text[pos:])
    return segments


@cache
def _split_word(word: str) -> tuple[str, ...] | None:
    """Decompõe uma palavra inteira em tokens, ou ``None`` se não for possível."""
    if not word:
        return ()
    for token in _TOKENS:
        if word.startswith(token) and (rest := _split_word(word[len(token) :])) is not None:
            return (token, *rest)
    return None


def _render(segment: Segment, dt: datetime, lang: str) -> str:
    if isinstance(segment, str):
        return segment
    match segment.name:
        case "aaaa":
            return f"{dt.year:04d}"
        case "aa":
            return f"{dt.year % 100:02d}"
        case "mm":
            return f"{dt.month:02d}"
        case "month":
            return MONTHS[lang][dt.month - 1]
        case "mon":
            return MONTHS_SHORT[lang][dt.month - 1]
        case "dd":
            return f"{dt.day:02d}"
    raise AssertionError(segment.name)


def validate_folder_name(name: str) -> None:
    bad = sorted({ch for ch in name if ch in _INVALID_CHARS})
    if bad:
        shown = " ".join(repr(ch) if ord(ch) < 32 else ch for ch in bad)
        raise PatternError("invalid_char", f"Caractere não permitido em nome de pasta: {shown}")
    if name.endswith("."):
        raise PatternError("trailing_dot", f"Nome de pasta não pode terminar com ponto: {name}")
    if name.split(".")[0].strip().upper() in _RESERVED:
        raise PatternError("reserved_name", f"Nome reservado pelo Windows: {name}")
