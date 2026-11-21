"""Incident Report PDF generator for DOCSight."""

import io
import json
import logging
import os
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import ResourceAccessPolicy

from app.aggregation import (
    ThresholdContext,
    Window,
    aggregate_snapshot_period,
    canonical_utc_timestamp,
    report_bounds,
    select_preferred_bnetz,
)
from app.analyzer import (
    active_threshold_profile,
    get_thresholds,
    resolve_ds_power_thresholds,
    resolve_snr_thresholds,
    resolve_us_power_thresholds,
    threshold_snapshot,
)
from app.docsis_utils import to_float
from app.error_counters import to_counter
from app.i18n import get_translations

log = logging.getLogger("docsis.report")

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")


def _threshold_reference():
    """Return the short table label and upstream value sources of the active profile."""
    profile = active_threshold_profile()
    sources = profile["meta"].get("upstream_power_sources")
    return profile["short_name"] or "-", sources if isinstance(sources, dict) else {}


def _has_convention(sources):
    """Whether the profile marks any value of a row as a DOCSight convention."""
    return isinstance(sources, dict) and any(
        isinstance(value, dict) and value.get("source") == "convention"
        for value in sources.values()
    )


def _format_threshold_table():
    """Build display-ready threshold rows from the active analyzer profile."""
    t = get_thresholds()
    reference, us_sources = _threshold_reference()
    rows = []
    # DS Power - per modulation
    ds = t.get("downstream_power", {})
    for mod in sorted(k for k in ds if not k.startswith("_")):
        v = ds[mod]
        g = v.get("good", [0, 0])
        # Without a warning band the analyzer tolerates only the good band.
        w = v.get("warning", g)
        c = v.get("critical", [0, 0])
        rows.append({
            "category": "DS Power",
            "variant": mod,
            "good": f"{g[0]} to {g[1]} dBmV",
            "tolerated": f"{w[0]} to {w[1]} dBmV",
            "critical": f"{c[0]} to {c[1]} dBmV",
            "ref": reference,
            "convention": False,
        })
    # US Power - per channel type. Low upstream power is rated at most
    # marginal, so only the maximum is a critical bound. Low OFDMA power is
    # not rated, so its lower bound is the plausible minimum of the analyzer.
    us = t.get("upstream_power", {})
    for key in sorted(k for k in us if not k.startswith("_")):
        v = us[key]
        g = v.get("good", [0, 0])
        w = v.get("warning", g)
        c = v.get("critical", [0, 0])
        rated = resolve_us_power_thresholds("OFDMA" if key == "ofdma" else None, thresholds=t)
        good_min = g[0] if rated["rate_low"] else rated["plausible_min"]
        warn_min = w[0] if rated["rate_low"] else rated["plausible_min"]
        convention = _has_convention(us_sources.get(key))
        rows.append({
            "category": "US Power",
            "variant": key,
            "good": f"{good_min} to {g[1]} dBmV",
            "tolerated": f"{warn_min} to {w[1]} dBmV",
            "critical": f"<= {c[1]} dBmV",
            "ref": f"{reference} *" if convention else reference,
            "convention": convention,
        })
    # SNR - per modulation
    snr = t.get("snr", {})
    for mod in sorted(k for k in snr if not k.startswith("_")):
        v = snr[mod]
        rows.append({
            "category": "SNR/MER",
            "variant": mod,
            "good": f">= {v.get('good_min', 0)} dB",
            "tolerated": f">= {v.get('warning_min', v.get('good_min', 0))} dB",
            "critical": f">= {v.get('critical_min', 0)} dB",
            "ref": reference,
            "convention": False,
        })
    # US Modulation - QAM order health
    us_mod = t.get("upstream_modulation", {})
    warn_qam = us_mod.get("warning_max_qam")
    crit_qam = us_mod.get("critical_max_qam")
    if warn_qam is not None and crit_qam is not None:
        rows.append({
            "category": "US Modulation",
            "variant": "QAM Order",
            "good": f"> {warn_qam}-QAM",
            "tolerated": f"<= {warn_qam}-QAM",
            "critical": f"<= {crit_qam}-QAM",
            "ref": reference,
            "convention": False,
        })
    return rows


def _warning_bands():
    """Warning bands the analyzer applies to 256QAM downstream and SC-QAM upstream."""
    raw = threshold_snapshot()["thresholds"]
    ds = resolve_ds_power_thresholds("256QAM", thresholds=raw)
    us = resolve_us_power_thresholds(thresholds=raw)
    return {
        "ds_power": (ds["warn_min"], ds["warn_max"]),
        "us_power": (us["warn_min"], us["warn_max"]),
        "snr": resolve_snr_thresholds("256QAM", thresholds=raw)["warn_min"],
    }


def _default_warn_thresholds(ds_snr_warn_min=None):
    """Get default warning thresholds as display strings for report."""
    bands = _warning_bands()
    ds_w, us_w = bands["ds_power"], bands["us_power"]
    return {
        "ds_power": f"{ds_w[0]} to {ds_w[1]} dBmV",
        "us_power": f"{us_w[0]} to {us_w[1]} dBmV",
        "snr": f">= {ds_snr_warn_min if ds_snr_warn_min is not None else bands['snr']} dB",
    }


