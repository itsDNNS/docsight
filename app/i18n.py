"""Internationalization - translation strings."""

LANGUAGES = {"en": "English", "de": "Deutsch"}

EN = {
    # Navigation
    "nav": "Navigation",
    "live_dashboard": "Live Dashboard",
    "day_trend": "Day Trend",
    "week_trend": "Week Trend",
    "month_trend": "Month Trend",
    "settings": "Settings",
    "reference_values": "Reference Values",

    # Topbar
    "open_calendar": "Open calendar",
    "last_update": "Last Update",

    # Health (display labels for analyzer values Gut/Grenzwertig/Schlecht)
    "health_good": "Good",
    "health_marginal": "Marginal",
    "health_poor": "Poor",
    "health_warning": "Warning",
    "health_critical": "Critical",

    # Summary cards
    "ds_channels": "Downstream Channels",
    "us_channels": "Upstream Channels",
    "ds_power_range": "DS Power (Min / Avg / Max)",
    "ds_snr_range": "DS SNR (Min / Avg)",
    "ds_errors_label": "DS Errors (corr. / uncorr.)",
    "us_power_range": "US Power (Min / Avg / Max)",

    # Table headers
    "status": "Status",
    "channel": "Channel",
    "frequency": "Frequency",
    "power_dbmv": "Power (dBmV)",
    "snr_db": "SNR (dB)",
    "modulation": "Modulation",
    "corr": "Corr.",
    "uncorr": "Uncorr.",
    "multiplex": "Multiplex",
    "channels": "Channels",
    "downstream": "Downstream",
    "upstream": "Upstream",

    # Reference table
    "metric": "Metric",
    "good": "Good",
    "marginal": "Marg.",
    "poor": "Poor",
    "low": "low",

    # Historical
    "historical_view": "Historical View",
    "back_to_live": "Back to Live",
    "error_label": "Error",
    "waiting_msg": "Waiting for first DOCSIS query...",

    # Trends
    "no_data": "No data available for this period.",
    "trend_error": "Error loading trend data.",
    "correctable": "Correctable",
    "uncorrectable": "Uncorrectable",
    "errors": "Errors",
    "ds_power_avg": "DS Power Avg (dBmV)",
    "ds_snr_avg": "DS SNR Avg (dB)",
    "us_power_avg": "US Power Avg (dBmV)",

    # Calendar / Date
    "live": "Live",
    "day": "Day",
    "week": "Week",
    "month": "Month",
    "months": ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"],

    # Setup
    "initial_setup": "Initial Setup",
    "fritz_connection": "FritzBox Connection",
    "url": "URL",
    "username": "Username",
    "password": "Password",
    "test_connection": "Test Connection",
    "poll_interval": "Poll Interval",
    "interval_sec": "Interval (seconds)",
    "history_days": "History (days)",
    "history_hint": "How long snapshots are stored",
    "snapshot_time": "Daily Snapshot (time)",
    "snapshot_hint": "Reference time for daily comparisons and trends",
    "advanced_mqtt": "Advanced: MQTT / Home Assistant",
    "optional": "Optional",
    "mqtt_broker": "MQTT Broker",
    "mqtt_desc": "For Home Assistant integration via MQTT Auto-Discovery. Without MQTT only the web UI runs.",
    "mqtt_optional_ha": "optional - for Home Assistant",
    "username_opt": "Username (optional)",
    "password_opt": "Password (optional)",
    "topic_prefix": "Topic Prefix",
    "complete_setup": "Complete Setup",
    "testing": "Testing...",
    "connected": "Connected",
    "network_error": "Network error",
    "pw_required": "FritzBox password is required.",
    "unknown_error": "Unknown",
    "error_prefix": "Error",
    "default": "Default",

    # Settings
    "back_dashboard": "Back to Dashboard",
    "light_mode": "Light Mode",
    "dark_mode": "Dark Mode",
    "general": "General",
    "save": "Save",
    "settings_saved": "Settings saved",
    "save_failed": "Save failed",
    "saved_ph": "Saved",

    # Language
    "language": "Language",

    # ISP / Connection
    "isp_name": "Internet Provider",
    "isp_hint": "Shown in LLM export report",
    "isp_other": "Other",
    "isp_other_placeholder": "Enter provider name",
    "isp_select": "Select provider",
    "isp_options": ["Vodafone", "PYUR", "eazy", "O2", "1&1", "Telekom", "NetCologne", "M-net", "Wilhelm.tel"],
    "tariff": "Tariff",
    "max_downstream": "Max Downstream",
    "max_upstream": "Max Upstream",

    # Export
    "export_llm": "Export for LLM",
    "export_title": "LLM Analysis Export",
    "export_hint": "Copy this text and paste it into your favorite LLM (ChatGPT, Claude, Gemini, ...) for connection insights.",
    "copy_clipboard": "Copy to Clipboard",
    "copied": "Copied!",
    "close": "Close",
    "export_no_data": "No data available yet. Wait for the first poll.",
}

