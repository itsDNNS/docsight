"""Locale coverage and protected-literal contracts."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


LOCALES = {
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "ga", "hr",
    "hu", "it", "lt", "lv", "nb", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
}
PROTECTED_LITERALS = (
    "ROUND_HALF_UP", "Bundesnetzagentur", "Verbraucherzentrale", "DOCSight",
    "§58(3)", "§58", "TKG", "€0.00", ".txt", "PDF", "€",
)


def test_all_natural_locale_catalogs_have_the_complete_key_set():
    directory = Path("app/modules/de_tkg_compensation/i18n")
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
    }

    assert set(catalogs) == LOCALES
    assert all(set(catalog) == set(catalogs["en"]) for catalog in catalogs.values())
    assert all(catalog["title"] != catalogs["en"]["title"] for code, catalog in catalogs.items() if code != "en")
    assert all(
        sum(value == catalogs["en"][key] for key, value in catalog.items()) <= 1
        for code, catalog in catalogs.items()
        if code != "en"
    )


def test_localized_guidance_preserves_sentences_and_has_no_degenerate_repetition():
    directory = Path("app/modules/de_tkg_compensation/i18n")
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
    }
    english = catalogs["en"]
    for code, catalog in catalogs.items():
        if code == "en":
            continue
        for key, source in english.items():
            sentence_count = len(re.findall(r"[.!?](?:\s|$)", source))
            localized_count = len(re.findall(r"[.!?](?:\s|$)", catalog[key]))
            assert localized_count >= sentence_count, f"shortened {code}.{key}"
            words = catalog[key].split()
            if len(words) > 20:
                repeats = Counter(words).most_common(1)[0][1]
                assert repeats <= max(5, len(words) // 4), f"repetition in {code}.{key}"


def test_protected_legal_and_technical_literals_are_not_localized():
    directory = Path("app/modules/de_tkg_compensation/i18n")
    english = json.loads((directory / "en.json").read_text(encoding="utf-8"))
    for path in directory.glob("*.json"):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        for key, source in english.items():
            for literal in PROTECTED_LITERALS:
                assert catalog[key].count(literal) == source.count(literal), (
                    f"protected literal parity failed for {path.stem}.{key}: {literal}"
                )


def test_non_english_catalogs_do_not_retain_multiword_english_fragments():
    directory = Path("app/modules/de_tkg_compensation/i18n")
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
    }
    english = catalogs["en"]
    protected_words = {
        word.casefold()
        for literal in PROTECTED_LITERALS
        for word in re.findall(r"[A-Za-z]+", literal)
    }
    for code, catalog in catalogs.items():
        if code in {"en", "de"}:
            continue
        for key, source in english.items():
            words = re.findall(r"[A-Za-z]+", source)
            fragments = {
                " ".join(words[index:index + 3]).casefold()
                for index in range(max(0, len(words) - 2))
                if not any(
                    word.casefold() in protected_words
                    for word in words[index:index + 3]
                )
            }
            normalized = " ".join(re.findall(r"[A-Za-z]+", catalog[key])).casefold()
            assert not any(fragment in normalized for fragment in fragments), (
                f"untranslated English fragment in {code}.{key}"
            )
