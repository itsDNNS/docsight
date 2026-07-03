import pytest

from app.maintainer_notices import (
    NoticeValidationError,
    coerce_dismissed_notice_ids,
    get_active_notices,
    validate_notice_schema,
)


def _notice(**overrides):
    data = {
        "id": "test-notice",
        "severity": "info",
        "title": "Local notice",
        "body": "Bundled with DOCSight.",
        "locations": ("dashboard", "settings"),
    }
    data.update(overrides)
    return data


def test_active_notice_matches_location_and_excludes_dismissed_ids():
    notices = [_notice(id="visible"), _notice(id="dismissed")]

    active = get_active_notices(
        dismissed_ids=["dismissed"],
        location="dashboard",
        notices=notices,
    )

    assert [notice["id"] for notice in active] == ["visible"]


def test_notice_severity_sorting_prioritizes_critical_then_warning_then_info():
    notices = [
        _notice(id="info", severity="info"),
        _notice(id="critical", severity="critical"),
        _notice(id="warning", severity="warning"),
    ]

    active = get_active_notices(notices=notices)

    assert [notice["id"] for notice in active] == ["critical", "warning", "info"]


def test_notice_payload_exposes_only_shipped_public_fields():
    notices = [
        _notice(
            id="linked",
            link_label="Open",
            link_url="/settings#about",
            internal_note="operator-only",
        )
    ]

    active = get_active_notices(notices=notices)

    assert active == [
        {
            "id": "linked",
            "severity": "info",
            "title": "Local notice",
            "body": "Bundled with DOCSight.",
            "link_label": "Open",
            "link_url": "/settings#about",
        }
    ]


def test_notices_reject_remote_html_and_unsafe_links():
    with pytest.raises(NoticeValidationError):
        validate_notice_schema(_notice(id="unsafe'id"))

    with pytest.raises(NoticeValidationError):
        validate_notice_schema(_notice(body="<strong>remote html</strong>"))

    with pytest.raises(NoticeValidationError):
        validate_notice_schema(_notice(link_url="javascript:alert(1)", link_label="Open"))


def test_relative_and_https_links_are_allowed():
    validate_notice_schema(_notice(link_url="/settings#about", link_label="Open"))
    validate_notice_schema(_notice(link_url="https://github.com/itsDNNS/docsight", link_label="Open"))


def test_invalid_notices_are_ignored_so_notices_remain_non_blocking():
    notices = [
        _notice(id="visible"),
        _notice(id="bad-html", body="<strong>broken</strong>"),
        "not-a-mapping",
        _notice(id="bad-link", link_url=["https://example.com"], link_label="Open"),
        _notice(id="bad-location", locations=(["dashboard"],)),
    ]

    active = get_active_notices(notices=notices)

    assert [notice["id"] for notice in active] == ["visible"]


def test_dismissed_notice_ids_are_validated_deduped_and_bounded():
    raw = [f"notice-{idx}" for idx in range(205)] + ["bad id", "notice-204"]

    normalized = coerce_dismissed_notice_ids(raw)

    assert len(normalized) == 200
    assert "bad id" not in normalized
    assert normalized[-1] == "notice-204"
