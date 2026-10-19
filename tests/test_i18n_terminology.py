"""Translations keep DOCSight's domain terms in their technical sense.

Machine translation turned modem polling into opinion polls, upstream channels into
rivers, signal power into political power or electricity, and the US abbreviation
into the United States. These checks cover the core, module and glossary catalogs.
"""

import json
import re
from pathlib import Path

import pytest

from app.glossary import get_glossary_categories, get_glossary_terms


ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIRS = [ROOT / "app" / "i18n"] + sorted(
    path for path in (ROOT / "app" / "modules").glob("*/i18n") if (path / "en.json").exists()
)
GLOSSARY_DIR = ROOT / "app" / "glossary_i18n"
LANGUAGES = sorted(path.stem for path in (ROOT / "app" / "i18n").glob("*.json") if path.stem not in {"en", "template"})

# Stems of the survey/vote sense. Spanish "sondeo" is the established networking term and stays allowed.
SURVEY_SENSE = {
    "bg": r"анкет|гласув|проучван",
    "cs": r"hlasov|anket|průzkum",
    "da": r"afstemning|meningsmåling|undersøgelse",
    "de": r"umfrage|abstimmung",
    "el": r"δημοσκ|ψηφοφ|ψήφ|ερωτήσ",
    "es": r"encuesta|votaci",
    "et": r"küsitlus|hääletus",
    "fi": r"äänest",
    "fr": r"sondage|scrutin|\bvote",
    "ga": r"vótaí|pobalbhreith",
    "hr": r"anket|glasan",
    "hu": r"szavaz|közvélemény",
    "it": r"sondagg",
    "lt": r"apklaus|balsav",
    "lv": r"aptauj|balsoš",
    "nb": r"avstemning|meningsmåling|undersøkelse",
    "nl": r"peiling",
    "pl": r"ankiet|sondaż|głosow",
    "pt": r"pesquis|sondagem|votaç|enquete",
    "ro": r"sondaj|\bvot",
    "sk": r"prieskum|hlasovan|anket",
    "sl": r"anket|glasovan",
    "sv": r"omröstning|röstning",
}

# A translated upstream/downstream string names the direction: the English term, as most catalogs
# do, or an established technical equivalent of that language. River metaphors don't qualify.
UPSTREAM_TERMS = {
    "bg": r"възходящ", "cs": r"vzestupn", "de": r"rückweg", "el": r"ανοδικ", "es": r"ascendente|subida|retorno",
    "et": r"üleslüli|üleslaadimi", "fr": r"montant|amont|retour", "ga": r"aníos|\bsuas\b|uaslódál", "hr": r"uzlazn",
    "hu": r"feltöltés", "lt": r"aukštyn|siuntimo", "lv": r"augšupsait|augšupielād|augšupejoš", "pt": r"ascendente",
    "ro": r"ascendent", "sk": r"vzostupn",
}
DOWNSTREAM_TERMS = {
    "bg": r"низходящ", "cs": r"sestupn", "el": r"καθοδικ", "es": r"descendente|bajada", "et": r"allalüli|alla- |allalaadimi",
    "fr": r"descendant|aval", "ga": r"anuas|íoslódál", "hr": r"silazn", "hu": r"letöltés", "lt": r"žemyn|atsisiuntimo",
    "lv": r"lejupsait|lejupielād|lejupejoš", "pt": r"descendente", "ro": r"descendent", "sk": r"zostupn",
}

# US/DS abbreviate upstream/downstream, never the country.
COUNTRY_SENSE = {
    "bg": r"САЩ|американ", "cs": r"\bUSA\b|americk|Spojen", "da": r"\bUSA\b|amerikan", "de": r"\bUSA\b|amerikan",
    "el": r"ΗΠΑ|αμερικ|ΔΣ|ΜΑΣ", "es": r"EE\.? ?UU|Estados Unidos|estadounid", "et": r"\bUSA\b|ameerika|Ühendriig",
    "fi": r"\bUSA\b|Yhdysval|amerikkal", "fr": r"États-Unis|\bUSA\b|améric", "ga": r"\bSAM\b|Stáit Aontaithe|Meiriceá",
    "hr": r"\bSAD\b|američk", "hu": r"\bUSA\b|amerikai|Egyesült Állam", "it": r"\bUSA\b|Stati Uniti|american",
    "lt": r"\bJAV\b|amerik", "lv": r"\bASV\b|amerikā", "nb": r"\bUSA\b|amerikan", "nl": r"\bVS\b|Verenigde Staten|Amerikaan",
    "pl": r"\bUSA\b|amerykań|Stan[ya] Zjedn", "pt": r"\bEUA\b|Estados Unidos|american", "ro": r"\bSUA\b|american",
    "sk": r"\bUSA\b|americk|Spojen", "sl": r"\bZDA\b|ameriš", "sv": r"\bUSA\b|amerikansk",
}

# Signal power is a level, not authority, electricity or a power supply.
POWER_WRONG_SENSE = {
    "cs": r"napájen|příkon", "da": r"\bstrøm", "el": r"δύναμ", "et": r"\bvõim\b|\btoide", "fi": r"^tehoa$|\bvalta",
    "hu": r"hatalm|hatalom", "lt": r"maitinim", "lv": r"spēks", "nb": r"\bstrøm", "nl": r"voeding|\bstroom\b",
    "pl": r"zasilan|pobór|moc pobieran", "pt": r"\bpoder\b", "sk": r"napájan|príkon|napájac", "sv": r"\bström",
}