def _worst_ds_power(worst):
    """Quote the low downstream extreme only when it lies further out of range.

    Upstream power keeps its maximum: low upstream power on its own is rated
    at most marginal and usually harmless, so it is no complaint finding.
    """
    high, low = worst["ds_power_max"], worst.get("ds_power_min")
    high_value, low_value = to_float(high), to_float(low)
    if low_value is None:
        return high
    if high_value is None:
        return low
    band = _warning_bands()["ds_power"]
    if band[0] - low_value > max(high_value - band[1], 0):
        return low
    return high


def _format_diagnostic_note(note, s):
    if "spec_max" in note:
        key = "diag_note_high"
    elif "spec_min" in note:
        key = "diag_note_snr_low" if note["type"] == "snr_low" else "diag_note_low"
    else:
        key = "diag_note_stored_critical_high" if note["type"].endswith("_high") else "diag_note_stored_critical_low"
    diagnostic = s[key].format(
        ch=note["channel_id"],
        ch_type=note["channel_type"],
        metric=note["metric"],
        value=note["value"],
        unit="dB" if note["type"] == "snr_low" else "dBmV",
        spec=note.get("spec_max", note.get("spec_min")),
        pct=note.get("deviation_pct"),
    )
    observed = s["diagnostic_observed_at"].format(observed_at=note["observed_at"])
    return f"{diagnostic} {observed}"


def _format_diagnostic_complaint(notes, s):
    """Format diagnostic notes as complaint letter text section."""
    if not notes:
        return ""
    lines = [s["complaint_diag_header"]]
    for note in notes:
        text = _format_diagnostic_note(note, s)
        if text:
            lines.append("- " + text)
    if any(n.get("severity") == "extreme" for n in notes):
        lines.append("")
        lines.append(s["diag_note_isp_hint"])
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Localised strings for PDF reports
# ---------------------------------------------------------------------------
_REPORT_I18N_DIR = os.path.join(os.path.dirname(__file__), "i18n")


