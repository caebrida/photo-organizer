from datetime import datetime

import pytest

from photo_organizer.core.pattern import PRESETS, FolderPattern, PatternError

DT = datetime(2026, 10, 27, 14, 32, 8)


def render(text: str, lang: str = "pt") -> list[str]:
    return FolderPattern.parse(text).render(DT, lang)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("aaaa > mm > dd", ["2026", "10", "27"]),
        ("aaaa > mm", ["2026", "10"]),
        ("aaaa > month", ["2026", "Outubro"]),
        ("aaaa > mm - month > dd", ["2026", "10 - Outubro", "27"]),
        ("aaaa-mm-dd", ["2026-10-27"]),
        ("yyyy>mm>dd", ["2026", "10", "27"]),
        ("AAAA > MM > DD", ["2026", "10", "27"]),
        ("aa_mon", ["26_Out"]),
        ("aaaammdd", ["20261027"]),
        ("mm > dd", ["10", "27"]),
    ],
)
def test_render_pt(text, expected):
    assert render(text) == expected


def test_month_follows_language():
    assert render("aaaa > month > mon", "en") == ["2026", "October", "Oct"]
    assert render("month mon", "pt") == ["Outubro Out"]


def test_words_that_are_not_only_tokens_stay_literal():
    assert render("Montanha aaaa") == ["Montanha 2026"]
    assert render("Saara > dd") == ["Saara", "27"]


def test_quoted_text_is_never_a_token():
    assert render('"Viagem" > aaaa') == ["Viagem", "2026"]
    assert render('"dd mm" aaaa') == ["dd mm 2026"]


def test_quoted_text_can_hold_separator_but_is_rejected_as_folder_name():
    with pytest.raises(PatternError) as err:
        FolderPattern.parse('"a > b"')
    assert err.value.code == "invalid_char"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("aaaa >> dd", "empty_level"),
        ("aaaa > ", "empty_level"),
        ('"Viagem > aaaa', "unclosed_quote"),
        ("aaaa: mm", "invalid_char"),
        ("aaaa > fotos?", "invalid_char"),
        ("aaaa > a|b", "invalid_char"),
        ("aaaa > CON", "reserved_name"),
        ("nul.txt > aaaa", "reserved_name"),
        ("aaaa > fim.", "trailing_dot"),
    ],
)
def test_invalid_patterns(text, code):
    with pytest.raises(PatternError) as err:
        FolderPattern.parse(text)
    assert err.value.code == code
    assert str(err.value)  # mensagem legível para o usuário


def test_presets_are_valid():
    for text in PRESETS:
        FolderPattern.parse(text)
