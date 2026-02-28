"""Incident Report PDF generator for DOCSight."""

import io
import logging
import os
from datetime import datetime

from fpdf import FPDF

from app.analyzer import get_thresholds

log = logging.getLogger("docsis.report")

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")


def _format_threshold_table():
    """Build display-ready threshold rows from thresholds.json."""
    t = get_thresholds()
    rows = []
    # DS Power - per modulation
    ds = t.get("downstream_power", {})
    for mod in ("256QAM", "64QAM", "1024QAM", "4096QAM"):
        v = ds.get(mod)
        if not v:
            continue
        rows.append({
            "category": "DS Power",
            "variant": mod,
            "good": f"{v['good_min']} to {v['good_max']} dBmV",
            "warn": f"{v['tolerated_min']} to {v['tolerated_max']} dBmV",
            "ref": "VFKD",
        })
    # US Power - per DOCSIS version
    us = t.get("upstream_power", {})
    for ver in ("EuroDOCSIS 3.0", "DOCSIS 3.1"):
        v = us.get(ver)
        if not v:
            continue
        rows.append({
            "category": "US Power",
            "variant": ver,
            "good": f"{v['good_min']} to {v['good_max']} dBmV",
            "warn": f"{v['tolerated_min']} to {v['tolerated_max']} dBmV",
            "ref": "VFKD",
        })
    # SNR - per modulation
    snr = t.get("snr", {})
    for mod in ("256QAM", "64QAM", "1024QAM", "4096QAM"):
        v = snr.get(mod)
        if not v:
            continue
        rows.append({
            "category": "SNR/MER",
            "variant": mod,
            "good": f">= {v['good_min']} dB",
            "warn": f">= {v['tolerated_min']} dB",
            "ref": "VFKD",
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
            "warn": f"<= {warn_qam}-QAM / <= {crit_qam}-QAM crit.",
            "ref": "VFKD",
        })
    return rows


def _default_warn_thresholds():
    """Get default warning thresholds as display strings for report."""
    t = get_thresholds()
    ds = t.get("downstream_power", {}).get("256QAM", {})
    us = t.get("upstream_power", {}).get("EuroDOCSIS 3.0", {})
    snr = t.get("snr", {}).get("256QAM", {})
    return {
        "ds_power": f"{ds.get('tolerated_min', -5.9)} to {ds.get('tolerated_max', 18.0)} dBmV",
        "us_power": f"{us.get('tolerated_min', 37.1)} to {us.get('tolerated_max', 51.0)} dBmV",
        "snr": f">= {snr.get('tolerated_min', 32.0)} dB",
    }

