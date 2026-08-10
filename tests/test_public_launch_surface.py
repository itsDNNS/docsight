"""Static contracts for the DOCSight public landing surface."""

from __future__ import annotations

import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
README = ROOT / "README.md"
DATA_CONTRACT = ROOT / "DATA_CONTRACT.md"
UNLINKED_PUBLIC_IMAGES = [
    DOCS / "docsight.png",
    DOCS / "screenshots" / "setup.png",
    DOCS / "screenshots" / "smart-capture-settings.png",
    DOCS / "screenshots" / "readme-hero-evidence.png",
]
LOCAL_PUBLIC_ASSET_RE = re.compile(
    r"(?<![\w/-])(?:docs/)?(?:screenshots/|samples/)?[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp|svg|pdf)"
)


class LandingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta: dict[tuple[str, str], str] = {}
        self.canonical = ""
        self.links: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            if "name" in data and "content" in data:
                self.meta[("name", data["name"])] = data["content"]
            if "property" in data and "content" in data:
                self.meta[("property", data["property"])] = data["content"]
        if tag == "link" and data.get("rel") == "canonical":
            self.canonical = data.get("href", "")
        if tag == "a" and data.get("href"):
            self.links.append(data["href"])
        if tag == "img" and data.get("src"):
            self.images.append(data["src"])
        if tag == "source" and data.get("srcset"):
            self.images.append(data["srcset"].split()[0])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def parse_landing() -> LandingParser:
    parser = LandingParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
        length = struct.unpack(">I", fh.read(4))[0]
        assert fh.read(4) == b"IHDR"
        width, height = struct.unpack(">II", fh.read(8))
        assert length == 13
        return width, height


def test_landing_page_has_required_canonical_and_social_metadata() -> None:
    parser = parse_landing()

    assert parser.title.strip()
    assert parser.meta[("name", "description")]
    assert parser.canonical == "https://itsdnns.github.io/docsight/"
    assert parser.meta[("property", "og:type")] == "website"
    assert parser.meta[("property", "og:site_name")] == "DOCSight"
    assert parser.meta[("property", "og:title")].strip()
    assert parser.meta[("property", "og:description")].strip()
    assert parser.meta[("property", "og:url")] == parser.canonical
    og_image = parser.meta[("property", "og:image")]
    assert og_image.startswith(parser.canonical)
    assert (DOCS / urlparse(og_image).path.removeprefix("/docsight/")).is_file()
    assert parser.meta[("name", "twitter:card")] == "summary_large_image"
    assert parser.meta[("name", "twitter:title")].strip()
    assert parser.meta[("name", "twitter:description")].strip()
    assert parser.meta[("name", "twitter:image")] == og_image


def test_landing_page_references_only_existing_local_assets() -> None:
    parser = parse_landing()

    for src in parser.images:
        if urlparse(src).scheme:
            continue
        assert (DOCS / src).exists(), src
    for href in parser.links:
        parsed = urlparse(href)
        if parsed.scheme or href.startswith("#") or href.startswith("mailto:"):
            continue
        assert (DOCS / href.split("#", 1)[0]).exists(), href


def test_public_surface_docs_and_social_asset_exist() -> None:
    expected = [
        DATA_CONTRACT,
        DOCS / "index.html",
        DOCS / "feature-matrix.md",
        DOCS / "self-hosted-directory-submission.md",
        DOCS / "public-launch-follow-up-issues.md",
        DOCS / "proof-pack.md",
        DOCS / "samples" / "demo-complaint-report.pdf",
        DOCS / "screenshots" / "bad-day-evidence.png",
        DOCS / "screenshots" / "dashboard-hero.png",
        DOCS / "screenshots" / "social-preview.png",
    ]
    for path in expected:
        assert path.exists(), path
        assert path.stat().st_size > 0, path

    width, height = png_size(DOCS / "screenshots" / "social-preview.png")
    assert width >= 1200
    assert height >= 630
    width, height = png_size(DOCS / "screenshots" / "dashboard-hero.png")
    assert width >= 1600
    assert height >= 900


def test_public_docs_reference_existing_local_assets_without_unlinked_images() -> None:
    public_docs = [README, *sorted(DOCS.rglob("*.md")), *sorted(DOCS.rglob("*.html"))]

    missing = []
    for source in public_docs:
        for ref in sorted(set(LOCAL_PUBLIC_ASSET_RE.findall(source.read_text(encoding="utf-8")))):
            asset = ROOT / ref if ref.startswith("docs/") else DOCS / ref
            if not asset.exists():
                missing.append(f"{source.relative_to(ROOT)} -> {ref}")

    assert missing == []
    assert [path.relative_to(ROOT).as_posix() for path in UNLINKED_PUBLIC_IMAGES if path.exists()] == []


def test_no_private_or_localhost_values_in_public_surface() -> None:
    paths = [INDEX, DOCS / "feature-matrix.md", DOCS / "self-hosted-directory-submission.md"]
    pattern = re.compile(r"(localhost|127\.0\.0\.1|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.|Vodafone Kabel)", re.I)
    for path in paths:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_public_modem_family_counts_match_registry() -> None:
    from app.drivers import driver_registry

    family_count = len(driver_registry.get_all_type_keys() - {"generic"})
    claim = f"{family_count} modem families"
    assert claim in README.read_text(encoding="utf-8")
    assert claim in INDEX.read_text(encoding="utf-8")