DE = {
    "nav": "Navigation",
    "live_dashboard": "Live Dashboard",
    "day_trend": "Tagesverlauf",
    "week_trend": "Wochentrend",
    "month_trend": "Monatstrend",
    "settings": "Einstellungen",
    "reference_values": "Richtwerte",

    "open_calendar": "Kalender oeffnen",
    "last_update": "Letztes Update",

    "health_good": "Gut",
    "health_marginal": "Grenzwertig",
    "health_poor": "Schlecht",
    "health_warning": "Warnung",
    "health_critical": "Kritisch",

    "ds_channels": "Downstream Kanaele",
    "us_channels": "Upstream Kanaele",
    "ds_power_range": "DS Power (Min / Avg / Max)",
    "ds_snr_range": "DS SNR (Min / Avg)",
    "ds_errors_label": "DS Fehler (korr. / unkorr.)",
    "us_power_range": "US Power (Min / Avg / Max)",

    "status": "Status",
    "channel": "Kanal",
    "frequency": "Frequenz",
    "power_dbmv": "Power (dBmV)",
    "snr_db": "SNR (dB)",
    "modulation": "Modulation",
    "corr": "Korr.",
    "uncorr": "Unkorr.",
    "multiplex": "Multiplex",
    "channels": "Kanaele",
    "downstream": "Downstream",
    "upstream": "Upstream",

    "metric": "Metrik",
    "good": "Gut",
    "marginal": "Grenz.",
    "poor": "Schlecht",
    "low": "niedrig",

    "historical_view": "Historische Ansicht",
    "back_to_live": "Zurueck zu Live",
    "error_label": "Fehler",
    "waiting_msg": "Warte auf erste DOCSIS-Abfrage...",

    "no_data": "Keine Daten fuer diesen Zeitraum vorhanden.",
    "trend_error": "Fehler beim Laden der Trenddaten.",
    "correctable": "Korrigierbar",
    "uncorrectable": "Unkorrigierbar",
    "errors": "Fehler",
    "ds_power_avg": "DS Power Avg (dBmV)",
    "ds_snr_avg": "DS SNR Avg (dB)",
    "us_power_avg": "US Power Avg (dBmV)",

    "live": "Live",
    "day": "Tag",
    "week": "Woche",
    "month": "Monat",
    "months": ["Januar", "Februar", "Maerz", "April", "Mai", "Juni",
               "Juli", "August", "September", "Oktober", "November", "Dezember"],

    "initial_setup": "Ersteinrichtung",
    "fritz_connection": "FritzBox-Verbindung",
    "url": "URL",
    "username": "Benutzername",
    "password": "Passwort",
    "test_connection": "Verbindung testen",
    "poll_interval": "Abfrageintervall",
    "interval_sec": "Intervall (Sekunden)",
    "history_days": "Historie (Tage)",
    "history_hint": "Wie lange Snapshots gespeichert werden",
    "snapshot_time": "Tages-Snapshot (Uhrzeit)",
    "snapshot_hint": "Referenz-Zeitpunkt fuer Tagesvergleiche und Trends",
    "advanced_mqtt": "Erweitert: MQTT / Home Assistant",
    "optional": "Optional",
    "mqtt_broker": "MQTT Broker",
    "mqtt_desc": "Fuer die Integration mit Home Assistant via MQTT Auto-Discovery. Ohne MQTT laeuft nur die Web-Oberflaeche.",
    "mqtt_optional_ha": "optional - fuer Home Assistant",
    "username_opt": "Benutzername (optional)",
    "password_opt": "Passwort (optional)",
    "topic_prefix": "Topic-Prefix",
    "complete_setup": "Einrichtung abschliessen",
    "testing": "Teste...",
    "connected": "Verbunden",
    "network_error": "Netzwerkfehler",
    "pw_required": "FritzBox-Passwort ist erforderlich.",
    "unknown_error": "Unbekannt",
    "error_prefix": "Fehler",
    "default": "Standard",

    "back_dashboard": "Zurueck zum Dashboard",
    "light_mode": "Light Mode",
    "dark_mode": "Dark Mode",
    "general": "Allgemein",
    "save": "Speichern",
    "settings_saved": "Einstellungen gespeichert",
    "save_failed": "Speichern fehlgeschlagen",
    "saved_ph": "Gespeichert",

    "language": "Sprache",

    "isp_name": "Internetanbieter",
    "isp_hint": "Wird im LLM-Export angezeigt",
    "isp_other": "Andere",
    "isp_other_placeholder": "Anbietername eingeben",
    "isp_select": "Anbieter waehlen",
    "isp_options": ["Vodafone", "PYUR", "eazy", "O2", "1&1", "Telekom", "NetCologne", "M-net", "Wilhelm.tel"],
    "tariff": "Tarif",
    "max_downstream": "Max Downstream",
    "max_upstream": "Max Upstream",

    "export_llm": "Export fuer LLM",
    "export_title": "LLM-Analyse Export",
    "export_hint": "Kopiere diesen Text und fuege ihn in dein bevorzugtes LLM (ChatGPT, Claude, Gemini, ...) ein, um Insights zu deiner Verbindung zu erhalten.",
    "copy_clipboard": "In Zwischenablage kopieren",
    "copied": "Kopiert!",
    "close": "Schliessen",
    "export_no_data": "Noch keine Daten vorhanden. Warte auf die erste Abfrage.",
}

_TRANSLATIONS = {"en": EN, "de": DE}


def get_translations(lang="en"):
    """Return translation dict for given language code."""
    return _TRANSLATIONS.get(lang, EN)