# ---------------------------------------------------------------------------
# Localised strings for PDF reports
# ---------------------------------------------------------------------------
REPORT_STRINGS = {
    "en": {
        "report_title": "DOCSight Incident Report",
        "generated": "Generated:",
        "page": "Page",
        "footer": "DOCSight Incident Report",
        # Section titles
        "section_connection_info": "Connection Information",
        "section_current_status": "Current Status",
        "section_historical": "Historical Analysis",
        "section_thresholds": "Reference: DOCSIS Signal Thresholds",
        "section_complaint": "ISP Complaint Template",
        # Labels
        "isp": "ISP",
        "tariff": "Tariff",
        "modem": "Modem",
        "report_period": "Report Period",
        "data_points": "Data Points",
        "connection_health": "Connection Health",
        "issues": "Issues",
        "ds_channels": "Downstream Channels",
        "us_channels": "Upstream Channels",
        "period_to": "to",
        # Table headers
        "col_ch": "CH",
        "col_freq": "Freq",
        "col_power": "Power",
        "col_snr": "SNR",
        "col_mod": "Mod",
        "col_corr_err": "Corr Err",
        "col_uncorr_err": "Uncorr Err",
        "col_health": "Health",
        "col_multiplex": "Multiplex",
        "col_parameter": "Parameter",
        "col_modulation": "Modulation",
        "col_good": "Good",
        "col_warning": "Warning",
        "col_reference": "Reference",
        # Stats
        "total_measurements": "Total Measurements",
        "measurements_poor": "Measurements with POOR health",
        "measurements_marginal": "Measurements with MARGINAL health",
        "worst_recorded": "Worst Recorded Values",
        "ds_power_worst": "DS Power (worst max)",
        "us_power_worst": "US Power (worst max)",
        "ds_snr_worst": "DS SNR (worst min)",
        "uncorr_err_max": "Uncorrectable Errors (max)",
        "corr_err_max": "Correctable Errors (max)",
        "worst_ds_channels": "Most Problematic Downstream Channels",
        "worst_us_channels": "Most Problematic Upstream Channels",
        "channel_unhealthy": "Channel {cid}: unhealthy in {count}/{total} measurements ({pct}%)",
        # Complaint letter
        "complaint_subject": "Subject: Persistent DOCSIS Signal Quality Issues — Request for Technical Inspection",
        "complaint_greeting": "Dear {isp} Technical Support,",
        "complaint_body": (
            "I am writing to formally document ongoing signal quality issues with my cable internet connection. "
            "Using automated monitoring (DOCSight), I have collected {count} measurements "
            "between {start} and {end}."
        ),
        "complaint_findings": "Key findings:",
        "complaint_poor_rate": "Connection rated POOR in {poor} of {total} measurements ({pct}%)",
        "complaint_ds_power": "Worst downstream power: {val} dBmV (threshold: {thresh})",
        "complaint_us_power": "Worst upstream power: {val} dBmV (threshold: {thresh})",
        "complaint_snr": "Worst downstream SNR: {val} dB (threshold: {thresh})",
        "complaint_uncorr": "Peak uncorrectable errors: {val}",
        "complaint_exceed": (
            "These values exceed the acceptable ranges defined in the DOCSIS specification and indicate "
            "physical layer issues that require on-site investigation."
        ),
        "complaint_request": "I request:",
        "complaint_req1": "A qualified technician visit to inspect the coaxial infrastructure",
        "complaint_req2": "Signal level measurements at the tap and at my premises",
        "complaint_req3": "Written documentation of findings and corrective actions",
        "complaint_escalation": (
            "The full monitoring data is attached to this report. I reserve the right to escalate this matter "
            "to the Bundesnetzagentur (Federal Network Agency) if the issue is not resolved within a reasonable timeframe."
        ),
        "complaint_closing_label": "Sincerely,",
        "complaint_closing": "Sincerely,\n[Your Name]\n[Customer Number]\n[Address]",
        "complaint_short_subject": "Subject: DOCSIS Signal Quality Issues",
        "complaint_short_greeting": "Dear Technical Support,",
        "complaint_short_body": (
            "I am experiencing persistent signal quality issues with my cable internet connection. "
            "Please see the attached monitoring data for details."
        ),
        "complaint_short_closing": "Sincerely,\n[Your Name]",
        # Incident-scoped report
        "incident_report_title": "DOCSight Complaint Report",
        "section_incident_summary": "Incident Summary",
        "incident_name": "Incident",
        "incident_status": "Status",
        "incident_period": "Period",
        "incident_duration": "Duration",
        "incident_duration_days": "{days} days",
        "incident_duration_ongoing": "ongoing",
        "section_speedtest": "Speed Test Results",
        "speedtest_date": "Date",
        "speedtest_download": "Download",
        "speedtest_upload": "Upload",
        "speedtest_ping": "Ping",
        "speedtest_avg": "Average",
        "speedtest_min": "Minimum",
        "section_bnetz": "BNetzA Measurements",
        "section_journal": "Journal Entries",
        "journal_attachments": "{count} attachment(s)",
        # BNetzA complaint section
        "complaint_bnetz_header": "Official Broadband Measurement (Bundesnetzagentur):",
        "complaint_bnetz_body": (
            "According to the official measurement protocol dated {date}, conducted in compliance with "
            "the Breitbandmessung methodology, the following contractual deviations were recorded:"
        ),
        "complaint_bnetz_tariff": "Tariff: {tariff} ({provider})",
        "complaint_bnetz_dl": "Contracted download speed: {max} Mbit/s / Measured average download: {avg} Mbit/s ({pct}% of contracted maximum)",
        "complaint_bnetz_ul": "Contracted upload speed: {max} Mbit/s / Measured average upload: {avg} Mbit/s ({pct}% of contracted maximum)",
        "complaint_bnetz_verdict": "Verdict: Download {verdict_dl} / Upload {verdict_ul}",
        "complaint_bnetz_legal": (
            "Under Section 57(4) TKG, the consistently measured speeds fall below the contractually "
            "guaranteed service levels, establishing grounds for fee reduction or contract termination."
        ),
    },
    "de": {
        "report_title": "DOCSight Störungsbericht",
        "generated": "Erstellt:",
        "page": "Seite",
        "footer": "DOCSight Störungsbericht",
        "section_connection_info": "Verbindungsinformationen",
        "section_current_status": "Aktueller Status",
        "section_historical": "Historische Analyse",
        "section_thresholds": "Referenz: DOCSIS-Signalgrenzwerte",
        "section_complaint": "ISP-Beschwerdevorlage",
        "isp": "ISP",
        "tariff": "Tarif",
        "modem": "Modem",
        "report_period": "Berichtszeitraum",
        "data_points": "Datenpunkte",
        "connection_health": "Verbindungsqualität",
        "issues": "Probleme",
        "ds_channels": "Downstream-Kanäle",
        "us_channels": "Upstream-Kanäle",
        "period_to": "bis",
        "col_ch": "CH",
        "col_freq": "Freq",
        "col_power": "Pegel",
        "col_snr": "SNR",
        "col_mod": "Mod",
        "col_corr_err": "Korr Err",
        "col_uncorr_err": "Unkorr Err",
        "col_health": "Zustand",
        "col_multiplex": "Multiplex",
        "col_parameter": "Parameter",
        "col_modulation": "Modulation",
        "col_good": "Gut",
        "col_warning": "Warnung",
        "col_reference": "Referenz",
        "total_measurements": "Messungen gesamt",
        "measurements_poor": "Messungen mit Zustand SCHLECHT",
        "measurements_marginal": "Messungen mit Zustand GRENZWERTIG",
        "worst_recorded": "Schlechteste gemessene Werte",
        "ds_power_worst": "DS-Pegel (schlechtester Max.)",
        "us_power_worst": "US-Pegel (schlechtester Max.)",
        "ds_snr_worst": "DS-SNR (schlechtester Min.)",
        "uncorr_err_max": "Nicht korrigierbare Fehler (Max.)",
        "corr_err_max": "Korrigierbare Fehler (Max.)",
        "worst_ds_channels": "Problematischste Downstream-Kanäle",
        "worst_us_channels": "Problematischste Upstream-Kanäle",
        "channel_unhealthy": "Kanal {cid}: auffällig in {count}/{total} Messungen ({pct}%)",
        "complaint_subject": "Betreff: Anhaltende DOCSIS-Signalqualitätsprobleme — Antrag auf technische Überprüfung",
        "complaint_greeting": "Sehr geehrte Damen und Herren der technischen Abteilung von {isp},",
        "complaint_body": (
            "hiermit dokumentiere ich formell anhaltende Signalqualitätsprobleme meines Kabelinternetanschlusses. "
            "Mithilfe automatisierter Überwachung (DOCSight) habe ich {count} Messungen "
            "im Zeitraum vom {start} bis {end} erfasst."
        ),
        "complaint_findings": "Wesentliche Ergebnisse:",
        "complaint_poor_rate": "Verbindung als SCHLECHT bewertet in {poor} von {total} Messungen ({pct}%)",
        "complaint_ds_power": "Schlechtester Downstream-Pegel: {val} dBmV (Grenzwert: {thresh})",
        "complaint_us_power": "Schlechtester Upstream-Pegel: {val} dBmV (Grenzwert: {thresh})",
        "complaint_snr": "Schlechtester Downstream-SNR: {val} dB (Grenzwert: {thresh})",
        "complaint_uncorr": "Maximale nicht korrigierbare Fehler: {val}",
        "complaint_exceed": (
            "Diese Werte überschreiten die in der DOCSIS-Spezifikation definierten zulässigen Bereiche und deuten "
            "auf Probleme der physikalischen Schicht hin, die eine Vor-Ort-Untersuchung erfordern."
        ),
        "complaint_request": "Ich beantrage:",
        "complaint_req1": "Einen Technikerbesuch zur Überprüfung der Koaxialinfrastruktur",
        "complaint_req2": "Signalpegelmessungen am Übergabepunkt und an meinem Anschluss",
        "complaint_req3": "Schriftliche Dokumentation der Ergebnisse und Korrekturmaßnahmen",
        "complaint_escalation": (
            "Die vollständigen Überwachungsdaten sind diesem Bericht beigefügt. Ich behalte mir vor, "
            "diese Angelegenheit an die Bundesnetzagentur weiterzuleiten, sofern das Problem nicht "
            "innerhalb einer angemessenen Frist behoben wird."
        ),
        "complaint_closing_label": "Mit freundlichen Grüßen,",
        "complaint_closing": "Mit freundlichen Grüßen,\n[Ihr Name]\n[Kundennummer]\n[Adresse]",
        "complaint_short_subject": "Betreff: DOCSIS-Signalqualitätsprobleme",
        "complaint_short_greeting": "Sehr geehrte Damen und Herren,",
        "complaint_short_body": (
            "ich habe anhaltende Signalqualitätsprobleme mit meinem Kabelinternetanschluss. "
            "Bitte entnehmen Sie die Details den beigefügten Überwachungsdaten."
        ),
        "complaint_short_closing": "Mit freundlichen Grüßen,\n[Ihr Name]",
        # Incident-scoped report
        "incident_report_title": "DOCSight Beschwerdebericht",
        "section_incident_summary": "Zusammenfassung",
        "incident_name": "Vorfall",
        "incident_status": "Status",
        "incident_period": "Zeitraum",
        "incident_duration": "Dauer",
        "incident_duration_days": "{days} Tage",
        "incident_duration_ongoing": "andauernd",
        "section_speedtest": "Geschwindigkeitstests",
        "speedtest_date": "Datum",
        "speedtest_download": "Download",
        "speedtest_upload": "Upload",
        "speedtest_ping": "Ping",
        "speedtest_avg": "Durchschnitt",
        "speedtest_min": "Minimum",
        "section_bnetz": "BNetzA-Messungen",
        "section_journal": "Journal-Eintraege",
        "journal_attachments": "{count} Anhang/Anhaenge",
        # BNetzA complaint section
        "complaint_bnetz_header": "Offizielle Breitbandmessung (Bundesnetzagentur):",
        "complaint_bnetz_body": (
            "Laut dem offiziellen Messprotokoll vom {date}, durchgeführt gemäß der "
            "Breitbandmessung-Methodik, wurden folgende vertragliche Abweichungen festgestellt:"
        ),
        "complaint_bnetz_tariff": "Tarif: {tariff} ({provider})",
        "complaint_bnetz_dl": "Vertragliche Download-Geschwindigkeit: {max} Mbit/s / Gemessener Durchschnitt: {avg} Mbit/s ({pct}% des vertraglichen Maximums)",
        "complaint_bnetz_ul": "Vertragliche Upload-Geschwindigkeit: {max} Mbit/s / Gemessener Durchschnitt: {avg} Mbit/s ({pct}% des vertraglichen Maximums)",
        "complaint_bnetz_verdict": "Bewertung: Download {verdict_dl} / Upload {verdict_ul}",
        "complaint_bnetz_legal": (
            "Gemäß § 57 Abs. 4 TKG unterschreiten die gemessenen Geschwindigkeiten dauerhaft die vertraglich "
            "zugesicherten Leistungswerte, was eine Grundlage für Entgeltminderung oder Vertragskündigung darstellt."
        ),
    },
    "fr": {
        "report_title": "DOCSight Rapport d'incident",
        "generated": "Généré :",
        "page": "Page",
        "footer": "DOCSight Rapport d'incident",
        "section_connection_info": "Informations de connexion",
        "section_current_status": "État actuel",
        "section_historical": "Analyse historique",
        "section_thresholds": "Référence : Seuils de signal DOCSIS",
        "section_complaint": "Modèle de réclamation FAI",
        "isp": "FAI",
        "tariff": "Forfait",
        "modem": "Modem",
        "report_period": "Période du rapport",
        "data_points": "Points de données",
        "connection_health": "Santé de la connexion",
        "issues": "Problèmes",
        "ds_channels": "Canaux descendants",
        "us_channels": "Canaux montants",
        "period_to": "au",
        "col_ch": "CH",
        "col_freq": "Fréq",
        "col_power": "Puiss",
        "col_snr": "SNR",
        "col_mod": "Mod",
        "col_corr_err": "Err Corr",
        "col_uncorr_err": "Err Non-c",
        "col_health": "État",
        "col_multiplex": "Multiplex",
        "col_parameter": "Paramètre",
        "col_modulation": "Modulation",
        "col_good": "Bon",
        "col_warning": "Alerte",
        "col_reference": "Référence",
        "total_measurements": "Mesures totales",
        "measurements_poor": "Mesures avec état MAUVAIS",
        "measurements_marginal": "Mesures avec état LIMITE",
        "worst_recorded": "Pires valeurs enregistrées",
        "ds_power_worst": "Puiss DS (pire max)",
        "us_power_worst": "Puiss US (pire max)",
        "ds_snr_worst": "SNR DS (pire min)",
        "uncorr_err_max": "Erreurs non corrigeables (max)",
        "corr_err_max": "Erreurs corrigeables (max)",
        "worst_ds_channels": "Canaux descendants les plus problématiques",
        "worst_us_channels": "Canaux montants les plus problématiques",
        "channel_unhealthy": "Canal {cid} : défaillant dans {count}/{total} mesures ({pct}%)",
        "complaint_subject": "Objet : Problèmes persistants de qualité du signal DOCSIS — Demande d'inspection technique",
        "complaint_greeting": "Madame, Monsieur, Service technique de {isp},",
        "complaint_body": (
            "Par la présente, je documente formellement des problèmes persistants de qualité du signal "
            "de ma connexion Internet par câble. À l'aide d'une surveillance automatisée (DOCSight), "
            "j'ai collecté {count} mesures entre le {start} et le {end}."
        ),
        "complaint_findings": "Résultats principaux :",
        "complaint_poor_rate": "Connexion évaluée MAUVAISE dans {poor} sur {total} mesures ({pct}%)",
        "complaint_ds_power": "Pire puissance descendante : {val} dBmV (seuil : {thresh})",
        "complaint_us_power": "Pire puissance montante : {val} dBmV (seuil : {thresh})",
        "complaint_snr": "Pire SNR descendant : {val} dB (seuil : {thresh})",
        "complaint_uncorr": "Maximum d'erreurs non corrigeables : {val}",
        "complaint_exceed": (
            "Ces valeurs dépassent les plages acceptables définies dans la spécification DOCSIS et indiquent "
            "des problèmes de couche physique nécessitant une investigation sur site."
        ),
        "complaint_request": "Je demande :",
        "complaint_req1": "La visite d'un technicien qualifié pour inspecter l'infrastructure coaxiale",
        "complaint_req2": "Des mesures de niveau de signal au point de raccordement et dans mes locaux",
        "complaint_req3": "Une documentation écrite des constats et des mesures correctives",
        "complaint_escalation": (
            "L'ensemble des données de surveillance est joint à ce rapport. Je me réserve le droit de saisir "
            "l'ARCEP (Autorité de régulation des communications électroniques et des postes) si le problème "
            "n'est pas résolu dans un délai raisonnable."
        ),
        "complaint_closing_label": "Veuillez agréer mes salutations distinguées,",
        "complaint_closing": "Veuillez agréer mes salutations distinguées,\n[Votre nom]\n[Numéro client]\n[Adresse]",
        "complaint_short_subject": "Objet : Problèmes de qualité du signal DOCSIS",
        "complaint_short_greeting": "Madame, Monsieur,",
        "complaint_short_body": (
            "Je rencontre des problèmes persistants de qualité du signal de ma connexion Internet par câble. "
            "Veuillez consulter les données de surveillance jointes pour plus de détails."
        ),
        "complaint_short_closing": "Veuillez agréer mes salutations distinguées,\n[Votre nom]",
        # Incident-scoped report
        "incident_report_title": "DOCSight Rapport de plainte",
        "section_incident_summary": "Resume de l'incident",
        "incident_name": "Incident",
        "incident_status": "Statut",
        "incident_period": "Periode",
        "incident_duration": "Duree",
        "incident_duration_days": "{days} jours",
        "incident_duration_ongoing": "en cours",
        "section_speedtest": "Tests de debit",
        "speedtest_date": "Date",
        "speedtest_download": "Telechargement",
        "speedtest_upload": "Envoi",
        "speedtest_ping": "Ping",
        "speedtest_avg": "Moyenne",
        "speedtest_min": "Minimum",
        "section_bnetz": "Mesures BNetzA",
        "section_journal": "Entrees du journal",
        "journal_attachments": "{count} piece(s) jointe(s)",
        # BNetzA complaint section
        "complaint_bnetz_header": "Mesure officielle du haut débit (Bundesnetzagentur) :",
        "complaint_bnetz_body": (
            "Selon le protocole de mesure officiel du {date}, réalisé conformément à la "
            "méthodologie Breitbandmessung, les écarts contractuels suivants ont été constatés :"
        ),
        "complaint_bnetz_tariff": "Forfait : {tariff} ({provider})",
        "complaint_bnetz_dl": "Débit descendant contractuel : {max} Mbit/s / Débit descendant mesuré : {avg} Mbit/s ({pct}% du maximum contractuel)",
        "complaint_bnetz_ul": "Débit montant contractuel : {max} Mbit/s / Débit montant mesuré : {avg} Mbit/s ({pct}% du maximum contractuel)",
        "complaint_bnetz_verdict": "Verdict : Descendant {verdict_dl} / Montant {verdict_ul}",
        "complaint_bnetz_legal": (
            "Conformément aux dispositions de l'ARCEP relatives aux obligations de qualité de service, "
            "les débits mesurés sont systématiquement inférieurs aux niveaux de service contractuels, "
            "établissant un fondement pour une réduction tarifaire ou la résiliation du contrat."
        ),
    },
    "es": {
        "report_title": "DOCSight Informe de incidencia",
        "generated": "Generado:",
        "page": "Página",
        "footer": "DOCSight Informe de incidencia",
        "section_connection_info": "Información de conexión",
        "section_current_status": "Estado actual",
        "section_historical": "Análisis histórico",
        "section_thresholds": "Referencia: Umbrales de señal DOCSIS",
        "section_complaint": "Plantilla de reclamación al ISP",
        "isp": "ISP",
        "tariff": "Tarifa",
        "modem": "Módem",
        "report_period": "Período del informe",
        "data_points": "Puntos de datos",
        "connection_health": "Salud de la conexión",
        "issues": "Problemas",
        "ds_channels": "Canales descendentes",
        "us_channels": "Canales ascendentes",
        "period_to": "a",
        "col_ch": "CH",
        "col_freq": "Frec",
        "col_power": "Pot",
        "col_snr": "SNR",
        "col_mod": "Mod",
        "col_corr_err": "Err Corr",
        "col_uncorr_err": "Err No-c",
        "col_health": "Estado",
        "col_multiplex": "Multiplex",
        "col_parameter": "Parámetro",
        "col_modulation": "Modulación",
        "col_good": "Bueno",
        "col_warning": "Alerta",
        "col_reference": "Referencia",
        "total_measurements": "Mediciones totales",
        "measurements_poor": "Mediciones con estado MALO",
        "measurements_marginal": "Mediciones con estado MARGINAL",
        "worst_recorded": "Peores valores registrados",
        "ds_power_worst": "Pot DS (peor máx)",
        "us_power_worst": "Pot US (peor máx)",
        "ds_snr_worst": "SNR DS (peor mín)",
        "uncorr_err_max": "Errores no corregibles (máx)",
        "corr_err_max": "Errores corregibles (máx)",
        "worst_ds_channels": "Canales descendentes más problemáticos",
        "worst_us_channels": "Canales ascendentes más problemáticos",
        "channel_unhealthy": "Canal {cid}: defectuoso en {count}/{total} mediciones ({pct}%)",
        "complaint_subject": "Asunto: Problemas persistentes de calidad de señal DOCSIS — Solicitud de inspección técnica",
        "complaint_greeting": "Estimado servicio técnico de {isp},",
        "complaint_body": (
            "Por medio de la presente, documento formalmente problemas persistentes de calidad de señal "
            "en mi conexión de Internet por cable. Mediante monitorización automatizada (DOCSight), "
            "he recopilado {count} mediciones entre el {start} y el {end}."
        ),
        "complaint_findings": "Hallazgos principales:",
        "complaint_poor_rate": "Conexión calificada como MALA en {poor} de {total} mediciones ({pct}%)",
        "complaint_ds_power": "Peor potencia descendente: {val} dBmV (umbral: {thresh})",
        "complaint_us_power": "Peor potencia ascendente: {val} dBmV (umbral: {thresh})",
        "complaint_snr": "Peor SNR descendente: {val} dB (umbral: {thresh})",
        "complaint_uncorr": "Máximo de errores no corregibles: {val}",
        "complaint_exceed": (
            "Estos valores exceden los rangos aceptables definidos en la especificación DOCSIS e indican "
            "problemas de capa física que requieren una investigación en el sitio."
        ),
        "complaint_request": "Solicito:",
        "complaint_req1": "Una visita de un técnico cualificado para inspeccionar la infraestructura coaxial",
        "complaint_req2": "Mediciones de nivel de señal en el punto de conexión y en mis instalaciones",
        "complaint_req3": "Documentación escrita de los hallazgos y las acciones correctivas",
        "complaint_escalation": (
            "Los datos completos de monitorización se adjuntan a este informe. Me reservo el derecho de elevar "
            "este asunto a la Secretaría de Estado de Telecomunicaciones e Infraestructuras Digitales "
            "si el problema no se resuelve en un plazo razonable."
        ),
        "complaint_closing_label": "Atentamente,",
        "complaint_closing": "Atentamente,\n[Su nombre]\n[Número de cliente]\n[Dirección]",
        "complaint_short_subject": "Asunto: Problemas de calidad de señal DOCSIS",
        "complaint_short_greeting": "Estimado servicio técnico,",
        "complaint_short_body": (
            "Estoy experimentando problemas persistentes de calidad de señal en mi conexión de Internet por cable. "
            "Consulte los datos de monitorización adjuntos para más detalles."
        ),
        "complaint_short_closing": "Atentamente,\n[Su nombre]",
        # Incident-scoped report
        "incident_report_title": "DOCSight Informe de queja",
        "section_incident_summary": "Resumen del incidente",
        "incident_name": "Incidente",
        "incident_status": "Estado",
        "incident_period": "Periodo",
        "incident_duration": "Duracion",
        "incident_duration_days": "{days} dias",
        "incident_duration_ongoing": "en curso",
        "section_speedtest": "Pruebas de velocidad",
        "speedtest_date": "Fecha",
        "speedtest_download": "Descarga",
        "speedtest_upload": "Subida",
        "speedtest_ping": "Ping",
        "speedtest_avg": "Promedio",
        "speedtest_min": "Minimo",
        "section_bnetz": "Mediciones BNetzA",
        "section_journal": "Entradas del diario",
        "journal_attachments": "{count} adjunto(s)",
        # BNetzA complaint section
        "complaint_bnetz_header": "Medición oficial de banda ancha (Bundesnetzagentur):",
        "complaint_bnetz_body": (
            "Según el protocolo de medición oficial del {date}, realizado conforme a la "
            "metodología Breitbandmessung, se registraron las siguientes desviaciones contractuales:"
        ),
        "complaint_bnetz_tariff": "Tarifa: {tariff} ({provider})",
        "complaint_bnetz_dl": "Velocidad de descarga contratada: {max} Mbit/s / Promedio medido: {avg} Mbit/s ({pct}% del máximo contratado)",
        "complaint_bnetz_ul": "Velocidad de subida contratada: {max} Mbit/s / Promedio medido: {avg} Mbit/s ({pct}% del máximo contratado)",
        "complaint_bnetz_verdict": "Resultado: Descarga {verdict_dl} / Subida {verdict_ul}",
        "complaint_bnetz_legal": (
            "De acuerdo con las disposiciones de la Secretaría de Estado de Telecomunicaciones "
            "e Infraestructuras Digitales sobre obligaciones de calidad del servicio, las velocidades "
            "medidas se encuentran por debajo de los niveles contractuales, lo que constituye fundamento "
            "para una reducción de la tarifa o la terminación del contrato."
        ),
    },
}


