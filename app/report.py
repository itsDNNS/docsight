"""Incident Report PDF generator for DOCSight."""

import io
import logging
from datetime import datetime

from fpdf import FPDF

log = logging.getLogger("docsis.report")

# DIN thresholds for reference in reports
THRESHOLDS = {
    "ds_power": {"good": "±7 dBmV", "warn": "±10 dBmV", "ref": "EN 50083-7, IEC 60728-1-2"},
    "us_power": {"good": "35–49 dBmV", "warn": "50–54 dBmV", "ref": "DOCSIS 3.0/3.1 PHY Spec"},
    "snr": {"good": ">30 dB", "warn": "25–30 dB", "ref": "DOCSIS 3.0/3.1 PHY Spec"},
}


class IncidentReport(FPDF):
    """Custom PDF class for DOCSight incident reports."""

    def __init__(self, lang="en"):
        super().__init__()
        self.lang = lang
        self.add_font("dejavu", "", "/usr/share/fonts/TTF/DejaVuSans.ttf")
        self.add_font("dejavu", "B", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")
        self.add_font("dejavu", "I", "/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf")
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_font("dejavu", "B", 16)
        self.cell(0, 10, "DOCSight Incident Report", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("dejavu", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_text_color(0, 0, 0)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("dejavu", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"DOCSight Incident Report — Page {self.page_no()}/{{nb}}", align="C")

    def _section_title(self, title):
        self.set_font("dejavu", "B", 13)
        self.set_fill_color(41, 128, 185)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def _key_value(self, key, value, bold_value=False):
        self.set_font("dejavu", "", 10)
        self.cell(60, 6, key + ":", new_x="RIGHT")
        self.set_font("dejavu", "B" if bold_value else "", 10)
        self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")

    def _health_color(self, health):
        if health == "good":
            return (39, 174, 96)
        elif health == "marginal":
            return (243, 156, 18)
        return (231, 76, 60)

    def _table_header(self, cols, widths):
        self.set_font("dejavu", "B", 9)
        self.set_fill_color(220, 220, 220)
        for col, w in zip(cols, widths):
            self.cell(w, 6, col, border=1, fill=True, align="C")
        self.ln()

    def _table_row(self, cells, widths, health=None):
        self.set_font("dejavu", "", 8)
        if health:
            r, g, b = self._health_color(health)
            self.set_text_color(r, g, b)
        for cell, w in zip(cells, widths):
            self.cell(w, 5, str(cell), border=1, align="C")
        self.set_text_color(0, 0, 0)
        self.ln()


def _compute_worst_values(snapshots):
    """Compute worst values across all snapshots in the range."""
    worst = {
        "ds_power_max": 0,
        "ds_power_min": 0,
        "us_power_max": 0,
        "ds_snr_min": 999,
        "ds_uncorrectable_max": 0,
        "ds_correctable_max": 0,
        "health_poor_count": 0,
        "health_marginal_count": 0,
        "total_snapshots": len(snapshots),
    }
    for snap in snapshots:
        s = snap["summary"]
        if abs(s.get("ds_power_max", 0)) > abs(worst["ds_power_max"]):
            worst["ds_power_max"] = s.get("ds_power_max", 0)
        if abs(s.get("ds_power_min", 0)) > abs(worst["ds_power_min"]):
            worst["ds_power_min"] = s.get("ds_power_min", 0)
        if s.get("us_power_max", 0) > worst["us_power_max"]:
            worst["us_power_max"] = s.get("us_power_max", 0)
        if s.get("ds_snr_min", 999) < worst["ds_snr_min"]:
            worst["ds_snr_min"] = s.get("ds_snr_min", 999)
        if s.get("ds_uncorrectable_errors", 0) > worst["ds_uncorrectable_max"]:
            worst["ds_uncorrectable_max"] = s.get("ds_uncorrectable_errors", 0)
        if s.get("ds_correctable_errors", 0) > worst["ds_correctable_max"]:
            worst["ds_correctable_max"] = s.get("ds_correctable_errors", 0)
        health = s.get("health", "good")
        if health == "poor":
            worst["health_poor_count"] += 1
        elif health == "marginal":
            worst["health_marginal_count"] += 1
    return worst


def _find_worst_channels(snapshots):
    """Find channels that were most frequently in bad health."""
    ds_issues = {}
    us_issues = {}
    for snap in snapshots:
        for ch in snap.get("ds_channels", []):
            cid = ch.get("channel_id", 0)
            if ch.get("health") != "good":
                ds_issues[cid] = ds_issues.get(cid, 0) + 1
        for ch in snap.get("us_channels", []):
            cid = ch.get("channel_id", 0)
            if ch.get("health") != "good":
                us_issues[cid] = us_issues.get(cid, 0) + 1
    ds_sorted = sorted(ds_issues.items(), key=lambda x: x[1], reverse=True)[:5]
    us_sorted = sorted(us_issues.items(), key=lambda x: x[1], reverse=True)[:5]
    return ds_sorted, us_sorted


def generate_report(snapshots, current_analysis, config=None, connection_info=None, lang="en"):
    """Generate a PDF incident report.

    Args:
        snapshots: List of snapshot dicts from storage.get_range_data()
        current_analysis: Current live analysis dict
        config: Config dict (isp_name, etc.)
        connection_info: Connection info dict (speeds, etc.)
        lang: Language code

    Returns:
        bytes: PDF file content
    """
    config = config or {}
    connection_info = connection_info or {}
    pdf = IncidentReport(lang=lang)
    pdf.alias_nb_pages()
    pdf.add_page()

    # --- Connection Info ---
    pdf._section_title("Connection Information")
    isp = config.get("isp_name", "Unknown ISP")
    pdf._key_value("ISP", isp)
    ds_mbps = connection_info.get("max_downstream_kbps", 0) // 1000 if connection_info.get("max_downstream_kbps") else "N/A"
    us_mbps = connection_info.get("max_upstream_kbps", 0) // 1000 if connection_info.get("max_upstream_kbps") else "N/A"
    pdf._key_value("Tariff", f"{ds_mbps} / {us_mbps} Mbit/s (Down / Up)")
    device = config.get("modem_type", connection_info.get("device_name", "Unknown"))
    pdf._key_value("Modem", device)

    if snapshots:
        start = snapshots[0]["timestamp"]
        end = snapshots[-1]["timestamp"]
        pdf._key_value("Report Period", f"{start}  to  {end}")
        pdf._key_value("Data Points", str(len(snapshots)))
    pdf.ln(3)

    # --- Current Status ---
    pdf._section_title("Current Status")
    if current_analysis:
        s = current_analysis["summary"]
        health = s.get("health", "unknown")
        pdf.set_font("dejavu", "B", 12)
        r, g, b = pdf._health_color(health)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, f"Connection Health: {health.upper()}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if s.get("health_issues"):
            pdf.set_font("dejavu", "", 10)
            pdf.cell(0, 6, f"Issues: {', '.join(s['health_issues'])}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Current channel table
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, "Downstream Channels", new_x="LMARGIN", new_y="NEXT")
        cols = ["CH", "Freq", "Power", "SNR", "Mod", "Corr Err", "Uncorr Err", "Health"]
        widths = [12, 25, 20, 18, 22, 25, 25, 20]
        pdf._table_header(cols, widths)
        for ch in current_analysis.get("ds_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                ch.get("frequency", "")[:10],
                f"{ch.get('power', 0):.1f}",
                f"{ch.get('snr', 0):.1f}" if ch.get("snr") else "—",
                str(ch.get("modulation", ""))[:10],
                f"{ch.get('correctable_errors', 0):,}",
                f"{ch.get('uncorrectable_errors', 0):,}",
                ch.get("health", ""),
            ], widths, health=ch.get("health"))

        pdf.ln(3)
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, "Upstream Channels", new_x="LMARGIN", new_y="NEXT")
        cols_us = ["CH", "Freq", "Power", "Mod", "Multiplex", "Health"]
        widths_us = [15, 30, 25, 30, 35, 25]
        pdf._table_header(cols_us, widths_us)
        for ch in current_analysis.get("us_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                ch.get("frequency", "")[:12],
                f"{ch.get('power', 0):.1f}",
                str(ch.get("modulation", ""))[:12],
                str(ch.get("multiplex", ""))[:15],
                ch.get("health", ""),
            ], widths_us, health=ch.get("health"))

    # --- Historical Analysis ---
    if snapshots:
        pdf.add_page()
        pdf._section_title("Historical Analysis")
        worst = _compute_worst_values(snapshots)

        pdf._key_value("Total Measurements", str(worst["total_snapshots"]))
        pdf._key_value("Measurements with POOR health", str(worst["health_poor_count"]), bold_value=True)
        pdf._key_value("Measurements with MARGINAL health", str(worst["health_marginal_count"]))
        pdf.ln(2)

        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, "Worst Recorded Values", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dejavu", "", 10)

        pdf._key_value("DS Power (worst max)", f"{worst['ds_power_max']} dBmV (threshold: {THRESHOLDS['ds_power']['warn']})")
        pdf._key_value("US Power (worst max)", f"{worst['us_power_max']} dBmV (threshold: {THRESHOLDS['us_power']['warn']})")
        pdf._key_value("DS SNR (worst min)", f"{worst['ds_snr_min']} dB (threshold: {THRESHOLDS['snr']['warn']})")
        pdf._key_value("Uncorrectable Errors (max)", f"{worst['ds_uncorrectable_max']:,}")
        pdf._key_value("Correctable Errors (max)", f"{worst['ds_correctable_max']:,}")
        pdf.ln(3)

        # Worst channels
        ds_worst, us_worst = _find_worst_channels(snapshots)
        if ds_worst:
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, "Most Problematic Downstream Channels", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in ds_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  Channel {cid}: unhealthy in {count}/{len(snapshots)} measurements ({pct}%)", new_x="LMARGIN", new_y="NEXT")
        if us_worst:
            pdf.ln(2)
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, "Most Problematic Upstream Channels", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in us_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  Channel {cid}: unhealthy in {count}/{len(snapshots)} measurements ({pct}%)", new_x="LMARGIN", new_y="NEXT")

    # --- Reference Thresholds ---
    pdf.add_page()
    pdf._section_title("Reference: DOCSIS Signal Thresholds")
    pdf.set_font("dejavu", "", 9)
    cols_ref = ["Parameter", "Good", "Warning", "Reference"]
    widths_ref = [45, 35, 35, 55]
    pdf._table_header(cols_ref, widths_ref)
    for param, vals in THRESHOLDS.items():
        label = param.replace("_", " ").title()
        pdf._table_row([label, vals["good"], vals["warn"], vals["ref"]], widths_ref)
    pdf.ln(5)

    # --- ISP Complaint Template ---
    pdf._section_title("ISP Complaint Template")
    pdf.set_font("dejavu", "", 9)

    if snapshots:
        worst = _compute_worst_values(snapshots)
        start = snapshots[0]["timestamp"][:10]
        end = snapshots[-1]["timestamp"][:10]
        complaint = (
            f"Subject: Persistent DOCSIS Signal Quality Issues — Request for Technical Inspection\n\n"
            f"Dear {isp} Technical Support,\n\n"
            f"I am writing to formally document ongoing signal quality issues with my cable internet connection. "
            f"Using automated monitoring (DOCSight), I have collected {len(snapshots)} measurements "
            f"between {start} and {end}.\n\n"
            f"Key findings:\n"
            f"- Connection rated POOR in {worst['health_poor_count']} of {worst['total_snapshots']} measurements "
            f"({round(worst['health_poor_count']/max(worst['total_snapshots'],1)*100)}%)\n"
            f"- Worst downstream power: {worst['ds_power_max']} dBmV (threshold: {THRESHOLDS['ds_power']['warn']})\n"
            f"- Worst upstream power: {worst['us_power_max']} dBmV (threshold: {THRESHOLDS['us_power']['warn']})\n"
            f"- Worst downstream SNR: {worst['ds_snr_min']} dB (threshold: {THRESHOLDS['snr']['warn']})\n"
            f"- Peak uncorrectable errors: {worst['ds_uncorrectable_max']:,}\n\n"
            f"These values exceed the acceptable ranges defined in the DOCSIS specification and indicate "
            f"physical layer issues that require on-site investigation.\n\n"
            f"I request:\n"
            f"1. A qualified technician visit to inspect the coaxial infrastructure\n"
            f"2. Signal level measurements at the tap and at my premises\n"
            f"3. Written documentation of findings and corrective actions\n\n"
            f"The full monitoring data is attached to this report. I reserve the right to escalate this matter "
            f"to the Bundesnetzagentur (Federal Network Agency) if the issue is not resolved within a reasonable timeframe.\n\n"
            f"Sincerely,\n[Your Name]\n[Customer Number]\n[Address]"
        )
    else:
        complaint = (
            "Subject: DOCSIS Signal Quality Issues\n\n"
            "Dear Technical Support,\n\n"
            "I am experiencing persistent signal quality issues with my cable internet connection. "
            "Please see the attached monitoring data for details.\n\n"
            "Sincerely,\n[Your Name]"
        )

    pdf.multi_cell(0, 4, complaint)

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