def _load_report_strings():
    if not os.path.isdir(_REPORT_I18N_DIR):
        raise RuntimeError(f"Report i18n directory missing: {_REPORT_I18N_DIR}")

    strings = {}
    for fname in sorted(os.listdir(_REPORT_I18N_DIR)):
        if not fname.endswith(".json") or fname == "template.json":
            continue

        lang = fname[:-5]
        fpath = os.path.join(_REPORT_I18N_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            if lang == "en":
                raise RuntimeError(f"Failed to load required report i18n file {fpath}") from exc
            log.warning("Failed to load optional report i18n file %s: %s", fpath, exc)
            continue

        if not isinstance(data, dict):
            if lang == "en":
                raise RuntimeError(f"Required report i18n file {fpath} does not contain a JSON object")
            log.warning("Skipping non-object report i18n payload in %s", fpath)
            continue

        strings[lang] = {
            key: value for key, value in data.items()
            if not str(key).startswith("_")
        }

    if "en" not in strings:
        raise RuntimeError("Report i18n requires app/modules/reports/i18n/en.json")

    return strings


REPORT_STRINGS = _load_report_strings()


def _get_report_strings(lang="en"):
    strings = dict(REPORT_STRINGS["en"])
    if lang != "en":
        strings.update(REPORT_STRINGS.get(lang, {}))
    core = get_translations(lang)
    strings.update({key: core[key] for key in ("bnetz_verdict_ok", "bnetz_verdict_deviation")})
    return strings


class IncidentReport(FPDF):
    """Custom PDF class for DOCSight incident reports."""

    def __init__(self, lang="en"):
        super().__init__()
        self.lang = lang
        self._s = _get_report_strings(lang)
        # Attachments come from users and integrations: never let an image,
        # such as an SVG <image>, load server files or URLs.
        self.resource_access_policy = ResourceAccessPolicy.NONE
        self.add_font("dejavu", "", os.path.join(_FONT_DIR, "DejaVuSans.ttf"))
        self.add_font("dejavu", "B", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"))
        self.add_font("dejavu", "I", os.path.join(_FONT_DIR, "DejaVuSans-Oblique.ttf"))
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        s = self._s
        self.set_font("dejavu", "B", 16)
        self.cell(0, 10, s["report_title"], new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("dejavu", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, f"{s['generated']} {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_text_color(0, 0, 0)
        self.ln(5)

    def footer(self):
        s = self._s
        self.set_y(-15)
        self.set_font("dejavu", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"{s['footer']} - {s['page']} {self.page_no()}/{{nb}}", align="C")

    def _section_title(self, title):
        self.set_font("dejavu", "B", 13)
        self.set_fill_color(41, 128, 185)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def _key_value(self, key, value, bold_value=False):
        self.set_font("dejavu", "", 10)
        key_text = key + ":"
        key_w = max(65, self.get_string_width(key_text) + 4)
        self.cell(key_w, 6, key_text, new_x="RIGHT")
        self.set_font("dejavu", "B" if bold_value else "", 10)
        self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")

    def _health_color(self, health):
        if health == "good":
            return (39, 174, 96)
        elif health == "tolerated":
            return (132, 204, 22)
        elif health in ("marginal", "warning"):  # channels say "warning"
            return (243, 156, 18)
        return (231, 76, 60)

    def _table_header(self, cols, widths):
        self.set_font("dejavu", "B", 9)
        self.set_fill_color(220, 220, 220)
        for col, w in zip(cols, widths):
            self.cell(w, 6, col, border=1, fill=True, align="C")
        self.ln()

    def _fit_text(self, text, width, suffix=""):
        """Shorten text with an ellipsis so it and its suffix fit a table cell."""
        self.set_font("dejavu", "", 8)
        if self.get_string_width(text + suffix) <= width:
            return text + suffix
        while text and self.get_string_width(text + "…" + suffix) > width:
            text = text[:-1]
        return text.rstrip() + "…" + suffix

    def _table_row(self, cells, widths, health=None):
        self.set_font("dejavu", "", 8)
        if health:
            r, g, b = self._health_color(health)
            self.set_text_color(r, g, b)
        for cell, w in zip(cells, widths):
            self.cell(w, 5, str(cell), border=1, align="C")
        self.set_text_color(0, 0, 0)
        self.ln()


def _format_optional_count(value):
    """Format a counter value while preserving unsupported/null/unreadable as N/A."""
    return f"{count:,}" if (count := to_counter(value)) is not None else "N/A"


def _format_optional_decimal(value):
    """Format a decimal metric while preserving unavailable values."""
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "-"


def _format_optional_measurement(value):
    """Format a historical aggregate without turning missing data into zero."""
    return "N/A" if value is None else str(value)


def _aggregate_report_period(snapshots, report_start=None, report_end=None):
    requested = Window(report_start or "", report_end or "")
    start, end = report_bounds(snapshots, window=requested)
    thresholds = ThresholdContext.from_analyzer_snapshot(threshold_snapshot())
    aggregate = aggregate_snapshot_period(
        snapshots,
        window=Window(start, end),
        thresholds=thresholds,
    )
    return aggregate, start, end


def _comparison_label(s, key):
    labels = {
        "good": s["comparison_health_good"],
        "tolerated": s["comparison_health_tolerated"],
        "marginal": s["comparison_health_marginal"],
        "critical": s["comparison_health_critical"],
        "unknown": s["comparison_health_unknown"],
    }
    return labels.get(key, key.title())


def _comparison_top_health(period, s):
    dist = period.get("health_distribution") or {}
    if not dist:
        return _comparison_label(s, "unknown")
    best_key = max(dist, key=lambda name: dist.get(name, 0))
    total = max(period.get("snapshots", 0), 1)
    pct = round(dist.get(best_key, 0) / total * 100)
    return f"{_comparison_label(s, best_key)} ({pct}%)"


def _format_comparison_value(value, unit="", is_int=False):
    if value is None:
        return "-"
    if is_int:
        text = f"{int(value):,}"
    else:
        text = f"{value:+.2f}"
    return f"{text} {unit}".strip()


def _format_comparison_timestamp(ts):
    if not ts:
        return "-"
    raw = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return str(ts)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_comparison_evidence(comparison_data, s):
    if not comparison_data:
        return ""

    period_a = comparison_data.get("period_a") or {}
    period_b = comparison_data.get("period_b") or {}
    delta = comparison_data.get("delta") or {}

    lines = [
        s["comparison_complaint_header"],
        "",
        s["comparison_complaint_periods"].format(
            from_a=_format_comparison_timestamp(period_a.get("from")),
            to_a=_format_comparison_timestamp(period_a.get("to")),
            from_b=_format_comparison_timestamp(period_b.get("from")),
            to_b=_format_comparison_timestamp(period_b.get("to")),
        ),
        f"- {s['comparison_complaint_snapshots'].format(snapshots_a=period_a.get('snapshots', 0), snapshots_b=period_b.get('snapshots', 0))}",
        f"- {s['comparison_complaint_verdict'].format(verdict=s.get('comparison_verdict_' + str(delta.get('verdict', 'unchanged')), str(delta.get('verdict', 'unchanged')).title()))}",
        f"- {s['comparison_complaint_health'].format(health_a=_comparison_top_health(period_a, s), health_b=_comparison_top_health(period_b, s))}",
        f"- {s['comparison_complaint_ds_power'].format(value=_format_comparison_value(delta.get('ds_power'), 'dBmV'))}",
        f"- {s['comparison_complaint_ds_snr'].format(value=_format_comparison_value(delta.get('ds_snr'), 'dB'))}",
        f"- {s['comparison_complaint_us_power'].format(value=_format_comparison_value(delta.get('us_power'), 'dBmV'))}",
        f"- {s['comparison_complaint_uncorr'].format(value=_format_comparison_value(delta.get('uncorr_errors'), '', True))}",
        "",
    ]
    return "\n".join(lines)


def _localized_closing_placeholder(s, line_index, fallback):
    closing = s.get("complaint_closing", "")
    lines = closing.splitlines() if isinstance(closing, str) else []
    if len(lines) > line_index and lines[line_index].strip():
        return lines[line_index].strip()
    return fallback


def _format_customer_closing(s, customer_name="", customer_number="", customer_address=""):
    """Build a localized complaint closing with provided customer details."""
    label = s.get("complaint_closing_label") or _localized_closing_placeholder(s, 0, "Sincerely,")
    name = (customer_name or "").strip() or _localized_closing_placeholder(s, 1, "[Your Name]")
    number = (customer_number or "").strip() or _localized_closing_placeholder(s, 2, "[Customer Number]")
    address = (customer_address or "").strip()
    address_lines = address.splitlines() if address else [_localized_closing_placeholder(s, 3, "[Address]")]
    return "\n".join([label, name, number, *address_lines])


def _render_connection_info(pdf, s, config, connection_info):
    """Render the connection block of both PDF reports and return the ISP name."""
    config, connection_info = config or {}, connection_info or {}
    pdf._section_title(s["section_connection_info"])
    isp = config.get("isp_name", "Unknown ISP")
    pdf._key_value(s["isp"], isp)
    ds_mbps = connection_info.get("max_downstream_kbps", 0) // 1000 if connection_info.get("max_downstream_kbps") else "N/A"
    us_mbps = connection_info.get("max_upstream_kbps", 0) // 1000 if connection_info.get("max_upstream_kbps") else "N/A"
    pdf._key_value(s["tariff"], f"{ds_mbps} / {us_mbps} Mbit/s (Down / Up)")
    device = config.get("modem_type", connection_info.get("device_name", "Unknown"))
    pdf._key_value(s["modem"], device)
    return isp


def _render_historical(pdf, s, period_aggregate, total):
    """Render the historical-analysis page of both PDF reports."""
    pdf.add_page()
    pdf._section_title(s["section_historical"])
    worst = period_aggregate["worst"]

    pdf._key_value(s["total_measurements"], str(worst["total_snapshots"]))
    pdf._key_value(s["measurements_critical"], str(worst["health_critical_count"]), bold_value=True)
    pdf._key_value(s["measurements_marginal"], str(worst["health_marginal_count"]))
    pdf._key_value(s["measurements_tolerated"], str(worst["health_tolerated_count"]))
    pdf.ln(2)

    pdf.set_font("dejavu", "B", 10)
    pdf.cell(0, 6, s["worst_recorded"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("dejavu", "", 10)

    warn = _default_warn_thresholds(worst["ds_snr_warn_min"])
    worst_ds_power = _worst_ds_power(worst)
    pdf._key_value(s["ds_power_worst"], f"{_format_optional_measurement(worst_ds_power)} dBmV (threshold: {warn['ds_power']})")
    pdf._key_value(s["us_power_worst"], f"{_format_optional_measurement(worst['us_power_max'])} dBmV (threshold: {warn['us_power']})")
    pdf._key_value(s["ds_snr_worst"], f"{_format_optional_measurement(worst['ds_snr_min'])} dB (threshold: {warn['snr']})")
    pdf._key_value(s["uncorr_err_max"], _format_optional_count(worst["ds_uncorrectable_max"]))
    pdf._key_value(s["corr_err_max"], _format_optional_count(worst["ds_correctable_max"]))
    pdf.ln(3)

    for direction, key in (("ds", "worst_ds_channels"), ("us", "worst_us_channels")):
        channels = period_aggregate["worst_channels"][direction]
        if not channels:
            continue
        if direction == "us":
            pdf.ln(2)
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s[key], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dejavu", "", 9)
        for cid, count in channels:
            pct = round(count / total * 100)
            pdf.cell(0, 5, f"  {s['channel_unhealthy'].format(cid=cid, count=count, total=total, pct=pct)}", new_x="LMARGIN", new_y="NEXT")


def _complaint_request(s):
    return (
        f"{s['complaint_request']}\n"
        f"1. {s['complaint_req1']}\n"
        f"2. {s['complaint_req2']}\n"
        f"3. {s['complaint_req3']}\n\n"
    )


def _complaint_findings(s, isp, worst, count, start, end, evidence=""):
    """Complaint text from the subject through the request list, with evidence before the request."""
    warn = _default_warn_thresholds(worst["ds_snr_warn_min"])
    poor_pct = round(worst['health_critical_count'] / max(worst['total_snapshots'], 1) * 100)
    return (
        f"{s['complaint_subject']}\n\n"
        f"{s['complaint_greeting'].format(isp=isp)}\n\n"
        f"{s['complaint_body'].format(count=count, start=start, end=end)}\n\n"
        f"{s['complaint_findings']}\n"
        f"- {s['complaint_poor_rate'].format(poor=worst['health_critical_count'], total=worst['total_snapshots'], pct=poor_pct)}\n"
        f"- {s['complaint_ds_power'].format(val=_format_optional_measurement(_worst_ds_power(worst)), thresh=warn['ds_power'])}\n"
        f"- {s['complaint_us_power'].format(val=_format_optional_measurement(worst['us_power_max']), thresh=warn['us_power'])}\n"
        f"- {s['complaint_snr'].format(val=_format_optional_measurement(worst['ds_snr_min']), thresh=warn['snr'])}\n"
        f"- {s['complaint_uncorr'].format(val=_format_optional_count(worst['ds_uncorrectable_max']))}\n\n"
        f"{evidence}"
        f"{s['complaint_exceed']}\n\n"
        f"{_complaint_request(s)}"
    )


def _complaint_letter(s, isp, snapshots, period_aggregate, report_start, report_end, closing,
                      evidence="", bnetz_section=""):
    """Complaint letter of the period report and of the text letter."""
    if snapshots:
        diag = _format_diagnostic_complaint(period_aggregate["diagnostic_notes"], s)
        body = _complaint_findings(s, isp, period_aggregate["worst"], len(snapshots), report_start[:10],
                                   report_end[:10], diag + evidence + bnetz_section)
    else:
        greeting = s["complaint_greeting"].format(isp=isp) if bnetz_section else s["complaint_short_greeting"]
        body = (
            f"{s['report_period']}: {report_start} {s['period_to']} {report_end}\n\n"
            f"{greeting}\n\n"
            f"{s['complaint_no_docsis_data'].format(start=report_start, end=report_end)}\n\n"
        )
        if not bnetz_section:
            return body + closing
        body += bnetz_section + _complaint_request(s)
    return f"{body}{s['complaint_escalation']}\n\n{closing}"


def generate_report(
    snapshots,
    config=None,
    connection_info=None,
    lang="en",
    comparison_data=None,
    customer_name="",
    customer_number="",
    customer_address="",
    report_start=None,
    report_end=None,
):
    """Generate a PDF incident report.

    Args:
        snapshots: List of snapshot dicts from storage.get_range_data()
        config: Config dict (isp_name, etc.)
        connection_info: Connection info dict (speeds, etc.)
        lang: Language code
        comparison_data: Optional before/after comparison payload
        customer_name: Customer name for the embedded complaint letter
        customer_number: Customer/contract number for the embedded complaint letter
        customer_address: Customer address for the embedded complaint letter
        report_start: Requested inclusive report-window start in canonical UTC
        report_end: Requested inclusive report-window end in canonical UTC

    Returns:
        bytes: PDF file content
    """
    s = _get_report_strings(lang)
    period_aggregate, report_start, report_end = _aggregate_report_period(
        snapshots, report_start, report_end
    )
    latest_snapshot = period_aggregate["latest_snapshot"]
    diag_notes = period_aggregate["diagnostic_notes"]
    pdf = IncidentReport(lang=lang)
    pdf.alias_nb_pages()
    pdf.add_page()

    # --- Connection Info ---
    isp = _render_connection_info(pdf, s, config, connection_info)
    pdf._key_value(
        s["report_period"], f"{report_start}  {s['period_to']}  {report_end}"
    )
    pdf._key_value(s["data_points"], str(len(snapshots)))
    pdf.ln(3)

    # --- Latest status recorded inside the report period ---
    pdf._section_title(s["section_latest_recorded_status"])
    if latest_snapshot:
        observed_at = canonical_utc_timestamp(latest_snapshot.get("timestamp"))
        pdf._key_value(s["observed_at"], observed_at)
        sm = latest_snapshot["summary"]
        health = sm.get("health", "unknown")
        pdf.set_font("dejavu", "B", 12)
        r, g, b = pdf._health_color(health)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, f"{s['connection_health']}: {health.upper()}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if sm.get("health_issues"):
            pdf.set_font("dejavu", "", 10)
            labels = s["issue_labels"]
            translated = [labels.get(i, i) for i in sm["health_issues"]]
            pdf.multi_cell(0, 6, f"{s['issues']}: {', '.join(translated)}", align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Latest recorded channel table
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["ds_channels"], new_x="LMARGIN", new_y="NEXT")
        cols = [s["col_ch"], s["col_freq"], s["col_power"], s["col_snr"], s["col_mod"], s["col_corr_err"], s["col_uncorr_err"], s["col_health"]]
        widths = [12, 25, 20, 18, 22, 25, 25, 20]
        pdf._table_header(cols, widths)
        for ch in latest_snapshot.get("ds_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                (ch.get("frequency") or "")[:10],
                _format_optional_decimal(ch.get('power')),
                _format_optional_decimal(ch.get("snr")),
                str(ch.get("modulation") or "")[:10],
                _format_optional_count(ch.get('correctable_errors')),
                _format_optional_count(ch.get('uncorrectable_errors')),
                ch.get("health", ""),
            ], widths, health=ch.get("health"))

        pdf.ln(3)
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["us_channels"], new_x="LMARGIN", new_y="NEXT")
        cols_us = [s["col_ch"], s["col_freq"], s["col_power"], s["col_mod"], s["col_multiplex"], s["col_health"]]
        widths_us = [15, 30, 25, 30, 35, 25]
        pdf._table_header(cols_us, widths_us)
        for ch in latest_snapshot.get("us_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                (ch.get("frequency") or "")[:12],
                _format_optional_decimal(ch.get('power')),
                str(ch.get("modulation") or "")[:12],
                str(ch.get("multiplex") or "")[:15],
                ch.get("health", ""),
            ], widths_us, health=ch.get("health"))

    else:
        pdf.set_font("dejavu", "", 10)
        pdf.multi_cell(
            0,
            6,
            s["no_docsis_data"],
            new_x="LMARGIN",
            new_y="NEXT",
        )

    # --- Diagnostic Notes ---
    if diag_notes:
        pdf.ln(4)
        pdf._section_title(s["section_diagnostic_notes"])
        pdf.set_font("dejavu", "", 9)
        for note in diag_notes:
            text = _format_diagnostic_note(note, s)
            r, g, b = pdf._health_color("critical")
            pdf.set_text_color(r, g, b)
            pdf.multi_cell(0, 4, f"  {text}", new_x="LMARGIN", new_y="NEXT")
        if any(n.get("severity") == "extreme" for n in diag_notes):
            pdf.ln(2)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("dejavu", "I", 9)
            pdf.multi_cell(0, 4, s["diag_note_isp_hint"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("dejavu", "", 10)

    comparison_section = _format_comparison_evidence(comparison_data, s)
    if comparison_section:
        pdf.ln(4)
        pdf._section_title(s["comparison_section_title"])
        pdf.set_font("dejavu", "", 9)
        pdf.multi_cell(0, 4, comparison_section)
        pdf.set_font("dejavu", "", 10)

    # --- Historical Analysis ---
    if snapshots:
        _render_historical(pdf, s, period_aggregate, len(snapshots))

    # --- Reference Thresholds ---
    pdf.add_page()
    pdf._section_title(s["section_thresholds"])
    pdf.set_font("dejavu", "", 9)
    cols_ref = [s["col_parameter"], s["col_modulation"], s["col_good"], s["col_tolerated"], s["col_critical_thresh"], s["col_reference"]]
    widths_ref = [28, 28, 35, 35, 35, 25]
    pdf._table_header(cols_ref, widths_ref)
    rows_ref = _format_threshold_table()
    for row in rows_ref:
        marker = " *" if row["convention"] else ""
        ref = pdf._fit_text(row["ref"].removesuffix(marker), widths_ref[-1] - 2, marker)
        pdf._table_row([row["category"], row["variant"], row["good"], row["tolerated"], row["critical"], ref], widths_ref)
    pdf.ln(2)
    pdf.set_font("dejavu", "", 8)
    profile_label = active_threshold_profile()["label"] or "-"
    pdf.multi_cell(0, 4, s["threshold_profile_used"].format(profile=profile_label), new_x="LMARGIN", new_y="NEXT")
    if any(row["convention"] for row in rows_ref):
        pdf.multi_cell(0, 4, s["threshold_convention_note"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- ISP Complaint Template ---
    pdf._section_title(s["section_complaint"])
    pdf.set_font("dejavu", "", 9)

    closing = _format_customer_closing(s, customer_name, customer_number, customer_address)
    pdf.multi_cell(0, 4, _complaint_letter(s, isp, snapshots, period_aggregate, report_start, report_end, closing))

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


_BNETZ_COMPLAINT_KEYS = {"download": "complaint_bnetz_dl", "upload": "complaint_bnetz_ul"}


def _bnetz_ratio(m, direction):
    """Rounded contract maximum, measured average and percentage, or None when not measured."""
    avg = m.get(f"{direction}_measured_avg")
    if avg is None:
        return None
    max_ = round(m.get(f"{direction}_max_tariff") or 0)
    avg = round(avg)
    return {"max": max_, "avg": avg, "pct": round(avg / max_ * 100) if max_ else 0}


def _bnetz_verdict_line(s, m):
    """Localized download and upload verdicts of a BNetzA measurement."""
    labels = {"ok": s["bnetz_verdict_ok"], "deviation": s["bnetz_verdict_deviation"]}
    dl, ul = (labels.get(m.get(f"verdict_{direction}"), s["comparison_health_unknown"])
              for direction in _BNETZ_COMPLAINT_KEYS)
    return s["complaint_bnetz_verdict"].format(verdict_dl=dl, verdict_ul=ul)


def _bnetz_complaint_section(s, m, with_tariff):
    """BNetzA complaint section with the measured directions only; the text letter also names the tariff."""
    lines = [s["complaint_bnetz_header"], "", s["complaint_bnetz_body"].format(date=m.get("date", ""))]
    if with_tariff:
        lines += ["", f"- {s['complaint_bnetz_tariff'].format(tariff=m.get('tariff', '-'), provider=m.get('provider', '-'))}"]
    lines += [f"- {s[key].format(**ratio)}" for direction, key in _BNETZ_COMPLAINT_KEYS.items()
              if (ratio := _bnetz_ratio(m, direction))]
    lines.append(f"- {_bnetz_verdict_line(s, m)}")
    if "deviation" in (m.get("verdict_download"), m.get("verdict_upload")):
        lines += ["", s["complaint_bnetz_legal"]]
    return "\n".join(lines) + "\n\n"


def generate_incident_report(incident, entries, snapshots, speedtests, bnetz_list,
                              config=None, connection_info=None, lang="en",
                              customer_name="", customer_number="", customer_address="",
                              attachment_loader=None):
    """Generate PDF complaint report scoped to a specific incident.

    Args:
        incident: Incident dict (name, status, description, start_date, end_date)
        entries: List of journal entry dicts (with attachment_count, attachments list)
        snapshots: List of snapshot dicts from storage.get_range_data()
        speedtests: List of speedtest result dicts
        bnetz_list: List of BNetzA measurement dicts
        config: Config dict (isp_name, modem_type)
        connection_info: Connection info dict
        lang: Language code
        customer_name: Customer name for the embedded complaint letter
        customer_number: Customer/contract number for the embedded complaint letter
        customer_address: Customer address for the embedded complaint letter
        attachment_loader: Optional callable(attachment_id) -> dict with 'data', 'mime_type'

    Returns:
        bytes: PDF file content
    """
    s = _get_report_strings(lang)
    period_aggregate, _, _ = _aggregate_report_period(snapshots)
    pdf = IncidentReport(lang=lang)
    # Override the header title for incident reports
    pdf._s = dict(pdf._s)
    pdf._s["report_title"] = s["incident_report_title"]
    pdf._s["footer"] = s["incident_report_title"]
    pdf.alias_nb_pages()

    # ── Page 1: Incident Summary ──
    pdf.add_page()
    pdf._section_title(s["section_incident_summary"])

    pdf._key_value(s["incident_name"], incident.get("name", ""))
    status = incident.get("status", "open")
    pdf._key_value(s["incident_status"], status.upper(), bold_value=True)

    if incident.get("start_date"):
        start_str = incident["start_date"]
        end_str = incident.get("end_date") or ""
        period = start_str
        if end_str:
            period += f"  {s['period_to']}  {end_str}"
            try:
                d1 = datetime.strptime(start_str, "%Y-%m-%d")
                d2 = datetime.strptime(end_str, "%Y-%m-%d")
                days = (d2 - d1).days
                duration = s["incident_duration_days"].format(days=days)
            except ValueError:
                duration = ""
        else:
            period += f"  {s['period_to']}  ..."
            duration = s["incident_duration_ongoing"]
        pdf._key_value(s["incident_period"], period)
        if duration:
            pdf._key_value(s["incident_duration"], duration)

    if incident.get("description"):
        pdf.ln(2)
        pdf.set_font("dejavu", "", 10)
        pdf.multi_cell(0, 5, incident["description"])

    # Connection info
    pdf.ln(3)
    isp = _render_connection_info(pdf, s, config, connection_info)

    # ── Page 2: Signal Analysis (if snapshots available) ──
    if snapshots:
        _render_historical(pdf, s, period_aggregate, len(snapshots))

    # ── Page 3: Speedtest Results (if available) ──
    if speedtests:
        pdf.add_page()
        pdf._section_title(s["section_speedtest"])

        cols = [s["speedtest_date"], s["speedtest_download"], s["speedtest_upload"], s["speedtest_ping"], "Jitter", "Loss"]
        widths = [35, 30, 30, 25, 25, 25]
        pdf._table_header(cols, widths)

        dl_vals = []
        ul_vals = []
        for st in speedtests:
            ts = st.get("timestamp", "")[:16].replace("T", " ")
            dl = st.get("download_mbps") or st.get("download_human", "")
            ul = st.get("upload_mbps") or st.get("upload_human", "")
            ping = st["ping_ms"] if st.get("ping_ms") is not None else "-"
            jitter = st["jitter_ms"] if st.get("jitter_ms") is not None else "-"
            loss = st["packet_loss_pct"] if st.get("packet_loss_pct") is not None else "-"
            dl_display = f"{dl}" if dl else "-"
            ul_display = f"{ul}" if ul else "-"
            pdf._table_row([ts, dl_display, ul_display, str(ping), str(jitter), f"{loss}%"], widths)
            try:
                dl_vals.append(float(dl) if dl else 0)
            except (ValueError, TypeError):
                pass
            try:
                ul_vals.append(float(ul) if ul else 0)
            except (ValueError, TypeError):
                pass

        # Summary
        if dl_vals or ul_vals:
            pdf.ln(3)
            pdf.set_font("dejavu", "B", 10)
            if dl_vals:
                avg_dl = round(sum(dl_vals) / len(dl_vals), 1)
                min_dl = round(min(dl_vals), 1)
                pdf._key_value(f"{s['speedtest_avg']} {s['speedtest_download']}", f"{avg_dl} Mbit/s")
                pdf._key_value(f"{s['speedtest_min']} {s['speedtest_download']}", f"{min_dl} Mbit/s")
            if ul_vals:
                avg_ul = round(sum(ul_vals) / len(ul_vals), 1)
                min_ul = round(min(ul_vals), 1)
                pdf._key_value(f"{s['speedtest_avg']} {s['speedtest_upload']}", f"{avg_ul} Mbit/s")
                pdf._key_value(f"{s['speedtest_min']} {s['speedtest_upload']}", f"{min_ul} Mbit/s")

    # ── Page 4: BNetzA Measurements (if available) ──
    if bnetz_list:
        pdf.add_page()
        pdf._section_title(s["section_bnetz"])

        has_deviation = False
        for m in bnetz_list:
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, f"{m.get('date', '')} - {m.get('tariff', '')} ({m.get('provider', '')})", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)

            for direction in _BNETZ_COMPLAINT_KEYS:
                if ratio := _bnetz_ratio(m, direction):
                    pdf.cell(0, 5, f"  {direction.capitalize()}: {ratio['avg']} / {ratio['max']} Mbit/s ({ratio['pct']}%)",
                             new_x="LMARGIN", new_y="NEXT")

            pdf.cell(0, 5, f"  {_bnetz_verdict_line(s, m)}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            if "deviation" in (m.get("verdict_download"), m.get("verdict_upload")):
                has_deviation = True

        if has_deviation:
            pdf.ln(2)
            pdf.set_font("dejavu", "B", 9)
            pdf.set_text_color(231, 76, 60)
            pdf.multi_cell(0, 4, s["complaint_bnetz_legal"])
            pdf.set_text_color(0, 0, 0)

    # ── Page 5: Journal Entries ──
    if entries:
        pdf.add_page()
        pdf._section_title(s["section_journal"])

        for entry in entries:
            pdf.set_font("dejavu", "B", 10)
            date_str = entry.get("date", "")
            title = entry.get("title", "")
            pdf.cell(0, 6, f"{date_str}  -  {title}", new_x="LMARGIN", new_y="NEXT")

            desc = entry.get("description", "")
            if desc:
                if len(desc) > 500:
                    desc = desc[:500] + "..."
                pdf.set_font("dejavu", "", 9)
                pdf.multi_cell(0, 4, desc)

            att_count = entry.get("attachment_count", 0)
            if att_count:
                pdf.set_font("dejavu", "I", 8)
                pdf.set_text_color(128, 128, 128)
                pdf.cell(0, 4, s["journal_attachments"].format(count=att_count), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            # Embed image attachments if loader provided
            if attachment_loader and entry.get("attachments"):
                for att_meta in entry["attachments"]:
                    mime = att_meta.get("mime_type", "")
                    if mime not in ("image/jpeg", "image/png"):
                        continue
                    try:
                        att = attachment_loader(att_meta["id"])
                        if not att or len(att.get("data", b"")) > 500 * 1024:
                            continue
                        img_buf = io.BytesIO(att["data"])
                        # Check remaining page space
                        if pdf.get_y() > 220:
                            pdf.add_page()
                        pdf.image(img_buf, x=pdf.l_margin, w=min(170, pdf.epw))
                        pdf.ln(3)
                    except Exception:
                        log.warning("Failed to embed attachment %d in incident report", att_meta.get("id", 0))

            pdf.ln(3)

    # ── Last Page: Complaint Template ──
    pdf.add_page()
    pdf._section_title(s["section_complaint"])
    pdf.set_font("dejavu", "", 9)

    if snapshots:
        complaint = _complaint_findings(
            s, isp, period_aggregate["worst"], len(snapshots),
            period_aggregate["first_observed_at"][:10], period_aggregate["last_observed_at"][:10],
        )
    else:
        complaint = (
            f"{s['complaint_short_subject']}\n\n"
            f"{s['complaint_short_greeting']}\n\n"
            f"{s['complaint_short_body']}\n\n"
        )

    # Add BNetzA reference if measurements exist
    if bnetz_list:
        complaint += "\n" + _bnetz_complaint_section(s, select_preferred_bnetz(bnetz_list), with_tariff=False)

    complaint_closing = _format_customer_closing(s, customer_name, customer_number, customer_address)
    complaint += f"{s['complaint_escalation']}\n\n{complaint_closing}"

    pdf.multi_cell(0, 4, complaint)

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_complaint_text(snapshots, config=None, lang="en",
                            customer_name="", customer_number="", customer_address="",
                            bnetz_data=None, comparison_data=None,
                            report_start=None, report_end=None):
    """Generate ISP complaint letter as plain text.

    Args:
        snapshots: List of snapshot dicts
        config: Config dict (isp_name, etc.)
        lang: Language code
        customer_name: Customer name for letter
        customer_number: Customer/contract number
        customer_address: Customer address
        bnetz_data: Optional BNetzA measurement dict
        comparison_data: Optional before/after comparison payload
        report_start: Requested inclusive report-window start in canonical UTC
        report_end: Requested inclusive report-window end in canonical UTC

    Returns:
        str: Complaint letter text
    """
    s = _get_report_strings(lang)
    period_aggregate, report_start, report_end = _aggregate_report_period(
        snapshots, report_start, report_end
    )
    return _complaint_letter(
        s,
        (config or {}).get("isp_name", "Unknown ISP"),
        snapshots,
        period_aggregate,
        report_start,
        report_end,
        _format_customer_closing(s, customer_name, customer_number, customer_address),
        _format_comparison_evidence(comparison_data, s),
        _bnetz_complaint_section(s, bnetz_data, with_tariff=True) if bnetz_data else "",
    )
