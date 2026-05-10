#!/usr/bin/env python3
"""Generate demo-safe marketing proof-pack assets.

The generated assets use synthetic DOCSIS data only. They are intended for README,
launch posts, and support docs where real ISP names, IP addresses, customer data,
or live modem values should never appear.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.modules.reports.report as report_module

SCREENSHOT_PATH = ROOT / "docs" / "screenshots" / "bad-day-evidence.png"
SAMPLE_REPORT_PATH = ROOT / "docs" / "samples" / "demo-complaint-report.pdf"


Color = tuple[int, int, int]


BG: Color = (11, 18, 32)
PANEL: Color = (18, 27, 46)
PANEL_2: Color = (23, 35, 59)
BORDER: Color = (45, 63, 95)
TEXT: Color = (226, 232, 240)
MUTED: Color = (148, 163, 184)
GREEN: Color = (34, 197, 94)
YELLOW: Color = (245, 158, 11)
RED: Color = (239, 68, 68)
BLUE: Color = (59, 130, 246)
CYAN: Color = (34, 211, 238)
PURPLE: Color = (168, 85, 247)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/local/share/fonts") / name,
        Path("/Library/Fonts") / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def make_channel(channel_id: int, *, snr: float, power: float, health: str, uncorrectable: int) -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        "frequency": f"{450 + channel_id * 8} MHz",
        "power": round(power, 1),
        "snr": snr,
        "modulation": "256QAM",
        "correctable_errors": uncorrectable * 8 + channel_id * 13,
        "uncorrectable_errors": uncorrectable,
        "health": health,
    }


def make_us_channel(channel_id: int, *, power: float, health: str) -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        "frequency": f"{30 + channel_id * 6} MHz",
        "power": round(power, 1),
        "modulation": "64QAM" if health == "good" else "16QAM",
        "multiplex": "ATDMA",
        "health": health,
    }


def build_demo_series() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    start = datetime(2026, 4, 20, 0, 0, 0)
    snapshots: list[dict[str, Any]] = []

    for i in range(10 * 8):
        ts = start + timedelta(hours=i * 3)
        evening = 19 <= ts.hour <= 23
        bad_day = ts.day in {22, 23, 27, 28, 29}
        outage_window = bad_day and evening

        if outage_window:
            health = "critical"
            snr = 25.8 + (i % 3) * 0.4
            ds_power = -8.7 + (i % 4) * 0.3
            us_power = 56.2 + (i % 2) * 0.6
            uncorr = 24000 + i * 211
            issues = ["snr_critical", "us_power_critical_high"]
        elif bad_day:
            health = "tolerated"
            snr = 31.4 + (i % 3) * 0.5
            ds_power = -5.6 + (i % 4) * 0.2
            us_power = 50.5 + (i % 2) * 0.4
            uncorr = 1800 + i * 31
            issues = ["snr_low"]
        else:
            health = "good"
            snr = 38.5 + (i % 5) * 0.2
            ds_power = -0.8 + (i % 6) * 0.2
            us_power = 44.5 + (i % 4) * 0.3
            uncorr = 0 if i % 4 else 5
            issues = []

        ds_channels = [
            make_channel(1, snr=snr + 2.1, power=ds_power + 0.5, health=health, uncorrectable=uncorr // 4),
            make_channel(2, snr=snr, power=ds_power, health=health, uncorrectable=uncorr),
            make_channel(3, snr=snr + 1.2, power=ds_power + 0.9, health=health, uncorrectable=uncorr // 2),
        ]
        us_channels = [
            make_us_channel(1, power=us_power - 1.2, health="tolerated" if outage_window else "good"),
            make_us_channel(2, power=us_power, health="critical" if outage_window else health),
        ]
        summary = {
            "ds_total": len(ds_channels),
            "us_total": len(us_channels),
            "ds_power_min": round(min(ch["power"] for ch in ds_channels), 1),
            "ds_power_max": round(max(ch["power"] for ch in ds_channels), 1),
            "ds_power_avg": round(sum(ch["power"] for ch in ds_channels) / len(ds_channels), 1),
            "us_power_min": round(min(ch["power"] for ch in us_channels), 1),
            "us_power_max": round(max(ch["power"] for ch in us_channels), 1),
            "us_power_avg": round(sum(ch["power"] for ch in us_channels) / len(us_channels), 1),
            "ds_snr_min": round(min(ch["snr"] for ch in ds_channels), 1),
            "ds_snr_avg": round(sum(ch["snr"] for ch in ds_channels) / len(ds_channels), 1),
            "ds_correctable_errors": uncorr * 8,
            "ds_uncorrectable_errors": uncorr,
            "errors_supported": True,
            "health": health,
            "health_issues": issues,
        }
        snapshots.append(
            {
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "summary": summary,
                "ds_channels": ds_channels,
                "us_channels": us_channels,
            }
        )

    current_analysis = {
        "summary": snapshots[-1]["summary"],
        "ds_channels": snapshots[-1]["ds_channels"],
        "us_channels": snapshots[-1]["us_channels"],
    }

    def period_slice(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        end_dt = datetime.fromisoformat(end_iso.replace("Z", ""))
        return [
            snap for snap in snapshots
            if start_dt <= datetime.fromisoformat(snap["timestamp"]) <= end_dt
        ]

    def health_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
        result: dict[str, int] = {}
        for snap in items:
            health = snap["summary"].get("health", "unknown")
            result[health] = result.get(health, 0) + 1
        return result

    def avg(items: list[dict[str, Any]], key: str) -> float:
        return sum(float(snap["summary"].get(key, 0) or 0) for snap in items) / max(len(items), 1)

    period_a_from = "2026-04-20T00:00:00Z"
    period_a_to = "2026-04-21T23:59:00Z"
    period_b_from = "2026-04-27T00:00:00Z"
    period_b_to = "2026-04-29T23:59:00Z"
    period_a = period_slice(period_a_from, period_a_to)
    period_b = period_slice(period_b_from, period_b_to)

    comparison_data = {
        "period_a": {
            "from": period_a_from,
            "to": period_a_to,
            "snapshots": len(period_a),
            "health_distribution": health_distribution(period_a),
        },
        "period_b": {
            "from": period_b_from,
            "to": period_b_to,
            "snapshots": len(period_b),
            "health_distribution": health_distribution(period_b),
        },
        "delta": {
            "ds_power": round(avg(period_b, "ds_power_avg") - avg(period_a, "ds_power_avg"), 2),
            "ds_snr": round(avg(period_b, "ds_snr_avg") - avg(period_a, "ds_snr_avg"), 2),
            "us_power": round(avg(period_b, "us_power_avg") - avg(period_a, "us_power_avg"), 2),
            "uncorr_errors": int(
                max(snap["summary"].get("ds_uncorrectable_errors") or 0 for snap in period_b)
                - max(snap["summary"].get("ds_uncorrectable_errors") or 0 for snap in period_a)
            ),
            "verdict": "degraded",
        },
    }
    return snapshots, current_analysis, comparison_data


class FixedReportDateTime(datetime):
    """Fixed timestamp for reproducible marketing report assets."""

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001 - matches datetime.now signature
        value = cls(2026, 4, 29, 21, 30, tzinfo=timezone.utc)
        if tz is not None:
            return value.astimezone(tz)
        return value


def generate_sample_report() -> None:
    snapshots, current_analysis, comparison_data = build_demo_series()
    SAMPLE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    original_datetime = report_module.datetime
    original_init = report_module.IncidentReport.__init__

    def fixed_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.set_creation_date(FixedReportDateTime.now())

    try:
        report_module.datetime = FixedReportDateTime
        report_module.IncidentReport.__init__ = fixed_init
        pdf = report_module.generate_report(
            snapshots,
            current_analysis,
            config={"isp_name": "Example Cable Provider", "modem_type": "Demo DOCSIS Gateway"},
            connection_info={"max_downstream_kbps": 1000000, "max_upstream_kbps": 50000},
            lang="en",
            comparison_data=comparison_data,
        )
    finally:
        report_module.datetime = original_datetime
        report_module.IncidentReport.__init__ = original_init
    SAMPLE_REPORT_PATH.write_bytes(pdf)


def rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], radius: int, fill: Color, outline: Color | None = None) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=1 if outline else 0)


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, color: Color = TEXT, *, bold: bool = False) -> None:
    draw.text(xy, text, fill=color, font=font(size, bold=bold))


def draw_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str, value: str, note: str, color: Color) -> None:
    rounded_rect(draw, (x, y, x + w, y + h), 20, PANEL, BORDER)
    draw_text(draw, (x + 22, y + 18), title, 22, MUTED, bold=True)
    draw_text(draw, (x + 22, y + 52), value, 42, color, bold=True)
    draw_text(draw, (x + 22, y + 105), note, 20, MUTED)


def draw_line_chart(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    values: list[float],
    min_v: float,
    max_v: float,
    color: Color,
    label: str,
) -> None:
    x1, y1, x2, y2 = box
    points: list[tuple[int, int]] = []
    span = max(max_v - min_v, 1)
    for idx, value in enumerate(values):
        x = int(x1 + idx * (x2 - x1) / (len(values) - 1))
        y = int(y2 - ((value - min_v) / span) * (y2 - y1))
        points.append((x, y))
    draw.line(points, fill=color, width=4, joint="curve")


def generate_bad_day_screenshot() -> None:
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1600, 900), BG)
    draw = ImageDraw.Draw(img)

    # Sidebar and header
    rounded_rect(draw, (28, 28, 300, 872), 28, (8, 14, 26), BORDER)
    draw_text(draw, (62, 58), "DOCSight", 36, TEXT, bold=True)
    draw_text(draw, (62, 104), "Demo evidence mode", 20, MUTED)
    for idx, item in enumerate(["Dashboard", "Correlation", "Events", "Journal", "Reports"]):
        y = 175 + idx * 64
        fill = PANEL_2 if item == "Correlation" else (8, 14, 26)
        rounded_rect(draw, (52, y, 276, y + 44), 14, fill, BORDER if item == "Correlation" else fill)
        draw_text(draw, (76, y + 10), item, 21, TEXT if item == "Correlation" else MUTED, bold=item == "Correlation")
    draw_text(draw, (62, 790), "All values are synthetic", 18, MUTED)
    draw_text(draw, (62, 818), "No real ISP or customer data", 18, MUTED)

    draw_text(draw, (340, 46), "Bad evening evidence timeline", 42, TEXT, bold=True)
    draw_text(draw, (342, 98), "Cable/DOCSIS signal, speed, packet loss, events, and notes on one demo-safe timeline", 22, MUTED)

    # Status cards
    draw_card(draw, 340, 150, 285, 148, "Connection health", "CRITICAL", "5 critical windows", RED)
    draw_card(draw, 650, 150, 250, 148, "Lowest SNR", "25.8 dB", "below 29 dB threshold", RED)
    draw_card(draw, 925, 150, 250, 148, "Upstream power", "56.8", "dBmV peak", YELLOW)
    draw_card(draw, 1200, 150, 335, 148, "Evidence package", "Ready", "report, notes, before/after", GREEN)

    # Chart area
    rounded_rect(draw, (340, 330, 1535, 685), 24, PANEL, BORDER)
    draw_text(draw, (370, 358), "Cross-source correlation", 28, TEXT, bold=True)
    draw_text(draw, (370, 397), "A speed dip lines up with signal degradation, packet loss, and modem events", 20, MUTED)
    draw_text(draw, (1180, 397), "Normalized overlay", 18, MUTED)

    legend = [(CYAN, "SNR dB"), (BLUE, "Download Mbps"), (RED, "Packet loss %")]
    for idx, (color, label) in enumerate(legend):
        lx = 1165 + idx * 122
        ly = 362
        draw.line((lx, ly + 12, lx + 28, ly + 12), fill=color, width=4)
        draw_text(draw, (lx + 36, ly), label, 16, TEXT)

    # Grid
    gx1, gy1, gx2, gy2 = 390, 465, 1485, 630
    for i in range(5):
        y = gy1 + i * (gy2 - gy1) // 4
        draw.line((gx1, y, gx2, y), fill=(32, 45, 70), width=1)
    for i, day in enumerate(["Apr 24", "Apr 25", "Apr 26", "Apr 27", "Apr 28", "Apr 29"]):
        x = gx1 + i * (gx2 - gx1) // 5
        draw.line((x, gy1, x, gy2), fill=(32, 45, 70), width=1)
        draw_text(draw, (x - 25, gy2 + 16), day, 17, MUTED)

    snr = [39, 38, 38, 37, 34, 31, 26, 27, 30, 32, 28, 26, 31, 37]
    speed = [940, 930, 910, 895, 760, 610, 180, 220, 480, 650, 260, 190, 520, 900]
    loss = [0, 0, 0, 0, 1, 3, 12, 9, 4, 2, 8, 15, 3, 0]
    draw_line_chart(draw, (gx1, gy1 + 15, gx2, gy2 - 20), snr, 20, 42, CYAN, "SNR")
    draw_line_chart(draw, (gx1, gy1 + 20, gx2, gy2 - 35), [v / 25 for v in speed], 0, 42, BLUE, "Download")
    draw_line_chart(draw, (gx1, gy1 + 25, gx2, gy2 - 30), [v * 2.1 for v in loss], 0, 42, RED, "Packet loss")

    # Incident window band and markers
    incident_x1 = gx1 + 6 * (gx2 - gx1) // 13
    incident_x2 = gx1 + 11 * (gx2 - gx1) // 13
    draw.rounded_rectangle((incident_x1, gy1, incident_x2, gy2), radius=10, outline=(127, 29, 29), width=3)
    draw_text(draw, (incident_x1 + 20, gy1 + 14), "degraded evenings", 18, RED, bold=True)
    for x, label in [(incident_x1 + 30, "event"), (incident_x1 + 230, "journal"), (incident_x2 - 120, "report")]:
        draw.ellipse((x, gy1 - 8, x + 20, gy1 + 12), fill=RED)
        draw_text(draw, (x - 12, gy1 - 34), label, 16, TEXT)

    # Evidence cards
    cards = [
        (340, 710, "Event log", "SNR dropped below threshold at 20:14. Upstream power rose above tolerated range."),
        (745, 710, "Incident journal", "User note: video calls unstable and gaming packet loss visible during the same window."),
        (1150, 710, "ISP-ready report", "Includes worst values, before/after comparison, timeline, and complaint text."),
    ]
    for x, y, title, body in cards:
        rounded_rect(draw, (x, y, x + 385, y + 142), 18, PANEL, BORDER)
        draw_text(draw, (x + 22, y + 18), title, 24, TEXT, bold=True)
        # Simple wrapping
        words = body.split()
        line = ""
        yy = y + 58
        for word in words:
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font(17)) > 325:
                draw_text(draw, (x + 22, yy), line, 17, MUTED)
                yy += 24
                line = word
            else:
                line = candidate
        if line:
            draw_text(draw, (x + 22, yy), line, 17, MUTED)

    img.save(SCREENSHOT_PATH, optimize=True)


if __name__ == "__main__":
    generate_sample_report()
    generate_bad_day_screenshot()
    print(f"wrote {SAMPLE_REPORT_PATH.relative_to(ROOT)}")
    print(f"wrote {SCREENSHOT_PATH.relative_to(ROOT)}")
