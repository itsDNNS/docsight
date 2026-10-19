"""Polling a modem must not be translated as an opinion poll, survey or vote."""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIRS = [ROOT / "app" / "i18n"] + sorted(
    path for path in (ROOT / "app" / "modules").glob("*/i18n") if (path / "en.json").exists()
)
POLL_SOURCE = re.compile(r"\bpoll", re.IGNORECASE)

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


def _polling_entries():
    for catalog in CATALOG_DIRS:
        source = json.loads((catalog / "en.json").read_text(encoding="utf-8"))
        keys = [key for key, value in source.items() if isinstance(value, str) and POLL_SOURCE.search(value)]
        for path in sorted(catalog.glob("*.json")):
            if path.stem in SURVEY_SENSE:
                translations = json.loads(path.read_text(encoding="utf-8"))
                for key in keys:
                    yield path, key, translations.get(key) or ""


def test_every_translated_catalog_has_a_survey_sense_pattern():
    languages = {path.stem for catalog in CATALOG_DIRS for path in catalog.glob("*.json")}
    assert languages - {"en", "template"} <= set(SURVEY_SENSE)


def test_polling_is_not_translated_as_a_survey_or_vote():
    offenders = [
        f"{path.relative_to(ROOT).as_posix()} {key}: {value}"
        for path, key, value in _polling_entries()
        if re.search(SURVEY_SENSE[path.stem], value, re.IGNORECASE)
    ]
    assert offenders == []


@pytest.mark.parametrize(("lang", "text"), [("fi", "Äänestysväli"), ("nl", "Opiniepeilingsinterval"), ("es", "encuestas")])
def test_survey_sense_patterns_catch_known_mistranslations(lang, text):
    assert re.search(SURVEY_SENSE[lang], text, re.IGNORECASE)
