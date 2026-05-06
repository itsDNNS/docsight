"""Static UI/CSS contract tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_CSS = ROOT / "app" / "static" / "css" / "views.css"


def test_correlation_timeline_sticky_header_uses_opaque_surface():
    css = VIEWS_CSS.read_text(encoding="utf-8")
    header_block = css[css.index("#correlation-table thead th") : css.index("#correlation-table tbody tr")]

    assert "position: sticky" in header_block
    assert "background: var(--card-bg" in header_block
    assert "rgba(0,0,0,0.15)" not in header_block
    assert "z-index: 3" in header_block
