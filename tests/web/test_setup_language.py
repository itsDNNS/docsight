"""Focused contracts for first-run setup language selection."""

import json
import re

import pytest

from app.config import ConfigManager
from app.i18n import LANGUAGES
from app.runtime import current_runtime


def _html_lang(response):
    match = re.search(r'<html lang="([^"]+)"', response.get_data(as_text=True))
    assert match is not None
    return match.group(1)


def _stored_config(manager):
    with open(manager.config_path, encoding="utf-8") as config_file:
        return json.load(config_file)


@pytest.fixture
def fresh_manager(tmp_path):
    manager = ConfigManager(str(tmp_path / "data"))
    current_runtime().config_manager = manager
    current_runtime().storage = None
    app.config["TESTING"] = True
    return manager


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("en-US,en;q=0.9", "en"),
        ("pt-BR,pt;q=0.9", "pt"),
        ("fr", "fr"),
        ("fr;q=0.1,de-DE;q=0.9", "de"),
        ("zz-ZZ,xx;q=0.9", "en"),
    ],
)
def test_fresh_setup_negotiates_and_persists_supported_language(
    fresh_manager, accept_language, expected
):
    with app.test_client() as client:
        response = client.get(
            "/setup", headers={"Accept-Language": accept_language}
        )

    assert response.status_code == 200
    assert _html_lang(response) == expected
    assert fresh_manager.has_stored_value("language") is True
    assert _stored_config(fresh_manager)["language"] == expected


def test_fresh_setup_without_accept_language_persists_product_default(fresh_manager):
    with app.test_client() as client:
        response = client.get("/setup")

    assert response.status_code == 200
    assert _html_lang(response) == "en"
    assert _stored_config(fresh_manager)["language"] == "en"


def test_first_inference_survives_new_manager_client_and_changed_header(
    fresh_manager
):
    with app.test_client() as first_client:
        first_response = first_client.get(
            "/setup", headers={"Accept-Language": "de-DE"}
        )

    reloaded = ConfigManager(fresh_manager.data_dir)
    current_runtime().config_manager = reloaded
    with app.test_client() as second_client:
        second_response = second_client.get(
            "/setup", headers={"Accept-Language": "fr-FR"}
        )

    assert _html_lang(first_response) == "de"
    assert _html_lang(second_response) == "de"
    assert _stored_config(reloaded)["language"] == "de"


def test_valid_explicit_setup_language_overrides_and_persists(fresh_manager):
    fresh_manager.save({"language": "de"})

    with app.test_client() as client:
        explicit_response = client.get("/setup?lang=fr")
        later_response = client.get(
            "/setup", headers={"Accept-Language": "de-DE"}
        )

    assert _html_lang(explicit_response) == "fr"
    assert _html_lang(later_response) == "fr"
    assert _stored_config(fresh_manager)["language"] == "fr"


def test_existing_stored_preference_wins_over_browser_header(fresh_manager):
    fresh_manager.save({"language": "pl"})

    with app.test_client() as client:
        response = client.get(
            "/setup", headers={"Accept-Language": "de-DE"}
        )

    assert _html_lang(response) == "pl"
    assert _stored_config(fresh_manager)["language"] == "pl"


def test_invalid_query_is_ignored_and_never_persisted(fresh_manager):
    with app.test_client() as client:
        response = client.get(
            "/setup?lang=not-a-locale",
            headers={"Accept-Language": "de-DE"},
        )

    assert _html_lang(response) == "de"
    assert _stored_config(fresh_manager)["language"] == "de"


def test_setup_renders_every_registered_locale_option(fresh_manager):
    with app.test_client() as client:
        response = client.get("/setup", headers={"Accept-Language": "en-US"})

    html = response.get_data(as_text=True)
    language_select = html.split('id="lang-select"', 1)[1].split("</select>", 1)[0]
    rendered_options = set(
        re.findall(r'<option value="([^"]+)"', language_select)
    )
    assert rendered_options == set(LANGUAGES)


def test_non_setup_language_query_remains_transient(fresh_manager):
    fresh_manager.save({"modem_type": "fritzbox"})

    with app.test_client() as client:
        response = client.get("/settings?lang=de")

    assert response.status_code == 200
    assert _html_lang(response) == "de"
    assert fresh_manager.has_stored_value("language") is False
