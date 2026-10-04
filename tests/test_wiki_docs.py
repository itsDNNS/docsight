"""Checks that the repository and the published GitHub Wiki agree.

User and developer documentation lives in the Wiki. These tests read a real
checkout of https://github.com/itsDNNS/docsight.wiki.git from DOCSIGHT_WIKI_DIR.
Without one they are skipped locally; in CI a missing checkout fails, so the
coverage cannot disappear silently.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.test_defensive_review_docs import SECRET_PATTERNS

pytestmark = pytest.mark.wiki

ROOT = Path(__file__).resolve().parents[1]
WIKI_URL = "https://github.com/itsDNNS/docsight/wiki"
WIKI_LINK_RE = re.compile(
    r"https://github\.com/itsDNNS/docsight/wiki(?:/(?P<page>[A-Za-z0-9@!._-]+))?(?:#(?P<anchor>[\w-]+))?"
)
REPO_FILE_LINK_RE = re.compile(
    r"https://(?:raw\.githubusercontent\.com/itsDNNS/docsight/main"
    r"|github\.com/itsDNNS/docsight/(?:blob|tree)/main)/(?P<path>[^\s)\"'<>#?]+)"
)
PRIVATE_VALUE_RE = re.compile(
    r"(localhost|127\.0\.0\.1|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.|Vodafone Kabel)", re.I
)
SCANNED_SUFFIXES = {".md", ".html", ".yml", ".yaml", ".py", ".js", ".json", ".ps1"}
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "test-results", "__pycache__", ".pytest_cache"}

# Pages that replaced repository documents, or describe behavior the code still implements,
# with content that must survive there.
MIGRATED_CONTENT = {
    "Features-BNetzA": [
        "## Complaint Letter",
        "click its **pencil icon** to open the complaint dialog with that campaign selected",
        "DOCSight prefers the newest campaign with a parsed deviation; if none has one, it uses the newest campaign.",
        "## Automated File Watcher",
        "BNETZ_WATCH_DIR=/data/bnetz",
    ],
    "Architecture": [
        "app.app_factory.create_app()",
        "## Driver architecture",
        "FORMAT_FAMILIES",
        "aggregate_snapshot_period()",
        "### Dashboard signal data path",
    ],
    "Installation": [
        "## Image tags: stable or latest",
        "`vYYYY-MM-DD.N`",
        "docker exec docsight python -m app.doctor --json",
    ],
    "Running-without-Docker": [
        "libjpeg62-turbo-dev",
        "tools/icmp_probe_helper.c",
        "chmod 4755",
    ],
    "Windows-Quick-Start": [
        "docker run -d --name docsight --restart unless-stopped -p 8765:8765 "
        "-v docsight_data:/data ghcr.io/itsdnns/docsight:stable",
        "## Windows troubleshooting",
    ],
    "Windows-Desktop-Preview": [
        "DOCSight-Desktop-Preview-win64-<version>.zip.sha256",
        "## Known v0 limitations",
        "%LOCALAPPDATA%\\DOCSight\\runtime.json",
        "Docker remains the recommended path for 24/7 monitoring",
    ],
    "Notifications": [
        "`/notify/{config_key}`",
        "APPRISE_STATELESS_URLS",
        "NOTIFY_PWA_PUSH_VAPID_PRIVATE_KEY",
        "Push payloads are intentionally short",
    ],
    "Reverse-Proxy": [
        "BASE_PATH=/docsight",
        "REVERSE_PROXY_PREFIX=1",
        "proxy_set_header X-Forwarded-Prefix /docsight;",
        "### Container healthcheck",
        "### Platform wrappers and authentication",
    ],
    "Feature-Matrix": [
        "## Intentionally out of scope",
        "| Legal guarantee |",
        "| Managed cloud monitoring |",
        "Data stays on the user's own machine unless they export or share it.",
    ],
    "Proof-Pack": [
        "## Public screenshot safety checklist",
        "`Example Cable Provider`",
        "docs/samples/demo-complaint-report.pdf",
    ],
    "Community-Proof-Templates": [
        "## Modem compatibility report",
        "Do not post raw HAR captures publicly.",
    ],
    "Developer-Testing": [
        "tests/test_docsis_case_fixtures.py",
        "`previous_raw`",
        "FAST3896-15_PYUR-RDK_83.2.4",
        "--modules both",
        "not a controlled cold OS/SQLite-cache benchmark",
    ],
}

# Internal planning notes were removed, not published.
INTERNAL_ONLY_PHRASES = [
    "Shot list for future assets",
    "public surface follow-up issues",
    "public directory submission notes",
    "claim-safe copy",
]


@pytest.fixture(scope="module")
def wiki_dir() -> Path:
    configured = os.environ.get("DOCSIGHT_WIKI_DIR", "").strip()
    if not configured:
        message = "set DOCSIGHT_WIKI_DIR to a checkout of https://github.com/itsDNNS/docsight.wiki.git"
        if os.environ.get("CI"):
            pytest.fail(f"{message}; the Wiki checks are required in CI")
        pytest.skip(message)
    path = Path(configured).expanduser().resolve()
    if not (path / "Home.md").is_file():
        pytest.fail(f"DOCSIGHT_WIKI_DIR does not contain a Wiki checkout: {path}")
    return path


def heading_anchors(text: str) -> set[str]:
    """Anchors GitHub generates for Markdown and inline HTML headings."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line) or re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", line)
        if not match:
            continue
        title = re.sub(r"`([^`]*)`", r"\1", match.group(1))
        title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\- ]", "", title.strip().lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def repository_text_files():
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIPPED_DIRS]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix in SCANNED_SUFFIXES:
                yield path


