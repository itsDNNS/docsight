"""Shared empty state macro (partials/empty_state.html)."""

from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
ENV = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
T = {"empty_glossary_link": "What does this view show?"}


def _render(call):
    template = ENV.from_string(
        '{% from "partials/empty_state.html" import empty_state with context %}' + call
    )
    return BeautifulSoup(template.render(t=T), "html.parser")


def test_full_state_has_icon_reason_action_and_glossary_link():
    soup = _render(
        "{{ empty_state('x-empty', 'upload', 'Nothing yet', 'Because nothing ran.', "
        "action_label='Do it', action_href='/settings#connection', glossary='bnetza') }}"
    )
    root = soup.select_one("#x-empty.view-empty")
    assert root["role"] == "status" and not root.has_attr("hidden")
    assert root.select_one(".view-empty-icon i")["data-lucide"] == "upload"
    assert root.select_one(".view-empty-icon")["aria-hidden"] == "true"
    assert root.select_one(".view-empty-title").text == "Nothing yet"
    assert root.select_one(".view-empty-text").text == "Because nothing ran."
    action = root.select_one("a.view-empty-action")
    assert action["href"] == "/settings#connection" and action.text == "Do it"
    link = root.select_one("a.view-empty-link")
    assert link["href"] == "#glossary?term=bnetza" and link.text == T["empty_glossary_link"]


def test_button_action_and_hidden_state():
    soup = _render(
        "{{ empty_state('y', 'layers', 'Pick one', action_label='Choose', "
        "action_focus='#a', hidden=True) }}"
    )
    root = soup.select_one("#y")
    assert root.has_attr("hidden")
    button = root.select_one("button.view-empty-action")
    assert button["type"] == "button" and button["data-focus-target"] == "#a"
    assert not button.has_attr("onclick")
    assert root.select_one(".view-empty-text") is None
    assert root.select_one(".view-empty-link") is None


def test_state_without_action_or_glossary_has_no_action_row():
    soup = _render("{{ empty_state('z', 'info', 'Only a title') }}")
    assert soup.select_one("#z .view-empty-actions") is None