INVISIBLE = re.compile("[​‌‍⁠﻿]")


def _walk(source, translation, where):
    """Yield (where, english, translation, paired) for matching strings of two catalog trees."""
    if isinstance(source, dict) and isinstance(translation, dict):
        for key, value in source.items():
            if key in translation:
                yield from _walk(value, translation[key], f"{where}.{key}")
    elif isinstance(source, list) and isinstance(translation, list):
        if len(source) == len(translation):
            for index, (value, translated) in enumerate(zip(source, translation)):
                yield from _walk(value, translated, f"{where}[{index}]")
        else:
            # Lists such as aliases differ in length; their items can't be paired one to one.
            joined = " | ".join(item for item in source if isinstance(item, str))
            for index, translated in enumerate(translation):
                if isinstance(translated, str):
                    yield f"{where}[{index}]", joined, translated, False
    elif isinstance(source, str) and isinstance(translation, str):
        yield where, source, translation, True


def _entries(lang):
    for catalog in CATALOG_DIRS:
        path = catalog / f"{lang}.json"
        if path.exists():
            source = json.loads((catalog / "en.json").read_text(encoding="utf-8"))
            translation = json.loads(path.read_text(encoding="utf-8"))
            yield from _walk(source, translation, path.relative_to(ROOT).as_posix())
    path = GLOSSARY_DIR / f"{lang}.json"
    if path.exists():
        canonical = {
            "categories": {item["id"]: item for item in get_glossary_categories()},
            "terms": {item["id"]: item for item in get_glossary_terms("en")},
        }
        localized = json.loads(path.read_text(encoding="utf-8"))
        for section, items in canonical.items():
            for item in localized.get(section, []):
                source = items.get(item.get("id"), {})
                fields = {key: value for key, value in item.items() if key in source and key not in {"id", "category", "protected_terms"}}
                yield from _walk({key: source[key] for key in fields}, fields, f"{path.relative_to(ROOT).as_posix()} {item['id']}")


def _offenders(check):
    return [
        f"{where}: {translation}"
        for lang in LANGUAGES
        for where, english, translation, paired in _entries(lang)
        if check(lang, english, translation, paired)
    ]


def test_every_language_has_terminology_rules():
    assert set(LANGUAGES) <= set(SURVEY_SENSE) & set(COUNTRY_SENSE)


def test_polling_is_not_translated_as_a_survey_or_vote():
    assert _offenders(lambda lang, en, tr, paired: re.search(r"\bpoll", en, re.I) and re.search(SURVEY_SENSE[lang], tr, re.I)) == []


@pytest.mark.parametrize(("direction", "alternatives"), [("upstream", UPSTREAM_TERMS), ("downstream", DOWNSTREAM_TERMS)])
def test_direction_terms_keep_their_technical_sense(direction, alternatives):
    def missing(lang, en, tr, paired):
        accepted = "|".join(filter(None, [direction, "uplink" if direction == "upstream" else "downlink", alternatives.get(lang)]))
        return paired and re.search(direction, en, re.I) and not re.search(accepted, tr, re.I)

    assert _offenders(missing) == []


def test_us_and_ds_abbreviate_directions_not_the_country():
    assert _offenders(lambda lang, en, tr, paired: re.search(r"\b(US|DS)\b", en) and re.search(COUNTRY_SENSE[lang], tr, re.I)) == []


def test_signal_power_is_not_translated_as_authority_or_electricity():
    def wrong(lang, en, tr, paired):
        return lang in POWER_WRONG_SENSE and re.search(r"\bpower", en, re.I) and re.search(POWER_WRONG_SENSE[lang], tr, re.I)

    assert _offenders(wrong) == []


def test_catalogs_contain_no_invisible_characters():
    paths = [path for catalog in [*CATALOG_DIRS, GLOSSARY_DIR] for path in catalog.glob("*.json")]
    assert [path.relative_to(ROOT).as_posix() for path in paths if INVISIBLE.search(path.read_text(encoding="utf-8"))] == []


@pytest.mark.parametrize(
    ("rules", "lang", "text"),
    [
        (SURVEY_SENSE, "fi", "Äänestysväli"),
        (SURVEY_SENSE, "nl", "Opiniepeilingsinterval"),
        (COUNTRY_SENSE, "el", "Δύναμη των ΗΠΑ"),
        (COUNTRY_SENSE, "nb", "Gjennomsnittlig strøm i USA"),
        (POWER_WRONG_SENSE, "hu", "Hatalom"),
        (POWER_WRONG_SENSE, "cs", "Příkon kriticky nízký"),
    ],
)
def test_patterns_catch_known_mistranslations(rules, lang, text):
    assert re.search(rules[lang], text, re.IGNORECASE)


@pytest.mark.parametrize(("lang", "text"), [("bg", "Нагоре по течението"), ("pl", "Wydobycie Własne"), ("it", "A monte")])
def test_river_translations_lack_the_upstream_term(lang, text):
    accepted = "|".join(filter(None, ["upstream", "uplink", UPSTREAM_TERMS.get(lang)]))
    assert not re.search(accepted, text, re.IGNORECASE)
