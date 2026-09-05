"""Translation catalog boundaries for the modulation module."""

import json
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parents[1] / "app/modules/modulation/i18n"


def test_capacity_catalog_explains_estimate():
    catalog = json.loads((I18N_DIR / "en.json").read_text(encoding="utf-8"))
    for key in ("capacity_title", "capacity_disclaimer", "capacity_warning_not_throughput", "capacity_partial_caveat"):
        assert catalog[key].strip()
    assert "Calculated SC-QAM gross capacity" in catalog["capacity_title"]
    assert "Not speedtest throughput" in catalog["capacity_warning_not_throughput"]
    assert "not tariff speed" in catalog["capacity_warning_not_tariff"].lower()


def test_low_qam_denominator_hint_is_localized_for_all_modulation_languages():
    for path in I18N_DIR.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["low_qam_denominator_hint"].strip(), path.name


def test_low_qam_legend_hint_key_is_localized_for_all_modulation_languages():
    for path in I18N_DIR.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["low_qam_legend_hint_d31_us"].strip(), path.name


def test_docsis_30_upstream_legend_hint_key_is_localized_for_all_modulation_languages():
    for path in I18N_DIR.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["low_qam_legend_hint_d30_us"].strip(), path.name