def wiki_link_problems(text: str, wiki: Path) -> list[str]:
    problems = []
    for match in WIKI_LINK_RE.finditer(text):
        page, anchor = match.group("page"), match.group("anchor")
        if not page:
            continue
        page_file = wiki / f"{page}.md"
        if not page_file.is_file():
            problems.append(f"missing page {page}")
        elif anchor and anchor not in heading_anchors(page_file.read_text(encoding="utf-8")):
            problems.append(f"missing heading {page}#{anchor}")
    return problems


def test_repository_links_to_existing_wiki_pages_and_headings(wiki_dir: Path) -> None:
    problems = []
    for path in repository_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for problem in wiki_link_problems(text, wiki_dir):
            problems.append(f"{path.relative_to(ROOT).as_posix()}: {problem}")
    assert problems == []


def test_desktop_preview_link_points_to_the_wiki_page(wiki_dir: Path) -> None:
    from app.web import DESKTOP_PREVIEW_DOC_URL

    assert DESKTOP_PREVIEW_DOC_URL == f"{WIKI_URL}/Windows-Desktop-Preview"
    assert wiki_link_problems(DESKTOP_PREVIEW_DOC_URL, wiki_dir) == []


@pytest.mark.parametrize("page", sorted(MIGRATED_CONTENT))
def test_migrated_documentation_keeps_its_content_in_the_wiki(wiki_dir: Path, page: str) -> None:
    page_file = wiki_dir / f"{page}.md"
    assert page_file.is_file(), f"missing Wiki page {page}"
    text = page_file.read_text(encoding="utf-8")
    missing = [snippet for snippet in MIGRATED_CONTENT[page] if snippet not in text]
    assert missing == []


def test_internal_planning_notes_are_not_published(wiki_dir: Path) -> None:
    leaked = [
        f"{path.name}: {phrase}"
        for path in sorted(wiki_dir.glob("*.md"))
        for phrase in INTERNAL_ONLY_PHRASES
        if phrase.lower() in path.read_text(encoding="utf-8").lower()
    ]
    assert leaked == []


def test_wiki_pages_contain_no_reusable_secret_examples(wiki_dir: Path) -> None:
    """Same reusable-secret check that covered these documents while they lived in the repository."""
    pages = sorted(wiki_dir.glob("*.md"))
    assert pages
    found = [
        f"{path.name}: {pattern.pattern}"
        for path in pages
        for pattern in SECRET_PATTERNS
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []


def test_architecture_page_names_existing_code_paths(wiki_dir: Path) -> None:
    text = (wiki_dir / "Architecture.md").read_text(encoding="utf-8")
    paths = re.findall(r"`((?:app|tests|scripts|tools)/[\w./-]+)`", text)
    assert paths
    assert [path for path in paths if not (ROOT / path.rstrip("/")).exists()] == []


def test_public_positioning_page_has_no_private_or_localhost_values(wiki_dir: Path) -> None:
    text = (wiki_dir / "Feature-Matrix.md").read_text(encoding="utf-8")
    assert not PRIVATE_VALUE_RE.search(text)


def test_repository_files_referenced_by_the_wiki_exist(wiki_dir: Path) -> None:
    missing = sorted(
        f"{path.name}: {match.group('path')}"
        for path in wiki_dir.glob("*.md")
        for match in REPO_FILE_LINK_RE.finditer(path.read_text(encoding="utf-8"))
        if not (ROOT / match.group("path").rstrip("/.")).exists()
    )
    assert missing == []
