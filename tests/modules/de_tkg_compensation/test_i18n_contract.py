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


def test_german_first_step_is_rights_first_and_keeps_accessible_start_paths():
    module = Path("app/modules/de_tkg_compensation")
    german = json.loads(
        (module / "i18n" / "de.json").read_text(encoding="utf-8")
    )
    template = (module / "templates" / "tkg_tab.html").read_text(encoding="utf-8")

    rights_first_strings = {
        key: german.get(key)
        for key in (
            "title",
            "subtitle",
            "de_scope",
            "rights_heading",
            "case_complete_title",
            "case_appointment_title",
            "step_candidate",
            "automatic_title",
            "candidate_help",
            "candidate_empty",
            "candidate_derived",
            "candidate_use",
            "load_candidates",
            "manual_window",
            "window_from",
            "window_to",
            "appointment_only_help",
            "performance_path",
            "next_first",
        )
    }
    assert rights_first_strings == {
        "title": "Mögliche Entschädigung prüfen",
        "subtitle": (
            "Internet oder Telefon komplett ausgefallen? Anbietertermin versäumt? "
            "Dann kann eine gesetzliche Entschädigung zustehen."
        ),
        "de_scope": "Für Verträge in Deutschland · TKG § 58",
        "rights_heading": "In diesen Fällen kann eine Entschädigung zustehen",
        "case_complete_title": "Vollständiger Ausfall",
        "case_appointment_title": "Versäumter Anbietertermin",
        "step_candidate": "1 · Ausfall oder Termin",
        "automatic_title": "Ausfall automatisch finden",
        "candidate_help": (
            "DOCSight durchsucht die gespeicherten Messwerte nach einem möglichen "
            "Ausfallzeitraum. Sie entscheiden selbst, ob Sie ihn übernehmen."
        ),
        "candidate_empty": (
            "Kein eindeutiger Ausfallzeitraum erkannt. Tragen Sie den Zeitraum "
            "selbst ein."
        ),
        "candidate_derived": "In Messdaten erkannt · bitte prüfen",
        "candidate_use": "Ausfallzeitraum übernehmen",
        "load_candidates": "Messdaten erneut prüfen",
        "manual_window": "Ausfallzeitraum selbst eintragen",
        "window_from": "Ausfall begann",
        "window_to": "Ausfall endete",
        "appointment_only_help": (
            "Nur einen versäumten Anbietertermin prüfen? Beide Zeitfelder leer "
            "lassen und mit „Weiter zu den Angaben“ fortfahren."
        ),
        "performance_path": (
            "Nur langsam oder instabil? Für eine mögliche Minderung gilt das "
            "offizielle Messverfahren der Bundesnetzagentur."
        ),
        "next_first": "Weiter zu den Angaben",
    }, rights_first_strings

    complete_case = german["case_complete_body"]
    assert "Internet oder Telefon" in complete_case
    assert "dritten Kalendertag" in complete_case
    assert "Störungsmeldung" in complete_case and "Anbieter" in complete_case
    assert "kann" in complete_case and "Entschädigung" in complete_case

    appointment_case = german["case_appointment_body"]
    assert "Kundendienst- oder Installationstermin" in appointment_case
    assert "unabhängig" in appointment_case
    assert "kann" in appointment_case and "Entschädigung" in appointment_case

    outcome = german["outcome_copy"]
    for wording in ("prüft", "berechnet", "möglichen Betrag", "bearbeitbares Schreiben"):
        assert wording in outcome
    assert "DOCSight" in outcome and "Anbieter" in outcome
    assert "Daten" in german["privacy_copy"]
    assert "diesem DOCSight-System" in german["privacy_copy"]
    assert "Keine Rechtsberatung" in german["disclaimer"]
    assert "keine Erfolgsgarantie" in german["disclaimer"]
    assert "Ausfallzeitraum" in german["manual_window"]
    assert "Ausfall" in german["window_from"]
    assert "Ausfall" in german["window_to"]
    for key in (
        "candidate_help",
        "candidate_empty",
        "candidate_derived",
        "candidate_use",
        "candidate_ongoing",
        "status_candidates_loaded",
    ):
        assert "Vorschlag" not in german[key]

    first_step = template.split('data-tkg-step="1"', 1)[1].split(
        'data-tkg-step="2"', 1
    )[0]
    assert (
        '<section class="tkg-rights-overview" '
        'aria-labelledby="tkg-rights-heading">'
    ) in first_step
    assert 'id="tkg-rights-heading"' in first_step
    assert first_step.count('class="tkg-rights-case"') == 2
    assert (
        '<section class="tkg-outcome" aria-labelledby="tkg-outcome-heading">'
    ) in first_step
    assert 'id="tkg-outcome-heading"' in first_step
    assert 'class="tkg-privacy"' in first_step
    assert (
        'id="tkg-performance-link" href="https://www.breitbandmessung.de/"'
    ) in first_step
    assert ">Breitbandmessung</a>" in first_step

    assert 'class="tkg-start-grid tkg-grid tkg-grid-2"' in first_step
    assert first_step.count('class="tkg-start-option"') == 2
    for element_id in (
        "tkg-load-candidates",
        "tkg-candidates",
        "tkg-window-from",
        "tkg-window-to",
    ):
        assert f'id="{element_id}"' in first_step

    assert (
        'id="tkg-status" class="tkg-status" role="status" aria-live="polite"'
        in template
    )
    assert 'class="tkg-legal-note"' in first_step
    assert "docsight.de_tkg_compensation.disclaimer" in first_step
    assert 'id="tkg-glossary-link"' in first_step
    assert "docsight.de_tkg_compensation.glossary_link" in first_step
    assert "_anchor='glossary?term=tkg_rights_de'" in first_step
    assert re.search(
        r'<button class="btn btn-accent" id="tkg-next"[^>]*>.*next_first',
        template,
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


def test_localized_placeholders_match_english_catalog():
    directory = Path("app/modules/de_tkg_compensation/i18n")
    english = json.loads((directory / "en.json").read_text(encoding="utf-8"))
    for path in directory.glob("*.json"):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        for key, source in english.items():
            expected = Counter(re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", source))
            actual = Counter(re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", catalog[key]))
            assert actual == expected, f"placeholder parity failed for {path.stem}.{key}"


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
