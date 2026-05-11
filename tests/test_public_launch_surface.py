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


class LandingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta: dict[tuple[str, str], str] = {}
        self.links: list[str] = []
        self.images: list[str] = []
        self.h1 = ""
        self._h1_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            if "name" in data and "content" in data:
                self.meta[("name", data["name"])] = data["content"]
            if "property" in data and "content" in data:
                self.meta[("property", data["property"])] = data["content"]
        if tag == "a" and data.get("href"):
            self.links.append(data["href"])
        if tag == "img" and data.get("src"):
            self.images.append(data["src"])
        if tag == "source" and data.get("srcset"):
            self.images.append(data["srcset"].split()[0])
        if tag == "h1":
            self._h1_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._h1_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._h1_depth:
            self.h1 += data


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


def test_landing_page_has_required_social_metadata_and_ctas() -> None:
    parser = parse_landing()

    assert "DOCSight" in parser.title
    assert "Self-hosted evidence" in parser.title
    assert parser.meta[("name", "description")]
    assert parser.meta[("property", "og:title")]
    assert parser.meta[("property", "og:description")]
    assert parser.meta[("property", "og:image")].endswith("/screenshots/social-preview.png")
    assert parser.meta[("name", "twitter:card")] == "summary_large_image"
    assert "Your ISP says everything is fine" in parser.h1
    assert "DOCSight shows the timeline" in parser.h1
    assert "https://github.com/itsDNNS/docsight#option-1-try-the-demo" in parser.links
    assert "#proof" in parser.links
    assert "https://github.com/itsDNNS/docsight/wiki/Installation" in parser.links


def test_landing_page_links_to_proof_pack_notes() -> None:
    parser = parse_landing()

    assert "https://github.com/itsDNNS/docsight/blob/main/docs/proof-pack.md" in parser.links


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


def test_landing_page_public_copy_is_claim_safe() -> None:
    text = INDEX.read_text(encoding="utf-8")
    forbidden = [
        "legal proof",
        "guaranteed",
        "certified",
        "BNetzA certified",
        "Claude",
        "Codex",
        "Gemini",
        "Hermes",
        "review gate",
        "internal workflow",
        "AI-powered",
        "revolutionary",
        "—",
    ]
    for phrase in forbidden:
        assert phrase not in text


def test_readme_points_to_product_page_without_displacing_wiki() -> None:
    readme = README.read_text(encoding="utf-8")

    assert '<a href="https://itsdnns.github.io/docsight/">Product page</a>' in readme
    assert '<a href="https://github.com/itsDNNS/docsight/wiki">Wiki</a>' in readme
    assert "docs/screenshots/dashboard-hero.png" in readme
    assert "docs/screenshots/dashboard-dark.png" in readme


def test_public_surface_docs_and_social_asset_exist() -> None:
    expected = [
        DOCS / "index.html",
        DOCS / "feature-matrix.md",
        DOCS / "self-hosted-directory-submission.md",
        DOCS / "public-launch-follow-up-issues.md",
        DOCS / "proof-pack.md",
        DOCS / "samples" / "demo-complaint-report.pdf",
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


def test_proof_pack_uses_current_public_assets_and_claims() -> None:
    text = (DOCS / "proof-pack.md").read_text(encoding="utf-8")
    directory = (DOCS / "self-hosted-directory-submission.md").read_text(encoding="utf-8")

    assert "DOCSight shows the timeline" in text
    assert "docs/screenshots/social-preview.png" in text
    assert "docs/screenshots/social-preview.png" in directory
    assert "DOCSight gives you proof" not in text
    assert "readme-hero-evidence.png" not in text
    assert "readme-hero-evidence.png" not in directory


def test_feature_matrix_has_shipped_planned_and_out_of_scope_sections() -> None:
    text = (DOCS / "feature-matrix.md").read_text(encoding="utf-8")

    assert "## Shipped today" in text
    assert "## Planned or under evaluation" in text
    assert "## Intentionally out of scope" in text
    assert "Legal guarantee" in text
    assert "Managed cloud monitoring" in text


def test_directory_submission_copy_keeps_privacy_and_claim_boundaries() -> None:
    text = (DOCS / "self-hosted-directory-submission.md").read_text(encoding="utf-8")

    assert "Data stays on the user's own machine" in text
    assert "Do not claim legal proof" in text
    assert "guaranteed ISP action" in text
    assert "self-hosted" in text
    assert "docsis" in text


def test_no_private_or_localhost_values_in_public_surface() -> None:
    paths = [INDEX, DOCS / "feature-matrix.md", DOCS / "self-hosted-directory-submission.md"]
    pattern = re.compile(r"(localhost|127\.0\.0\.1|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.|Vodafone Kabel)", re.I)
    for path in paths:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_public_surface_avoids_real_provider_names_outside_setup_docs() -> None:
    paths = [README, INDEX, DOCS / "proof-pack.md", DOCS / "self-hosted-directory-submission.md"]
    pattern = re.compile(r"\b(Vodafone|Unitymedia|Telekom|Comcast|Xfinity|Spectrum|Virgin Media|Rogers|Bell)\b", re.I)
    for path in paths:
        assert not pattern.search(path.read_text(encoding="utf-8")), path
