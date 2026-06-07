"""Data retrieval routes: trends, export, snapshots."""
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

from app.time_ranges import parse_time_range_hours
from app.web import (
    require_auth,
    get_storage, get_config_manager, get_state,
    _localize_timestamps,
)

log = logging.getLogger("docsis.web")

_ISSUE_LABELS = {
    "ds_power_critical": "Downstream power out of spec",
    "ds_power_marginal": "Downstream power approaching limits",
    "ds_power_tolerated": "Downstream power slightly out of spec",
    "us_power_critical_low": "Upstream power critically low",
    "us_power_critical_high": "Upstream power critically high",
    "us_power_marginal_low": "Upstream power below acceptable",
    "us_power_marginal_high": "Upstream power elevated",
    "us_power_tolerated_low": "Upstream power slightly low",
    "us_power_tolerated_high": "Upstream power slightly high",
    "snr_critical": "Signal-to-noise ratio critically low",
    "snr_marginal": "Signal-to-noise ratio below acceptable",
    "snr_tolerated": "Signal-to-noise ratio slightly below ideal",
    "us_modulation_critical": "Upstream modulation critically degraded",
    "us_modulation_marginal": "Upstream modulation degraded",
    "uncorr_errors_high": "High uncorrectable errors",
    "uncorr_errors_critical": "Uncorrectable error rate critical",
}


def _translate_issue(key: str) -> str:
    return _ISSUE_LABELS.get(key, key.replace("_", " ").title())


def _summary_error_count(summary, key):
    """Return a DOCSIS error counter only when the summary supports it."""
    if summary.get("errors_supported") is False:
        return None
    return summary.get(key)


def _format_error_count(value) -> str:
    """Format DOCSIS error counters while preserving unsupported/null as N/A."""
    return f"{value:,}" if value is not None else "N/A"


data_bp = Blueprint("data_bp", __name__)