class IncidentReport(FPDF):
    """Custom PDF class for DOCSight incident reports."""

    def __init__(self, lang="en"):
        super().__init__()
        self.lang = lang
        self._s = REPORT_STRINGS.get(lang, REPORT_STRINGS["en"])
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
        self.cell(0, 10, f"{s['footer']} — {s['page']} {self.page_no()}/{{nb}}", align="C")

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
    s = REPORT_STRINGS.get(lang, REPORT_STRINGS["en"])
    pdf = IncidentReport(lang=lang)
    pdf.alias_nb_pages()
    pdf.add_page()

    # --- Connection Info ---
    pdf._section_title(s["section_connection_info"])
    isp = config.get("isp_name", "Unknown ISP")
    pdf._key_value(s["isp"], isp)
    ds_mbps = connection_info.get("max_downstream_kbps", 0) // 1000 if connection_info.get("max_downstream_kbps") else "N/A"
    us_mbps = connection_info.get("max_upstream_kbps", 0) // 1000 if connection_info.get("max_upstream_kbps") else "N/A"
    pdf._key_value(s["tariff"], f"{ds_mbps} / {us_mbps} Mbit/s (Down / Up)")
    device = config.get("modem_type", connection_info.get("device_name", "Unknown"))
    pdf._key_value(s["modem"], device)

    if snapshots:
        start = snapshots[0]["timestamp"]
        end = snapshots[-1]["timestamp"]
        pdf._key_value(s["report_period"], f"{start}  {s['period_to']}  {end}")
        pdf._key_value(s["data_points"], str(len(snapshots)))
    pdf.ln(3)

    # --- Current Status ---
    pdf._section_title(s["section_current_status"])
    if current_analysis:
        sm = current_analysis["summary"]
        health = sm.get("health", "unknown")
        pdf.set_font("dejavu", "B", 12)
        r, g, b = pdf._health_color(health)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, f"{s['connection_health']}: {health.upper()}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if sm.get("health_issues"):
            pdf.set_font("dejavu", "", 10)
            pdf.cell(0, 6, f"{s['issues']}: {', '.join(sm['health_issues'])}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Current channel table
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["ds_channels"], new_x="LMARGIN", new_y="NEXT")
        cols = [s["col_ch"], s["col_freq"], s["col_power"], s["col_snr"], s["col_mod"], s["col_corr_err"], s["col_uncorr_err"], s["col_health"]]
        widths = [12, 25, 20, 18, 22, 25, 25, 20]
        pdf._table_header(cols, widths)
        for ch in current_analysis.get("ds_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                (ch.get("frequency") or "")[:10],
                f"{ch.get('power') or 0:.1f}",
                f"{ch.get('snr') or 0:.1f}" if ch.get("snr") else "—",
                str(ch.get("modulation") or "")[:10],
                f"{ch.get('correctable_errors') or 0:,}",
                f"{ch.get('uncorrectable_errors') or 0:,}",
                ch.get("health", ""),
            ], widths, health=ch.get("health"))

        pdf.ln(3)
        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["us_channels"], new_x="LMARGIN", new_y="NEXT")
        cols_us = [s["col_ch"], s["col_freq"], s["col_power"], s["col_mod"], s["col_multiplex"], s["col_health"]]
        widths_us = [15, 30, 25, 30, 35, 25]
        pdf._table_header(cols_us, widths_us)
        for ch in current_analysis.get("us_channels", []):
            pdf._table_row([
                ch.get("channel_id", ""),
                (ch.get("frequency") or "")[:12],
                f"{ch.get('power') or 0:.1f}",
                str(ch.get("modulation") or "")[:12],
                str(ch.get("multiplex") or "")[:15],
                ch.get("health", ""),
            ], widths_us, health=ch.get("health"))

    # --- Historical Analysis ---
    if snapshots:
        pdf.add_page()
        pdf._section_title(s["section_historical"])
        worst = _compute_worst_values(snapshots)

        pdf._key_value(s["total_measurements"], str(worst["total_snapshots"]))
        pdf._key_value(s["measurements_poor"], str(worst["health_poor_count"]), bold_value=True)
        pdf._key_value(s["measurements_marginal"], str(worst["health_marginal_count"]))
        pdf.ln(2)

        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["worst_recorded"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dejavu", "", 10)

        warn = _default_warn_thresholds()
        pdf._key_value(s["ds_power_worst"], f"{worst['ds_power_max']} dBmV (threshold: {warn['ds_power']})")
        pdf._key_value(s["us_power_worst"], f"{worst['us_power_max']} dBmV (threshold: {warn['us_power']})")
        pdf._key_value(s["ds_snr_worst"], f"{worst['ds_snr_min']} dB (threshold: {warn['snr']})")
        pdf._key_value(s["uncorr_err_max"], f"{worst['ds_uncorrectable_max']:,}")
        pdf._key_value(s["corr_err_max"], f"{worst['ds_correctable_max']:,}")
        pdf.ln(3)

        # Worst channels
        ds_worst, us_worst = _find_worst_channels(snapshots)
        if ds_worst:
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, s["worst_ds_channels"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in ds_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  {s['channel_unhealthy'].format(cid=cid, count=count, total=len(snapshots), pct=pct)}", new_x="LMARGIN", new_y="NEXT")
        if us_worst:
            pdf.ln(2)
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, s["worst_us_channels"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in us_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  {s['channel_unhealthy'].format(cid=cid, count=count, total=len(snapshots), pct=pct)}", new_x="LMARGIN", new_y="NEXT")

    # --- Reference Thresholds ---
    pdf.add_page()
    pdf._section_title(s["section_thresholds"])
    pdf.set_font("dejavu", "", 9)
    cols_ref = [s["col_parameter"], s["col_modulation"], s["col_good"], s["col_warning"], s["col_reference"]]
    widths_ref = [30, 35, 40, 40, 25]
    pdf._table_header(cols_ref, widths_ref)
    for row in _format_threshold_table():
        pdf._table_row([row["category"], row["variant"], row["good"], row["warn"], row["ref"]], widths_ref)
    pdf.ln(5)

    # --- ISP Complaint Template ---
    pdf._section_title(s["section_complaint"])
    pdf.set_font("dejavu", "", 9)

    if snapshots:
        worst = _compute_worst_values(snapshots)
        warn = _default_warn_thresholds()
        start = snapshots[0]["timestamp"][:10]
        end = snapshots[-1]["timestamp"][:10]
        poor_pct = round(worst['health_poor_count'] / max(worst['total_snapshots'], 1) * 100)
        complaint = (
            f"{s['complaint_subject']}\n\n"
            f"{s['complaint_greeting'].format(isp=isp)}\n\n"
            f"{s['complaint_body'].format(count=len(snapshots), start=start, end=end)}\n\n"
            f"{s['complaint_findings']}\n"
            f"- {s['complaint_poor_rate'].format(poor=worst['health_poor_count'], total=worst['total_snapshots'], pct=poor_pct)}\n"
            f"- {s['complaint_ds_power'].format(val=worst['ds_power_max'], thresh=warn['ds_power'])}\n"
            f"- {s['complaint_us_power'].format(val=worst['us_power_max'], thresh=warn['us_power'])}\n"
            f"- {s['complaint_snr'].format(val=worst['ds_snr_min'], thresh=warn['snr'])}\n"
            f"- {s['complaint_uncorr'].format(val='{:,}'.format(worst['ds_uncorrectable_max']))}\n\n"
            f"{s['complaint_exceed']}\n\n"
            f"{s['complaint_request']}\n"
            f"1. {s['complaint_req1']}\n"
            f"2. {s['complaint_req2']}\n"
            f"3. {s['complaint_req3']}\n\n"
            f"{s['complaint_escalation']}\n\n"
            f"{s['complaint_closing']}"
        )
    else:
        complaint = (
            f"{s['complaint_short_subject']}\n\n"
            f"{s['complaint_short_greeting']}\n\n"
            f"{s['complaint_short_body']}\n\n"
            f"{s['complaint_short_closing']}"
        )

    pdf.multi_cell(0, 4, complaint)

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_incident_report(incident, entries, snapshots, speedtests, bnetz_list,
                              config=None, connection_info=None, lang="en",
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
        attachment_loader: Optional callable(attachment_id) -> dict with 'data', 'mime_type'

    Returns:
        bytes: PDF file content
    """
    config = config or {}
    connection_info = connection_info or {}
    s = REPORT_STRINGS.get(lang, REPORT_STRINGS["en"])
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
            period += f"  {s.get('period_to', 'to')}  {end_str}"
            try:
                d1 = datetime.strptime(start_str, "%Y-%m-%d")
                d2 = datetime.strptime(end_str, "%Y-%m-%d")
                days = (d2 - d1).days
                duration = s["incident_duration_days"].format(days=days)
            except ValueError:
                duration = ""
        else:
            period += f"  {s.get('period_to', 'to')}  ..."
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
    pdf._section_title(s["section_connection_info"])
    isp = config.get("isp_name", "Unknown ISP")
    pdf._key_value(s["isp"], isp)
    ds_mbps = connection_info.get("max_downstream_kbps", 0) // 1000 if connection_info.get("max_downstream_kbps") else "N/A"
    us_mbps = connection_info.get("max_upstream_kbps", 0) // 1000 if connection_info.get("max_upstream_kbps") else "N/A"
    pdf._key_value(s["tariff"], f"{ds_mbps} / {us_mbps} Mbit/s (Down / Up)")
    device = config.get("modem_type", connection_info.get("device_name", "Unknown"))
    pdf._key_value(s["modem"], device)

    # ── Page 2: Signal Analysis (if snapshots available) ──
    if snapshots:
        pdf.add_page()
        pdf._section_title(s["section_historical"])
        worst = _compute_worst_values(snapshots)

        pdf._key_value(s["total_measurements"], str(worst["total_snapshots"]))
        pdf._key_value(s["measurements_poor"], str(worst["health_poor_count"]), bold_value=True)
        pdf._key_value(s["measurements_marginal"], str(worst["health_marginal_count"]))
        pdf.ln(2)

        pdf.set_font("dejavu", "B", 10)
        pdf.cell(0, 6, s["worst_recorded"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dejavu", "", 10)

        warn = _default_warn_thresholds()
        pdf._key_value(s["ds_power_worst"], f"{worst['ds_power_max']} dBmV (threshold: {warn['ds_power']})")
        pdf._key_value(s["us_power_worst"], f"{worst['us_power_max']} dBmV (threshold: {warn['us_power']})")
        pdf._key_value(s["ds_snr_worst"], f"{worst['ds_snr_min']} dB (threshold: {warn['snr']})")
        pdf._key_value(s["uncorr_err_max"], f"{worst['ds_uncorrectable_max']:,}")
        pdf._key_value(s["corr_err_max"], f"{worst['ds_correctable_max']:,}")
        pdf.ln(3)

        # Worst channels
        ds_worst, us_worst = _find_worst_channels(snapshots)
        if ds_worst:
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, s["worst_ds_channels"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in ds_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  {s['channel_unhealthy'].format(cid=cid, count=count, total=len(snapshots), pct=pct)}", new_x="LMARGIN", new_y="NEXT")
        if us_worst:
            pdf.ln(2)
            pdf.set_font("dejavu", "B", 10)
            pdf.cell(0, 6, s["worst_us_channels"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("dejavu", "", 9)
            for cid, count in us_worst:
                pct = round(count / len(snapshots) * 100)
                pdf.cell(0, 5, f"  {s['channel_unhealthy'].format(cid=cid, count=count, total=len(snapshots), pct=pct)}", new_x="LMARGIN", new_y="NEXT")

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
            ping = st.get("ping_ms", "-")
            jitter = st.get("jitter_ms", "-")
            loss = st.get("packet_loss_pct", "-")
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

            dl_max = round(m.get("download_max_tariff") or 0)
            dl_avg = round(m.get("download_measured_avg") or 0)
            dl_pct = round(dl_avg / dl_max * 100) if dl_max else 0
            ul_max = round(m.get("upload_max_tariff") or 0)
            ul_avg = round(m.get("upload_measured_avg") or 0)
            ul_pct = round(ul_avg / ul_max * 100) if ul_max else 0

            pdf.cell(0, 5, f"  Download: {dl_avg} / {dl_max} Mbit/s ({dl_pct}%)", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 5, f"  Upload: {ul_avg} / {ul_max} Mbit/s ({ul_pct}%)", new_x="LMARGIN", new_y="NEXT")

            verdict_dl = m.get("verdict_download", "-")
            verdict_ul = m.get("verdict_upload", "-")
            pdf.cell(0, 5, f"  Verdict: DL {verdict_dl} / UL {verdict_ul}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            if verdict_dl == "deviation" or verdict_ul == "deviation":
                has_deviation = True

        if has_deviation:
            pdf.ln(2)
            pdf.set_font("dejavu", "B", 9)
            pdf.set_text_color(231, 76, 60)
            pdf.multi_cell(0, 4, s.get("complaint_bnetz_legal", ""))
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
                        ext = "jpeg" if "jpeg" in mime else "png"
                        # Check remaining page space
                        if pdf.get_y() > 220:
                            pdf.add_page()
                        pdf.image(img_buf, x=pdf.l_margin, w=min(170, pdf.epw), type=ext)
                        pdf.ln(3)
                    except Exception:
                        log.warning("Failed to embed attachment %d in incident report", att_meta.get("id", 0))

            pdf.ln(3)

    # ── Last Page: Complaint Template ──
    pdf.add_page()
    pdf._section_title(s["section_complaint"])
    pdf.set_font("dejavu", "", 9)

    if snapshots:
        worst = _compute_worst_values(snapshots)
        warn = _default_warn_thresholds()
        start = snapshots[0]["timestamp"][:10]
        end = snapshots[-1]["timestamp"][:10]
        poor_pct = round(worst['health_poor_count'] / max(worst['total_snapshots'], 1) * 100)
        complaint = (
            f"{s['complaint_subject']}\n\n"
            f"{s['complaint_greeting'].format(isp=isp)}\n\n"
            f"{s['complaint_body'].format(count=len(snapshots), start=start, end=end)}\n\n"
            f"{s['complaint_findings']}\n"
            f"- {s['complaint_poor_rate'].format(poor=worst['health_poor_count'], total=worst['total_snapshots'], pct=poor_pct)}\n"
            f"- {s['complaint_ds_power'].format(val=worst['ds_power_max'], thresh=warn['ds_power'])}\n"
            f"- {s['complaint_us_power'].format(val=worst['us_power_max'], thresh=warn['us_power'])}\n"
            f"- {s['complaint_snr'].format(val=worst['ds_snr_min'], thresh=warn['snr'])}\n"
            f"- {s['complaint_uncorr'].format(val='{:,}'.format(worst['ds_uncorrectable_max']))}\n\n"
            f"{s['complaint_exceed']}\n\n"
            f"{s['complaint_request']}\n"
            f"1. {s['complaint_req1']}\n"
            f"2. {s['complaint_req2']}\n"
            f"3. {s['complaint_req3']}\n\n"
        )
    else:
        complaint = (
            f"{s['complaint_short_subject']}\n\n"
            f"{s['complaint_short_greeting']}\n\n"
            f"{s['complaint_short_body']}\n\n"
        )

    # Add BNetzA reference if measurements exist
    if bnetz_list:
        # Pick best measurement (prefer deviation)
        bnetz_data = None
        for m in reversed(bnetz_list):
            if m.get("verdict_download") == "deviation" or m.get("verdict_upload") == "deviation":
                bnetz_data = m
                break
        if not bnetz_data:
            bnetz_data = bnetz_list[-1]

        dl_max = round(bnetz_data.get("download_max_tariff") or 0)
        dl_avg = round(bnetz_data.get("download_measured_avg") or 0)
        dl_pct = round(dl_avg / dl_max * 100) if dl_max else 0
        ul_max = round(bnetz_data.get("upload_max_tariff") or 0)
        ul_avg = round(bnetz_data.get("upload_measured_avg") or 0)
        ul_pct = round(ul_avg / ul_max * 100) if ul_max else 0

        complaint += (
            f"\n{s.get('complaint_bnetz_header', '')}\n\n"
            f"{s.get('complaint_bnetz_body', '').format(date=bnetz_data.get('date', ''))}\n"
            f"- {s.get('complaint_bnetz_dl', '').format(max=dl_max, avg=dl_avg, pct=dl_pct)}\n"
            f"- {s.get('complaint_bnetz_ul', '').format(max=ul_max, avg=ul_avg, pct=ul_pct)}\n"
            f"- {s.get('complaint_bnetz_verdict', '').format(verdict_dl=bnetz_data.get('verdict_download', '-'), verdict_ul=bnetz_data.get('verdict_upload', '-'))}\n\n"
        )
        has_dev = bnetz_data.get("verdict_download") == "deviation" or bnetz_data.get("verdict_upload") == "deviation"
        if has_dev:
            complaint += s.get("complaint_bnetz_legal", "") + "\n\n"

    complaint += f"{s['complaint_escalation']}\n\n{s['complaint_closing']}"

    pdf.multi_cell(0, 4, complaint)

    # Output
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_complaint_text(snapshots, config=None, connection_info=None, lang="en",
                            customer_name="", customer_number="", customer_address="",
                            bnetz_data=None):
    """Generate ISP complaint letter as plain text.

    Args:
        snapshots: List of snapshot dicts
        config: Config dict (isp_name, etc.)
        connection_info: Connection info dict
        lang: Language code
        customer_name: Customer name for letter
        customer_number: Customer/contract number
        customer_address: Customer address
        bnetz_data: Optional BNetzA measurement dict

    Returns:
        str: Complaint letter text
    """
    config = config or {}
    s = REPORT_STRINGS.get(lang, REPORT_STRINGS["en"])
    isp = config.get("isp_name", "Unknown ISP")

    # Build closing with actual customer data
    closing_lines = []
    closing_lines.append(s.get("complaint_closing_label", "Sincerely,"))
    closing_lines.append(customer_name if customer_name else "[Your Name]")
    if customer_number:
        closing_lines.append(customer_number)
    else:
        closing_lines.append("[Customer Number]")
    if customer_address:
        closing_lines.append(customer_address)
    else:
        closing_lines.append("[Address]")
    closing = "\n".join(closing_lines)

    # Build BNetzA section if data provided
    bnetz_section = ""
    if bnetz_data:
        has_deviation = (
            bnetz_data.get("verdict_download") == "deviation"
            or bnetz_data.get("verdict_upload") == "deviation"
        )
        dl_max = round(bnetz_data.get("download_max_tariff") or 0)
        dl_avg = round(bnetz_data.get("download_measured_avg") or 0)
        dl_pct = round(dl_avg / dl_max * 100) if dl_max else 0
        ul_max = round(bnetz_data.get("upload_max_tariff") or 0)
        ul_avg = round(bnetz_data.get("upload_measured_avg") or 0)
        ul_pct = round(ul_avg / ul_max * 100) if ul_max else 0
        bnetz_lines = [
            s.get("complaint_bnetz_header", ""),
            "",
            s.get("complaint_bnetz_body", "").format(date=bnetz_data.get("date", "")),
            "",
            f"- {s.get('complaint_bnetz_tariff', '').format(tariff=bnetz_data.get('tariff', '-'), provider=bnetz_data.get('provider', '-'))}",
            f"- {s.get('complaint_bnetz_dl', '').format(max=dl_max, avg=dl_avg, pct=dl_pct)}",
            f"- {s.get('complaint_bnetz_ul', '').format(max=ul_max, avg=ul_avg, pct=ul_pct)}",
            f"- {s.get('complaint_bnetz_verdict', '').format(verdict_dl=bnetz_data.get('verdict_download', '-'), verdict_ul=bnetz_data.get('verdict_upload', '-'))}",
        ]
        if has_deviation:
            bnetz_lines.append("")
            bnetz_lines.append(s.get("complaint_bnetz_legal", ""))
        bnetz_section = "\n".join(bnetz_lines) + "\n\n"

    if snapshots:
        worst = _compute_worst_values(snapshots)
        warn = _default_warn_thresholds()
        start = snapshots[0]["timestamp"][:10]
        end = snapshots[-1]["timestamp"][:10]
        poor_pct = round(worst['health_poor_count'] / max(worst['total_snapshots'], 1) * 100)
        return (
            f"{s['complaint_subject']}\n\n"
            f"{s['complaint_greeting'].format(isp=isp)}\n\n"
            f"{s['complaint_body'].format(count=len(snapshots), start=start, end=end)}\n\n"
            f"{s['complaint_findings']}\n"
            f"- {s['complaint_poor_rate'].format(poor=worst['health_poor_count'], total=worst['total_snapshots'], pct=poor_pct)}\n"
            f"- {s['complaint_ds_power'].format(val=worst['ds_power_max'], thresh=warn['ds_power'])}\n"
            f"- {s['complaint_us_power'].format(val=worst['us_power_max'], thresh=warn['us_power'])}\n"
            f"- {s['complaint_snr'].format(val=worst['ds_snr_min'], thresh=warn['snr'])}\n"
            f"- {s['complaint_uncorr'].format(val='{:,}'.format(worst['ds_uncorrectable_max']))}\n\n"
            f"{bnetz_section}"
            f"{s['complaint_exceed']}\n\n"
            f"{s['complaint_request']}\n"
            f"1. {s['complaint_req1']}\n"
            f"2. {s['complaint_req2']}\n"
            f"3. {s['complaint_req3']}\n\n"
            f"{s['complaint_escalation']}\n\n"
            f"{closing}"
        )
    elif bnetz_section:
        # No DOCSIS snapshots but BNetzA data available
        return (
            f"{s['complaint_subject']}\n\n"
            f"{s['complaint_greeting'].format(isp=isp)}\n\n"
            f"{bnetz_section}"
            f"{s['complaint_request']}\n"
            f"1. {s['complaint_req1']}\n"
            f"2. {s['complaint_req2']}\n"
            f"3. {s['complaint_req3']}\n\n"
            f"{s['complaint_escalation']}\n\n"
            f"{closing}"
        )
    else:
        return (
            f"{s['complaint_short_subject']}\n\n"
            f"{s['complaint_short_greeting']}\n\n"
            f"{s['complaint_short_body']}\n\n"
            f"{closing}"
        )
