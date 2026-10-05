"""Comparison side of scripts/visual_review.py (capturing needs a browser)."""

import importlib.util
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("visual_review", ROOT / "scripts" / "visual_review.py")
visual_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visual_review)

PROPS = visual_review.STYLE_PROPERTIES


def _style(**overrides):
    values = dict.fromkeys(PROPS, "0px")
    values.update(overrides)
    return [values[name] for name in PROPS]


def _write(directory, name, image, view=None, shell=None):
    directory.mkdir(parents=True, exist_ok=True)
    image.save(directory / f"{name}.png")
    (directory / f"{name}.json").write_text(json.dumps({"view": view or {}, "shell": shell or {}}))


def test_identical_renderings_report_no_changes(tmp_path):
    for side in ("base", "head"):
        _write(tmp_path / side, "events--dark--desktop", Image.new("RGB", (40, 40), "black"),
               view={"#view-events": _style(color="rgb(1, 2, 3)")})
    summary = visual_review.compare(tmp_path / "base", tmp_path / "head", tmp_path / "diff")
    assert "1 renderings compared, 1 without visible or style changes." in summary
    assert "|" not in summary
    assert not list((tmp_path / "diff").glob("*.diff.png"))


def test_changed_pixels_and_styles_are_listed_with_examples(tmp_path):
    before = Image.new("RGB", (40, 40), "black")
    after = before.copy()
    after.paste((255, 255, 255), (0, 0, 10, 10))  # 100 of 1600 pixels
    _write(tmp_path / "base", "live--light--mobile", before,
           view={"#view-dashboard>button:1": _style(**{"padding-left": "20px"})})
    _write(tmp_path / "head", "live--light--mobile", after,
           view={"#view-dashboard>button:1": _style(**{"padding-left": "22px"}), "#new": _style()})

    summary = visual_review.compare(tmp_path / "base", tmp_path / "head", tmp_path / "diff")

    assert "`live--light--mobile` | 6.25% | 1 changed, 1 added, 0 removed" in summary
    assert "#view-dashboard>button:1 padding-left: 20px -> 22px" in summary
    assert (tmp_path / "diff" / "live--light--mobile.diff.png").exists()


def test_height_changes_and_missing_views_are_reported(tmp_path):
    _write(tmp_path / "base", "events--dark--desktop", Image.new("RGB", (40, 40)))
    _write(tmp_path / "head", "events--dark--desktop", Image.new("RGB", (40, 60)))
    _write(tmp_path / "base", "bqm--dark--desktop", Image.new("RGB", (40, 40)))
    _write(tmp_path / "head", "journal--dark--desktop", Image.new("RGB", (40, 40)))

    summary = visual_review.compare(tmp_path / "base", tmp_path / "head", tmp_path / "diff")

    assert "(height 40 -> 60 px)" in summary
    assert "`bqm--dark--desktop` | view removed" in summary
    assert "`journal--dark--desktop` | new view" in summary


def test_small_differences_below_the_channel_tolerance_are_ignored(tmp_path):
    before = Image.new("RGB", (20, 20), (100, 100, 100))
    after = Image.new("RGB", (20, 20), (100 + visual_review.PIXEL_TOLERANCE, 100, 100))
    result = visual_review._pixel_diff(_save(tmp_path, "a", before), _save(tmp_path, "b", after), tmp_path / "d.png")
    assert result["changed_ratio"] == 0


def _save(directory, name, image):
    path = directory / f"{name}.png"
    image.save(path)
    return path