def _append_connection_monitor_trends(data: list[dict], hours: int) -> None:
    """Add Connection Monitor latency samples for home-card sparklines.

    The dashboard sparkline renderer consumes /api/trends generically via
    data-spark-key. DOCSIS snapshots and Speedtest rows already flow through
    SnapshotStorage; Connection Monitor uses its own module database, so expose
    a lightweight latency series here without coupling the card to a second
    request path.
    """
    cfg = get_config_manager()
    data_dir = getattr(cfg, "data_dir", None)
    if not data_dir:
        return

    db_path = os.path.join(data_dir, "connection_monitor.db")
    if not os.path.exists(db_path):
        return

    try:
        from app.modules.connection_monitor.storage import ConnectionMonitorStorage

        storage = ConnectionMonitorStorage(db_path)
        enabled_targets = [t for t in storage.get_targets() if t.get("enabled")]
        if not enabled_targets:
            return

        # Home-card sparklines only need the short rolling windows used by the
        # dashboard. Longer trend views use the module's dedicated chart APIs.
        if hours > 24:
            return

        start_ts = datetime.now(timezone.utc).timestamp() - hours * 3600
        buckets: dict[int, list[float]] = defaultdict(list)
        for target in enabled_targets:
            samples = [
                sample for sample in storage.get_samples(target["id"], start=start_ts, limit=0)
                if not sample.get("timeout") and sample.get("latency_ms") is not None
            ]
            for sample in samples:
                bucket = int(sample["timestamp"] // 60) * 60
                buckets[bucket].append(float(sample["latency_ms"]))

        aggregated = sorted(
            (bucket, sum(values) / len(values))
            for bucket, values in buckets.items()
            if values
        )
        if len(aggregated) > 288:
            step = max(1, (len(aggregated) + 287) // 288)
            aggregated = aggregated[::step]
        for bucket, latency_ms in aggregated:
            data.append({
                "timestamp": datetime.fromtimestamp(bucket, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "connection_monitor",
                "connection_monitor_latency_ms": latency_ms,
            })
    except Exception:
        log.debug("Unable to append Connection Monitor trend data", exc_info=True)


def _append_speedtest_trends(data: list[dict], db_path: str, hours: int) -> None:
    """Add Speedtest download/upload rows for dashboard sparklines."""
    try:
        from app.modules.speedtest.storage import SpeedtestStorage

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        storage = SpeedtestStorage(db_path)
        for row in storage.get_speedtest_in_range(
            start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ):
            data.append({
                "timestamp": row["timestamp"],
                "source": "speedtest",
                "speedtest_download": row.get("download_mbps"),
                "speedtest_upload": row.get("upload_mbps"),
            })
    except Exception:
        log.debug("Unable to append Speedtest trend data", exc_info=True)


@data_bp.route("/api/trends")
@require_auth
def api_trends():
    """Return trend data for a normalized time range.

    Supports the normalized UI ranges (1h, 6h, 1d, 2d, 3d, 7d, 30d, 90d)
    plus the legacy day/week/month names for backwards compatibility.
    The date query parameter anchors only legacy day/week/month requests;
    normalized ranges are rolling windows ending at the current snapshot time.
    """
    _storage = get_storage()
    if not _storage:
        return jsonify([])
    range_type = (request.args.get("range", "1d") or "1d").strip().lower()
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    hours = parse_time_range_hours(range_type, default="1d", allow_legacy=True)
    if hours is None:
        return jsonify({"error": "Invalid range (use 1h, 6h, 1d, 2d, 3d, 7d, 30d, 90d)"}), 400

    ref_date = datetime.now()
    if range_type in ("day", "week", "month"):
        try:
            ref_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date format"}), 400

    if range_type == "day":
        data = _storage.get_intraday_data(date_str)
    elif range_type == "week":
        start = (ref_date - timedelta(days=6)).strftime("%Y-%m-%d")
        data = _storage.get_summary_range(start, date_str)
    elif range_type == "month":
        start = (ref_date - timedelta(days=29)).strftime("%Y-%m-%d")
        data = _storage.get_summary_range(start, date_str)
    else:
        data = _storage.get_summary_since(hours)
        _append_speedtest_trends(data, _storage.db_path, hours)
        _append_connection_monitor_trends(data, hours)
        data.sort(key=lambda row: row.get("timestamp") or "")
    _localize_timestamps(data)
    return jsonify(data)


@data_bp.route("/api/export")
@require_auth
def api_export():
    """Generate a structured markdown report for LLM analysis."""
    _storage = get_storage()
    _config_manager = get_config_manager()
    state = get_state()
    analysis = state.get("analysis")
    if not analysis:
        return jsonify({"error": "No data available"}), 404

    mode = request.args.get("mode", "full")
    if mode not in ("full", "update"):
        mode = "full"

    s = analysis["summary"]
    ds = analysis["ds_channels"]
    us = analysis["us_channels"]
    ts = state.get("last_update", "unknown")

    isp = _config_manager.get("isp_name", "") if _config_manager else ""
    conn = state.get("connection_info") or {}
    ds_mbps = conn.get("max_downstream_kbps", 0) // 1000 if conn else 0
    us_mbps = conn.get("max_upstream_kbps", 0) // 1000 if conn else 0

    lines = [
        "# DOCSight – DOCSIS Cable Connection Status Report",
        "",
        "## Context",
        "This is a status report from a DOCSIS cable modem generated by DOCSight.",
        "DOCSIS (Data Over Cable Service Interface Specification) is the standard for internet over coaxial cable.",
        "Analyze this data and provide insights about connection health, problematic channels, and recommendations.",
        f"- **Export Mode**: {'Full Context (48h)' if mode == 'full' else 'Update (6h)'}",
        "",
        "## Overview",
        f"- **ISP**: {isp}" if isp else None,
        f"- **Tariff**: {ds_mbps}/{us_mbps} Mbit/s (Down/Up)" if ds_mbps else None,
        f"- **Health**: {s.get('health', 'Unknown')}",
        f"- **Issues**: {', '.join(_translate_issue(i) for i in s.get('health_issues', []))}" if s.get('health_issues') else None,
        f"- **Timestamp**: {ts}",
        "",
        "## Summary",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Downstream Channels | {s.get('ds_total', 0)} |",
        f"| DS Power (Min/Avg/Max) | {s.get('ds_power_min')} / {s.get('ds_power_avg')} / {s.get('ds_power_max')} dBmV |",
        f"| DS SNR (Min/Avg) | {s.get('ds_snr_min')} / {s.get('ds_snr_avg')} dB |",
        f"| DS Correctable Errors | {_format_error_count(_summary_error_count(s, 'ds_correctable_errors'))} |",
        f"| DS Uncorrectable Errors | {_format_error_count(_summary_error_count(s, 'ds_uncorrectable_errors'))} |",
        f"| Upstream Channels | {s.get('us_total', 0)} |",
        f"| US Power (Min/Avg/Max) | {s.get('us_power_min')} / {s.get('us_power_avg')} / {s.get('us_power_max')} dBmV |",
        "",
        "## Downstream Channels",
        "| Ch | Frequency | Power (dBmV) | SNR (dB) | Modulation | Corr. Errors | Uncorr. Errors | DOCSIS | Health |",
        "|----|-----------|-------------|----------|------------|-------------|---------------|--------|--------|",
    ]
    for ch in ds:
        corr = ch.get("correctable_errors")
        uncorr = ch.get("uncorrectable_errors")
        err_corr = f"{corr:,}" if corr is not None else "-"
        err_uncorr = f"{uncorr:,}" if uncorr is not None else "-"
        lines.append(
            f"| {ch.get('channel_id','')} | {ch.get('frequency','')} | {ch.get('power','')} "
            f"| {ch.get('snr', '-')} | {ch.get('modulation','')} "
            f"| {err_corr} | {err_uncorr} "
            f"| {ch.get('docsis_version','')} | {ch.get('health','')} |"
        )
    lines += [
        "",
        "## Upstream Channels",
        "| Ch | Frequency | Power (dBmV) | Modulation | Multiplex | DOCSIS | Health |",
        "|----|-----------|-------------|------------|-----------|--------|--------|",
    ]
    for ch in us:
        lines.append(
            f"| {ch.get('channel_id','')} | {ch.get('frequency','')} | {ch.get('power','')} "
            f"| {ch.get('modulation','')} | {ch.get('multiplex','')} "
            f"| {ch.get('docsis_version','')} | {ch.get('health','')} |"
        )

    # ── Historical context (events, speedtests, incidents) ──
    if _storage:
        if mode == "full":
            event_hours, speedtest_limit = 48, 10
        else:
            event_hours, speedtest_limit = 6, 3

        events = _storage.get_recent_events(hours=event_hours)
        if events:
            lines += [
                "",
                f"## Events (Last {event_hours}h)",
                "| Timestamp | Severity | Type | Message |",
                "|-----------|----------|------|---------|",
            ]
            for ev in events:
                lines.append(
                    f"| {ev['timestamp']} | {ev['severity']} | {ev['event_type']} | {ev['message']} |"
                )

        speedtests = []
        try:
            from app.modules.speedtest.storage import SpeedtestStorage
            _ss = SpeedtestStorage(_storage.db_path)
            speedtests = _ss.get_recent_speedtests(limit=speedtest_limit)
        except (ImportError, Exception):
            pass
        if speedtests:
            lines += [
                "",
                f"## Speedtest Results (Last {speedtest_limit})",
                "| Timestamp | Download | Upload | Ping | Jitter | Packet Loss |",
                "|-----------|----------|--------|------|--------|-------------|",
            ]
            for st in speedtests:
                lines.append(
                    f"| {st['timestamp']} | {st.get('download_human', '')} | {st.get('upload_human', '')} "
                    f"| {st.get('ping_ms', '-')} ms | {st.get('jitter_ms', '-')} ms "
                    f"| {st.get('packet_loss_pct', '-')}% |"
                )

        if mode == "full":
            try:
                from app.modules.journal.storage import JournalStorage
                _js = JournalStorage(_storage.db_path)
                entries = _js.get_active_entries()
            except (ImportError, Exception):
                entries = []
            if entries:
                lines += ["", "## Incident Journal"]
                for inc in entries:
                    lines.append(f"### [{inc['date']}] {inc['title']}")
                    if inc.get("description"):
                        lines.append(inc["description"])
                    lines.append("")

        # ── Cross-source correlation ──
        if speedtests:
            corr_lines = []
            for st in speedtests:
                snap = _storage.get_closest_snapshot(st["timestamp"])
                if snap:
                    ss = snap["summary"]
                    corr_lines.append(
                        f"| {st['timestamp'][:16]} | {st.get('download_human', '')} "
                        f"| {ss.get('health', '')} | {ss.get('ds_snr_min', '')} dB "
                        f"| {ss.get('ds_power_avg', '')} dBmV "
                        f"| {_format_error_count(_summary_error_count(ss, 'ds_uncorrectable_errors'))} |"
                    )
            if corr_lines:
                lines += [
                    "",
                    "## Cross-Source Correlation",
                    "Speedtest performance correlated with modem signal health at the time of each test.",
                    "",
                    "| Speedtest Time | Download | Modem Health | DS SNR Min | DS Power Avg | Uncorr. Errors |",
                    "|---------------|----------|-------------|------------|-------------|----------------|",
                ]
                lines.extend(corr_lines)

    # ── Dynamic reference values from active threshold profile ──
    from app import analyzer as _analyzer
    _thresh = _analyzer.get_thresholds()

    _meta = _analyzer._t().get("_meta", {})
    profile_name = _meta.get("operator", "Active Profile")

    lines += ["", f"## Reference Values ({profile_name})", ""]

    lines += [
        "### Downstream Power (dBmV)",
        "| Modulation | Good | Tolerated | Critical |",
        "|------------|------|-----------|----------|",
    ]
    _ds = _thresh.get("downstream_power", {})
    for mod in sorted(k for k in _ds if not k.startswith("_")):
        t = _ds[mod]
        g = t.get("good", [0, 0])
        w = t.get("warning", [0, 0])
        c = t.get("critical", [0, 0])
        lines.append(f"| {mod} | {g[0]} to {g[1]} | {w[0]} to {w[1]} | < {c[0]} or > {c[1]} |")

    lines += [
        "",
        "### Upstream Power (dBmV)",
        "| Channel Type | Good | Tolerated | Critical |",
        "|-------------|------|-----------|----------|",
    ]
    _us = _thresh.get("upstream_power", {})
    for key in sorted(k for k in _us if not k.startswith("_")):
        t = _us[key]
        g = t.get("good", [0, 0])
        w = t.get("warning", [0, 0])
        c = t.get("critical", [0, 0])
        lines.append(f"| {key} | {g[0]} to {g[1]} | {w[0]} to {w[1]} | < {c[0]} or > {c[1]} |")

    lines += [
        "",
        "### SNR / MER (dB, absolute)",
        "| Modulation | Good | Tolerated | Critical |",
        "|------------|------|-----------|----------|",
    ]
    _snr = _thresh.get("snr", {})
    for mod in sorted(k for k in _snr if not k.startswith("_")):
        t = _snr[mod]
        lines.append(
            f"| {mod} "
            f"| >= {t.get('good_min', 0)} "
            f"| >= {t.get('warning_min', 0)} "
            f"| < {t.get('critical_min', 0)} |"
        )

    _err = _thresh.get("errors", {}).get("uncorrectable_pct")
    if _err:
        lines.append("")
        lines.append(f"**Uncorrectable Errors**: Tolerated >= {_err.get('warning', 1.0)}%, Critical >= {_err.get('critical', 3.0)}%")

    lines.append("")

    lines += [
        "## Questions",
        "Please analyze this data and provide:",
        "1. Overall connection health assessment",
        "2. Channels that need attention (with reasons)",
        "3. Error rate analysis and whether it indicates a problem",
        "4. Specific recommendations to improve connection quality",
    ]
    return jsonify({"text": "\n".join(line for line in lines if line is not None)})


@data_bp.route("/api/snapshots")
@require_auth
def api_snapshots():
    """Return list of available snapshot timestamps."""
    _storage = get_storage()
    if _storage:
        return jsonify(_storage.get_snapshot_list())
    return jsonify([])


@data_bp.route("/api/snapshots/<path:timestamp>")
@require_auth
def api_snapshot(timestamp):
    """Return full analysis for a specific snapshot."""
    _storage = get_storage()
    if not _storage:
        return jsonify({"error": "No storage"}), 500
    snap = _storage.get_snapshot(timestamp)
    if not snap:
        return jsonify({"error": "Snapshot not found"}), 404
    return jsonify(snap)
