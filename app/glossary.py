"""Canonical in-app glossary data model and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

GLOSSARY_LEVELS: tuple[str, ...] = ("eli5", "basic", "advanced", "technician")


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """Return non-empty strings with stable order and case-insensitive de-duplication."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


@dataclass(frozen=True)
class GlossaryTerm:
    """A canonical glossary term with stable IDs and multi-level explanations."""

    id: str
    category: str
    title: dict[str, str]
    aliases: dict[str, tuple[str, ...]]
    levels: dict[str, dict[str, str]]
    misconceptions: dict[str, tuple[str, ...]]
    related: tuple[str, ...]
    protected_terms: tuple[str, ...]
    tags: tuple[str, ...] = ()
    source_pages: tuple[str, ...] = ()
    ui_contexts: tuple[str, ...] = ()
    media: tuple[dict[str, Any], ...] = ()

    def localized(self, lang: str = "en") -> dict[str, Any]:
        """Return a template-friendly localized term, falling back to English."""
        translation = _localized_term_payload(self.id, lang)
        title = translation.get("title") or self.title.get(lang) or self.title["en"]
        metadata = _metadata_for_term(self.id)
        aliases = tuple(translation.get("aliases") or self.aliases.get(lang) or self.aliases.get("en", ()))
        aliases = _unique((*aliases, *metadata.get("aliases", ())))
        translated_levels = translation.get("levels") if isinstance(translation.get("levels"), dict) else {}
        native_levels = self.levels.get(lang, {})
        english_levels = self.levels["en"]
        levels = {
            level: (
                str(translated_levels.get(level) or native_levels.get(level) or english_levels.get(level) or "").strip()
            )
            for level in GLOSSARY_LEVELS
        }
        misconceptions = tuple(translation.get("misconceptions") or self.misconceptions.get(lang) or self.misconceptions.get("en", ()))
        media = translation.get("media") if isinstance(translation.get("media"), list) else list(self.media)
        return {
            "id": self.id,
            "category": self.category,
            "title": title,
            "aliases": list(aliases),
            "levels": dict(levels),
            "misconceptions": list(misconceptions),
            "related": list(self.related),
            "protected_terms": list(self.protected_terms),
            "tags": list(_unique((*self.tags, *metadata.get("tags", ())))),
            "source_pages": list(_unique((*self.source_pages, *metadata.get("source_pages", ())))),
            "ui_contexts": list(_unique((*self.ui_contexts, *metadata.get("ui_contexts", ())))),
            "media": media,
        }


@dataclass(frozen=True)
class GlossaryCategory:
    """A glossary category for browsing and future filtering."""

    id: str
    title: dict[str, str]
    description: dict[str, str]

    def localized(self, lang: str = "en") -> dict[str, str]:
        translation = _localized_category_payload(self.id, lang)
        return {
            "id": self.id,
            "title": translation.get("title") or self.title.get(lang) or self.title["en"],
            "description": translation.get("description") or self.description.get(lang) or self.description["en"],
        }


_CATEGORY_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("docsis_terms", "DOCSIS terms", "Cable/DOCSIS protocol, signal, channel, and event terms that DOCSight explains."),
    ("docsight_features", "DOCSight features", "Views, integrations, and evidence tools provided by DOCSight itself."),
)

_CATEGORIES: tuple[GlossaryCategory, ...] = tuple(
    GlossaryCategory(id=category_id, title={"en": title}, description={"en": description})
    for category_id, title, description in _CATEGORY_DEFINITIONS
)

def _term(
    term_id: str,
    category: str,
    title: str,
    aliases: tuple[str, ...],
    protected_terms: tuple[str, ...],
    related: tuple[str, ...],
    eli5: str,
    basic: str,
    advanced: str,
    technician: str,
    misconceptions: tuple[str, ...] = (),
) -> GlossaryTerm:
    """Create an English glossary term without repeating the locale container shape."""
    return GlossaryTerm(
        id=term_id,
        category=category,
        title={"en": title},
        aliases={"en": aliases},
        protected_terms=protected_terms,
        related=related,
        levels={
            "en": {
                "eli5": eli5,
                "basic": basic,
                "advanced": advanced,
                "technician": technician,
            }
        },
        misconceptions={"en": misconceptions} if misconceptions else {},
    )

_TERMS: tuple[GlossaryTerm, ...] = (
    _term(
        'docsis',
        'docsis_terms',
        'DOCSIS',
        ('Cable internet', 'Data Over Cable Service Interface Specification'),
        ('DOCSIS', 'DSL', 'DOCSight'),
        ('downstream', 'upstream', 'sc_qam', 'ofdm', 'ofdma', 'cmts', 'shared_medium'),
        'DOCSIS is the cable-internet language spoken by a cable modem and the provider network.',
        'DOCSIS carries internet service over coax cable. DOCSight reads modem, channel, and signal data from supported DOCSIS devices, so its evidence is about the cable access link rather than DSL.',
        'DOCSIS uses a mix of downstream and upstream channel families such as SC-QAM, OFDM, and OFDMA. Each family exposes different evidence, so DOCSight keeps channel type, direction, and support status separate.',
        'Use DOCSIS evidence as modem-side RF/MAC context: channel lock, power, MER/SNR, modulation, errors, and events. Provider provisioning, CMTS policy, segment load, and IP routing still need explicit supporting sources.',
        ('DOCSIS is not DSL; DOCSIS channel values should not be read like DSL sync values.',),
    ),
    _term(
        'downstream',
        'docsis_terms',
        'Downstream',
        ('Download direction', 'DS', 'Downstream channels'),
        ('DOCSIS', 'SC-QAM', 'OFDM'),
        ('upstream', 'sc_qam', 'ofdm', 'power_level', 'snr_mer'),
        'Downstream is data traveling from the provider network toward your modem.',
        'Downstream channels carry downloads and other inbound traffic. DOCSight shows their lock state and signal quality separately from upstream channels.',
        'Downstream evidence can come from SC-QAM and OFDM channels. Power, SNR/MER, modulation/profile data, and channel lock describe whether the modem can receive the carrier cleanly.',
        'Investigate downstream issues by correlating affected channels, MER/SNR changes, correctable/uncorrectable growth, OFDM profile changes, and event timestamps instead of treating one receive value as the whole diagnosis.',
    ),
    _term(
        'upstream',
        'docsis_terms',
        'Upstream',
        ('Upload direction', 'US', 'Upstream channels'),
        ('DOCSIS', 'SC-QAM', 'OFDMA'),
        ('downstream', 'ofdma', 'power_level', 'return_path_interference', 't3_t4_timeout'),
        'Upstream is data traveling from your modem back toward the provider network.',
        'Upstream channels carry uploads, requests, and modem ranging. DOCSight uses them as upload-side signal evidence.',
        'Upstream may use SC-QAM or OFDMA. Transmit power, modulation drops, ranging behavior, and return-path noise symptoms often matter more than download-side values.',
        'For upstream faults, compare power shifts, channel drops, OFDMA support gaps, T3/T4 events, and latency or packet-loss windows. Missing upstream fields mean unsupported or not reported, not automatically zero.',
    ),
    _term(
        'channel_bonding',
        'docsis_terms',
        'Channel bonding',
        ('Bonded channels', 'Channel bundle', 'DOCSIS bonding'),
        ('DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('downstream', 'upstream', 'sc_qam', 'ofdm', 'ofdma'),
        'Channel bonding lets a modem use several cable channels together.',
        'DOCSIS modems often use multiple downstream and upstream channels at once. DOCSight groups visible channels so you can see what is bonded, locked, and healthy.',
        'Bonding combines channel capacity, but the usable result depends on direction, channel family, lock state, profiles, scheduler behavior, and service configuration.',
        'When reviewing bonding evidence, look for missing or degraded members in the bundle, family-specific health, and whether symptoms affect one channel, one direction, or the whole service group.',
    ),
    _term(
        'sc_qam',
        'docsis_terms',
        'SC-QAM',
        ('Single-carrier QAM', 'DOCSIS 3.0 channel', 'QAM channel'),
        ('SC-QAM', 'DOCSIS', 'QAM'),
        ('qam_modulation_order', 'channel_bonding', 'ofdm', 'mixed_mode'),
        'SC-QAM is the classic narrow DOCSIS channel type.',
        'SC-QAM channels are traditional DOCSIS 3.0-style channels. DOCSight can usually show their power, SNR/MER, modulation, lock state, and health.',
        'SC-QAM uses one carrier with a fixed channel width and a QAM order. That makes gross channel context more straightforward than profile-based OFDM/OFDMA, when the modem exposes enough fields.',
        'Use SC-QAM rows to isolate channel-specific impairment: compare adjacent channels, modulation changes, MER/SNR, and error growth before escalating from a single poor value to a plant-wide conclusion.',
    ),
    _term(
        'ofdm',
        'docsis_terms',
        'OFDM',
        ('DOCSIS 3.1 downstream', 'Orthogonal frequency-division multiplexing'),
        ('OFDM', 'DOCSIS', 'SC-QAM'),
        ('ofdma', 'sc_qam', 'mixed_mode', 'qam_modulation_order'),
        'OFDM is the DOCSIS 3.1 downstream channel type made from many small subcarriers.',
        'DOCSIS 3.1 uses OFDM for wide downstream receive channels. DOCSight labels it separately because OFDM evidence differs from classic SC-QAM rows.',
        'OFDM health depends on profiles, excluded subcarriers, PLC/lock state, and profile availability. Missing profile information should stay unknown instead of being filled with guessed capacity.',
        'For OFDM diagnostics, compare profile changes, MER-like indicators, codeword/error behavior, and adjacent SC-QAM evidence. Treat unsupported profile fields as a data boundary, not as proof of good or bad service.',
    ),
    _term(
        'ofdma',
        'docsis_terms',
        'OFDMA',
        ('DOCSIS 3.1 upstream', 'Orthogonal frequency-division multiple access'),
        ('OFDMA', 'DOCSIS', 'SC-QAM'),
        ('ofdm', 'upstream', 'mixed_mode', 'return_path_interference'),
        'OFDMA is the DOCSIS 3.1 upstream channel type.',
        'OFDMA lets many modems share parts of a wide upstream block. DOCSight labels it separately from SC-QAM upstream channels.',
        'OFDMA depends on profiles, subcarriers, minislots, return-path noise, and scheduler context. Missing, None, or null fields mean unsupported or not reported, not measured zero.',
        'Diagnose OFDMA with upstream events, transmit behavior, profile availability, and latency/loss timing. Avoid SC-QAM-style capacity guesses unless the modem exposes the required OFDMA details.',
    ),
    _term(
        'mixed_mode',
        'docsis_terms',
        'Mixed mode (3.0 + 3.1)',
        ('DOCSIS 3.0 + 3.1', 'Mixed DOCSIS mode', 'SC-QAM plus OFDM'),
        ('DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('docsis', 'sc_qam', 'ofdm', 'ofdma', 'channel_bonding'),
        'Mixed mode means DOCSIS 3.0 and DOCSIS 3.1 channel types appear together.',
        'Many modern modems show SC-QAM channels next to OFDM downstream or OFDMA upstream. DOCSight keeps those families separate in the evidence.',
        'Mixed mode is normal during DOCSIS 3.1 deployments. Totals across SC-QAM, OFDM, and OFDMA should not be collapsed into one invented health or capacity number.',
        'When mixed mode looks odd, check whether only one family or direction is degraded. A clean SC-QAM set does not prove OFDM/OFDMA is healthy, and a missing 3.1 field may only mean unsupported reporting.',
    ),
    _term(
        'qam_modulation_order',
        'docsis_terms',
        'QAM / modulation order',
        ('QAM', '256-QAM', '4096-QAM', 'Modulation'),
        ('QAM', 'DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('sc_qam', 'qpsk', 'snr_mer', 'ofdm', 'ofdma'),
        'Modulation is how much data is packed into each cable signal step.',
        'Higher QAM levels can carry more bits per symbol, but they need a cleaner signal. DOCSight shows modulation so drops or low-QAM states are visible.',
        'QAM order must be interpreted with channel family and SNR/MER. SC-QAM has a simpler fixed-channel relationship than OFDM/OFDMA profile-based channels.',
        'Use modulation changes as evidence, not as an isolated verdict. Correlate them with MER/SNR, power, error growth, channel family, and whether the value is current or only the modem’s last reported state.',
    ),
    _term(
        'qpsk',
        'docsis_terms',
        'QPSK (4QAM)',
        ('4QAM', 'Quadrature Phase Shift Keying'),
        ('QPSK', 'QAM', 'DOCSIS'),
        ('qam_modulation_order', 'upstream', 'snr_mer', 'return_path_interference'),
        'QPSK, shown as 4QAM, is a very low modulation level.',
        'In DOCSIS, an upstream drop to 4QAM/QPSK usually means the signal quality is severely degraded. DOCSight displays it as 4QAM to match other modulation labels.',
        'QPSK carries 2 bits per symbol and is far less efficient than higher QAM orders. It is most useful when seen as a fallback state rather than as normal capacity evidence.',
        'Treat QPSK as a strong upstream impairment clue when it aligns with high transmit power, low MER/SNR, T3/T4 events, return-path noise, or packet-loss windows.',
    ),
    _term(
        'power_level',
        'docsis_terms',
        'Power level',
        ('Signal level', 'dBmV', 'Receive power', 'Transmit power'),
        ('dBmV',),
        ('downstream', 'upstream', 'snr_mer', 'return_path_interference'),
        'Power level says how strong the cable signal looks, or how hard the modem must talk back.',
        'DOCSight can show downstream receive power and upstream transmit power when the modem reports them. The two directions mean different things.',
        'Power must be interpreted by direction and channel type. A downstream receive level, an upstream transmit level, and an OFDMA report-power field are not interchangeable measurements.',
        'Use power evidence with MER/SNR, modulation, lock state, splitters/cabling history, and timing. Do not turn unsupported or missing power fields into zero-valued measurements.',
    ),
    _term(
        'snr_mer',
        'docsis_terms',
        'SNR/MER',
        ('Signal-to-noise ratio', 'Modulation error ratio', 'MER', 'SNR'),
        ('SNR', 'MER', 'DOCSIS', 'QAM'),
        ('power_level', 'qam_modulation_order', 'correctable_errors', 'uncorrectable_errors'),
        'SNR/MER describes how clearly the modem can hear the signal through noise.',
        'SNR and MER are signal-quality measurements. Better values usually mean the modem can decode the channel more reliably.',
        'SNR/MER gains meaning when read with modulation, channel family, error counters, and time trends. One clean value can hide intermittent noise or profile changes.',
        'For escalation, capture MER/SNR together with affected channel IDs, timestamps, error-rate changes, power, and events. Avoid mixing SNR/MER semantics across channel families without checking what the modem actually reports.',
    ),
    _term(
        'correctable_errors',
        'docsis_terms',
        'Correctable errors',
        ('Correctables', 'Corrected codewords', 'FEC corrected'),
        ('DOCSIS', 'FEC', 'DOCSight'),
        ('uncorrectable_errors', 'snr_mer', 'power_level'),
        'Correctable errors are signal mistakes the modem could repair.',
        'Correctable counters can rise even on a working line. DOCSight makes them useful by showing rate, timing, affected channels, and whether uncorrectables also rise.',
        'Correctables show FEC work, not direct packet loss. Recent growth during noise events is stronger evidence than a large cumulative total left over from the past.',
        'Compare corrected-codeword growth by channel and time window. Pair it with MER/SNR, modulation, and uncorrectables to separate harmless background correction from an active impairment.',
        ('A high old correctable total is not automatically an active fault.',),
    ),
    _term(
        'uncorrectable_errors',
        'docsis_terms',
        'Uncorrectable errors',
        ('Uncorrectables', 'Uncorrected codewords', 'FEC uncorrected'),
        ('DOCSIS', 'FEC'),
        ('correctable_errors', 'snr_mer', 'power_level'),
        'Uncorrectable errors are signal mistakes the modem could not repair.',
        'Uncorrectables can mean lost channel-level data, especially when they grow during the observation window. DOCSight treats growth and timing as more important than one old total.',
        'Evidence should keep raw cumulative counters separate from derived growth. Resets, wraparound, and modem reboots can change raw totals without representing a new outage.',
        'Use uncorrectables as escalation evidence when fresh growth aligns with low MER/SNR, modulation drops, event logs, or user-visible latency/loss. Preserve the raw counter when exporting evidence.',
        ('A single old uncorrectable total does not prove a current fault by itself.',),
    ),
    _term(
        't3_t4_timeout',
        'docsis_terms',
        'T3 / T4 timeout',
        ('T3 timeout', 'T4 timeout', 'Ranging timeout', 'DOCSIS timeout'),
        ('T3', 'T4', 'DOCSIS', 'CMTS'),
        ('upstream', 'return_path_interference', 'event_log'),
        'T3 and T4 timeouts are modem events where communication with the provider side was interrupted.',
        'A T3 timeout usually means a missed ranging response; a T4 timeout is more severe and can lead to a resync. DOCSight uses them as timing evidence.',
        'Timeouts are upstream/MAC-layer clues. They become more meaningful when they line up with transmit-power changes, return-path noise, channel loss, or a modem resynchronization.',
        'Read T3/T4 events with exact timestamps, maintenance windows, upstream channel state, and incident notes. A repeated T4 pattern is stronger evidence than one isolated historical event.',
    ),
    _term(
        'cmts',
        'docsis_terms',
        'CMTS',
        ('Cable Modem Termination System', 'Provider headend'),
        ('CMTS', 'DOCSIS', 'DOCSight'),
        ('docsis', 'vcmts', 'remote_phy', 'shared_medium'),
        'The CMTS is the provider-side system your cable modem talks to.',
        'A CMTS or related access system manages DOCSIS modems, channels, scheduling, and service configuration. DOCSight usually sees only the modem side.',
        'CMTS/CCAP behavior can affect channel availability, profiles, scheduling, and provisioning, but those provider-side decisions are only partly visible through modem telemetry.',
        'Do not infer exact CMTS state from modem evidence alone. Use CMTS-related wording only when supported by explicit provider data, event context, or modem fields that actually expose it.',
    ),
    _term(
        'vcmts',
        'docsis_terms',
        'vCMTS',
        ('Virtual CMTS', 'Software CMTS', 'CableOS'),
        ('vCMTS', 'CMTS', 'DOCSIS'),
        ('cmts', 'remote_phy', 'docsis'),
        'A vCMTS is a software-based CMTS used in modern cable networks.',
        'A vCMTS provides CMTS functions on server infrastructure instead of only dedicated hardware. DOCSight treats it as provider-side context.',
        'vCMTS architectures can change where control-plane and scheduling functions run, but local modem evidence still shows only the customer-side view of that system.',
        'Mention vCMTS only as architecture context unless the provider or modem exposes direct evidence. It should not be used to explain a fault without matching channel, event, or support data.',
    ),
    _term(
        'remote_phy',
        'docsis_terms',
        'Remote PHY',
        ('R-PHY', 'Remote PHY device', 'RPD'),
        ('Remote PHY', 'DOCSIS', 'CMTS'),
        ('cmts', 'vcmts', 'node_segment'),
        'Remote PHY moves some cable-network RF work closer to the neighborhood.',
        'In modern cable networks, Remote PHY can place PHY-layer functions in a remote node while the provider controls the service centrally. DOCSight normally sees modem-side effects only.',
        'R-PHY/RPD and vCMTS designs split PHY and MAC responsibilities differently from older headend-only systems. That changes topology, not the meaning of the modem’s local signal evidence.',
        'Avoid guessing exact R-PHY placement from DOCSight alone. Use it as context for provider discussions while relying on modem-visible channels, events, and timing for evidence.',
    ),
    _term(
        'return_path_interference',
        'docsis_terms',
        'Rückwegstörer',
        ('Return-path interferer', 'Return path noise', 'Upstream ingress'),
        ('DOCSIS', 'SNR', 'MER', 'OFDMA'),
        ('upstream', 'power_level', 't3_t4_timeout', 'snr_mer'),
        'A Rückwegstörer is noise that disturbs the upstream path back to the provider.',
        'Return-path interference can make uploads and modem ranging unstable. DOCSight can show symptoms such as upstream power changes, lower modulation, T3/T4 events, or packet loss.',
        'Return-path ingress is often shared and intermittent. It may affect several modems in a segment and may only appear during certain time windows or noisy in-home/device conditions.',
        'Localize return-path issues by correlating upstream symptoms with event times and, when available, provider spectrum or plant evidence. DOCSight alone can show symptoms, not the exact ingress source.',
    ),
    _term(
        'node_segment',
        'docsis_terms',
        'Node / segment',
        ('Segment', 'Service group', 'Cable node', 'Node split'),
        ('DOCSIS', 'CMTS', 'DOCSight'),
        ('shared_medium', 'segment_utilization', 'remote_phy'),
        'A node or segment is the part of the cable network shared by a group of homes.',
        'People in the same cable segment share some access-network capacity. A node split can reduce the number of users sharing the same resources.',
        'Service-group boundaries influence contention, channel load, and upgrade planning. A local modem can show symptoms but not the full segment population or provider scheduler state.',
        'Use segment language carefully: prove local signal health first, then compare timing, speed/latency evidence, and provider information before calling a problem segment utilization.',
    ),
    _term(
        'shared_medium',
        'docsis_terms',
        'Shared medium',
        ('Cable segment', 'Shared access network'),
        ('DOCSIS', 'CMTS', 'DOCSight'),
        ('node_segment', 'segment_utilization', 'speedtest'),
        'Cable internet shares parts of the neighborhood access network with other users.',
        'A shared medium can be busy even when your own modem signal looks clean. DOCSight separates local modem evidence from provider-side utilization claims.',
        'Shared-medium behavior depends on service-group size, scheduling, channel capacity, active demand, and provider policy. One modem cannot measure the whole segment directly.',
        'Distinguish clean RF evidence from congestion evidence. Correlate time-of-day patterns, speedtest/BQM/monitoring data, and provider feedback before treating shared medium as the root cause.',
        ('A good signal level does not prove that the provider segment is uncongested.',),
    ),
    _term(
        'health_status',
        'docsis_terms',
        'Health status',
        ('Good', 'Marginal', 'Poor', 'Signal health', 'Channel health'),
        ('DOCSight', 'DOCSIS', 'SNR', 'dBmV'),
        ('power_level', 'snr_mer', 'correctable_errors', 'uncorrectable_errors'),
        'Health status is DOCSight’s quick good/marginal/poor label for visible evidence.',
        'Health status summarizes modem-visible evidence such as power, SNR/MER, channel lock, and errors. It is a triage label, not a provider fault verdict by itself.',
        'The label compresses several signals for scanning, so it can hide which specific metric drove the result. Raw values, timestamps, and channel details remain the source of truth.',
        'Use health status as the entry point, then verify the underlying metric, affected channel family, trend, and event context before exporting or escalating the finding.',
    ),
    _term(
        'dashboard',
        'docsight_features',
        'Dashboard',
        ('Home view', 'Overview'),
        (),
        ('health_status', 'power_level', 'snr_mer', 'event_log', 'gaming_index'),
        'Dashboard is DOCSight’s main overview of the current cable-connection evidence.',
        'The dashboard combines status, modem/provider info, signal cards, channel tables, recent events, and optional speed or gaming evidence in one place.',
        'The dashboard is an evidence summary, not a new DOCSIS source. It correlates supported data and keeps unsupported fields visible as missing or unknown instead of filling gaps.',
        'Use the dashboard to choose the next drilldown: signal cards for RF symptoms, channel tables for per-channel detail, events for timing, and external measurements for user-impact correlation.',
    ),
    _term(
        'in_app_glossary',
        'docsight_features',
        'In-App Glossary',
        ('Glossary', 'Contextual help'),
        (),
        ('dashboard', 'docsis', 'power_level'),
        'In-App Glossary explains DOCSIS and DOCSight words without leaving the app.',
        'The glossary links dashboard labels and help icons to plain-language explanations, aliases, and related terms.',
        'Glossary entries keep DOCSIS terms separate from DOCSight features so explanatory bridges do not become invented protocol facts.',
        'Use glossary links as context for evidence review, not as a diagnostic result. The selected article should clarify what a metric means before you judge the live data.',
    ),
    _term(
        'channel_timeline',
        'docsight_features',
        'Channel Timeline',
        ('Timeline', 'Channel history'),
        (),
        ('downstream', 'upstream', 'signal_trends'),
        'Channel Timeline shows how channel state changed over time.',
        'Channel Timeline makes drops, lock changes, and signal shifts easier to compare across observation windows.',
        'A timeline can separate persistent impairment from a short transition, resync, maintenance window, or reporting gap. It depends on the snapshots DOCSight actually collected.',
        'Use the timeline to line up channel changes with events, error growth, speed/latency evidence, and user notes before deciding whether a channel problem is current.',
    ),
    _term(
        'signal_trends',
        'docsight_features',
        'Signal Trends',
        ('Signal history', 'Trend charts'),
        (),
        ('power_level', 'snr_mer', 'channel_timeline'),
        'Signal Trends turns repeated modem readings into graphs.',
        'Signal Trends shows time-series views for power, SNR/MER, errors, and related signal evidence.',
        'Trends make drift, intermittent noise, and before/after changes visible. They also show where evidence is missing because no sample or supported field was available.',
        'Use trend windows to export when a value changed, how long it persisted, and whether other metrics moved at the same time. Avoid averaging away short but important spikes.',
    ),
    _term(
        'modulation_performance',
        'docsight_features',
        'Modulation Performance',
        ('Modulation view', 'QAM performance'),
        ('DOCSight', 'QAM'),
        ('qam_modulation_order', 'sc_qam', 'ofdm', 'ofdma'),
        'Modulation Performance shows whether channels are using strong or degraded modulation.',
        'The view focuses on QAM and channel-family behavior so degraded modulation and capacity-sensitive signal problems are easier to spot.',
        'For DOCSIS 3.1 upstream Low-QAM, DOCSight treats ≤64QAM as the low-QAM boundary. OFDM/OFDMA profile data remains separate from DOCSIS 3.0 SC-QAM color semantics.',
        'Use this view to identify which family or direction is downshifting, then confirm with MER/SNR, power, errors, and event timing before assigning a fault cause.',
    ),
    _term(
        'segment_utilization',
        'docsight_features',
        'Segment Utilization',
        ('Segment load', 'Node load'),
        (),
        ('shared_medium', 'node_segment', 'speedtest'),
        'Segment Utilization helps separate your modem signal from shared-segment load clues.',
        'The view compares local signal evidence with supported utilization or performance signals when those data sources are available.',
        'Unknown remains a visible category and stays in distribution denominators. Dropping it would make the available samples look more certain than they are.',
        'Use this view only with its evidence boundary: supported samples, unknown buckets, missing data, and external performance measurements must remain separate in exports and explanations.',
    ),
    _term(
        'correlation_analysis',
        'docsight_features',
        'Correlation Analysis',
        ('Correlation view', 'Signal correlation'),
        (),
        ('signal_trends', 'speedtest', 'event_log'),
        'Correlation Analysis shows which symptoms happened at the same time.',
        'It compares signal, error, event, speed, and external evidence over time so matching problem windows are easier to see.',
        'Correlation is not causation. The view can strengthen a hypothesis when independent evidence lines up, but it does not invent provider-side facts that were not measured.',
        'Use correlation output to build an evidence chain: timestamp, symptom, affected metric, user impact, and supporting source. Keep unrelated coincidental changes out of the escalation story.',
    ),
    _term(
        'before_after_comparison',
        'docsight_features',
        'Before/After Comparison',
        ('Comparison view', 'Repair comparison'),
        (),
        ('signal_trends', 'incident_journal', 'dashboard'),
        'Before/After Comparison shows what changed around a repair, reboot, or provider visit.',
        'It compares snapshots around a chosen change so improvements and regressions are visible.',
        'A before/after view is strongest when both sides use comparable sample windows and supported metrics. Different windows or missing fields can mislead.',
        'Use it after changes such as splitters, cable work, modem restarts, or provider maintenance. Export the compared timestamps and unchanged metrics as well as the improved ones.',
    ),
    _term(
        'connection_monitor',
        'docsight_features',
        'Connection Monitor',
        ('Ping monitor', 'Availability monitor'),
        (),
        ('speedtest', 'event_log', 'incident_journal'),
        'Connection Monitor watches whether the connection stays reachable and responsive.',
        'It tracks reachability and latency over time, making dropouts and timing evidence easier to export and discuss.',
        'Monitor evidence reflects end-to-end reachability to the chosen target, not only DOCSIS RF health. A clean modem signal can still coincide with latency or routing symptoms.',
        'Use monitor windows with event logs and signal trends. Separate target outages, local LAN issues, and access-network symptoms before treating a latency spike as DOCSIS evidence.',
    ),
    _term(
        'event_log',
        'docsight_features',
        'Event Log',
        ('Events', 'Modem events'),
        (),
        ('t3_t4_timeout', 'connection_monitor', 'incident_journal'),
        'Event Log is the place where recent modem or app-visible events are collected.',
        'It helps timeouts, resyncs, and other symptoms be compared with signal changes and user impact.',
        'Event severity depends on type, frequency, timing, and surrounding signal state. A single old event is weaker evidence than a repeated pattern during an incident window.',
        'Use exact event timestamps and messages when escalating. Pair them with channel state, trends, and notes so the log supports a timeline instead of standing alone.',
    ),
    _term(
        'incident_journal',
        'docsight_features',
        'Incident Journal',
        ('Journal', 'ISP evidence journal'),
        (),
        ('event_log', 'connection_monitor', 'before_after_comparison'),
        'Incident Journal is where DOCSight keeps notes and evidence about connection problems.',
        'It records incidents, observations, and supporting data for troubleshooting or provider escalation.',
        'Journal entries are strongest when they combine user impact, exact time windows, and measured evidence instead of only free-text complaints.',
        'Use the journal to preserve context across visits or support calls: symptom, timestamp, affected service, exported evidence, and what changed after each intervention.',
    ),
    _term(
        'smart_capture',
        'docsight_features',
        'Smart Capture',
        ('Capture', 'Evidence capture'),
        (),
        ('incident_journal', 'dashboard', 'signal_trends'),
        'Smart Capture collects relevant DOCSight evidence around a problem window.',
        'It helps avoid relying on one isolated screenshot by gathering the data sources that matter for an incident.',
        'A capture is only as reliable as the supported sources available at that time. Missing or unsupported fields should remain visible instead of being replaced by guesses.',
        'Use captures for repeatable escalation packages: include the trigger time, collected snapshots, events, trends, and any external monitor data that covers the same window.',
    ),
    _term(
        'speedtest',
        'docsight_features',
        'Speedtest',
        ('Speed test', 'Throughput test'),
        (),
        ('dashboard', 'segment_utilization', 'gaming_index'),
        'Speedtest measures the throughput and latency a user sees during a test.',
        'DOCSight can record download, upload, latency, and jitter so user-visible performance can be compared with DOCSIS evidence.',
        'A speedtest measures end-to-end IP performance at one moment. It is not the same as DOCSIS channel capacity, tariff speed, or local RF health.',
        'Interpret speedtest results with test server, time of day, connection monitor data, segment clues, and modem evidence. Avoid using one low result as proof of a DOCSIS signal fault.',
    ),
    _term(
        'bqm',
        'docsight_features',
        'BQM',
        ('Broadband Quality Monitor', 'ThinkBroadband BQM'),
        (),
        ('connection_monitor', 'incident_journal', 'correlation_analysis'),
        'BQM adds an external view of latency and packet loss over time.',
        'The BQM integration brings external latency/loss monitoring into DOCSight so packet-loss windows can be compared with modem evidence.',
        'BQM observes reachability from outside the home network toward the monitored endpoint. It complements modem data but does not identify the DOCSIS layer by itself.',
        'Use BQM for timing correlation: match loss blocks with DOCSIS events, signal trends, and user reports. Treat monitor-target or routing caveats separately.',
    ),
    _term(
        'smokeping',
        'docsight_features',
        'Smokeping',
        ('SmokePing', 'Latency graph'),
        (),
        ('connection_monitor', 'bqm', 'correlation_analysis'),
        'Smokeping adds latency history as another evidence source.',
        'Smokeping support lets DOCSight use latency history for intermittent connectivity problems.',
        'Latency-history tools show timing and packet-loss patterns, not the physical cause. Their value increases when they overlap with modem or event evidence.',
        'Use Smokeping traces to confirm when symptoms began, how long they lasted, and whether they align with RF or DOCSIS events before adding them to an escalation package.',
    ),
    _term(
        'bnetza',
        'docsight_features',
        'BNetzA measurement',
        ('Broadband measurement', 'Bundesnetzagentur measurement'),
        (),
        ('speedtest', 'incident_journal', 'before_after_comparison'),
        'BNetzA measurement attaches official broadband-measurement evidence to DOCSight.',
        'BNetzA measurement support helps place official throughput evidence on DOCSight’s diagnostic timeline.',
        'Official measurement data is a performance record, not a DOCSIS channel reading. It should be compared with modem evidence rather than merged into signal health.',
        'Use BNetzA results as formal user-impact evidence alongside time-matched DOCSight snapshots, monitor data, and incident notes. Keep measurement method and timestamp visible.',
    ),
    _term(
        'gaming_index',
        'docsight_features',
        'Gaming Index',
        ('Gaming Quality Index', 'Gaming quality', 'Latency quality'),
        (),
        ('dashboard', 'speedtest', 'health_status'),
        'Gaming Index is a quick signal for latency-sensitive quality.',
        'It combines latency-sensitive evidence with DOCSIS health when available, so gaming-style problems are easier to spot.',
        'The index is a summary signal, not a replacement for the underlying latency, jitter, loss, and modem-health data. Missing inputs should stay explicit.',
        'Use the index as a triage shortcut, then verify the raw latency/loss window, DOCSIS status, and external measurements before drawing conclusions for real-time applications.',
    ),
    _term(
        'llm_export',
        'docsight_features',
        'LLM Export',
        ('AI export', 'Support export'),
        (),
        ('incident_journal', 'correlation_analysis', 'smart_capture'),
        'LLM Export packages selected DOCSight evidence into support-friendly text.',
        'It creates a focused text export so diagnostics can be reviewed without exposing unrelated app state.',
        'The export should preserve evidence boundaries: raw values, derived summaries, timestamps, and unsupported fields must stay distinguishable.',
        'Review an export before sharing it. Confirm it includes the relevant incident window and excludes unrelated or sensitive details that do not help the support case.',
    ),
    _term(
        'doctor_diagnostics',
        'docsight_features',
        'Doctor Diagnostics',
        ('Doctor', 'Diagnostics'),
        (),
        ('dashboard', 'incident_journal', 'smart_capture'),
        'Doctor Diagnostics guides checks for DOCSight setup and evidence collection.',
        'It helps separate configuration problems, modem-access problems, and actual line symptoms.',
        'Doctor checks are diagnostic scaffolding. They can confirm whether DOCSight can collect evidence, but they do not replace the evidence from modem data and incident windows.',
        'Use Doctor output before deep troubleshooting to verify setup, permissions, storage, integrations, and modem reachability. Then move to signal/event evidence for the actual fault question.',
    ),
    _term(
        'pwa_offline',
        'docsight_features',
        'PWA and Offline Mode',
        ('PWA', 'Offline shell'),
        (),
        ('dashboard', 'in_app_glossary'),
        'PWA and Offline Mode make DOCSight installable and usable as an app shell.',
        'They keep the app structure available while avoiding stale live data pretending to be current.',
        'Offline behavior is a freshness boundary. Cached pages can explain terms or show saved structure, but live modem status requires current collection data.',
        'When troubleshooting from an installed PWA, verify whether the view is online and freshly updated before using it as evidence. Do not escalate cached stale data as current status.',
    ),
)

_GLOSSARY_WIKI_INDEX: dict[str, dict[str, tuple[str, ...]]] = {
    'docsis': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('docsis', 'cable-internet', 'access-layer', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_basics', 'channel_tables'),
        'aliases': ('DOCSIS 3.0', 'DOCSIS 3.1', 'DOCSIS 4.0'),
    },
    'downstream': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('direction', 'download', 'channels', 'wiki-term'),
        'ui_contexts': ('dashboard_signal_cards', 'channel_tables'),
    },
    'upstream': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('direction', 'upload', 'channels', 'return-path', 'wiki-term'),
        'ui_contexts': ('dashboard_signal_cards', 'channel_tables'),
    },
    'channel_bonding': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('channels', 'bonding', 'wiki-term'),
        'ui_contexts': ('channel_tables',),
        'aliases': ('Channels',),
    },
    'sc_qam': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('sc-qam', 'docsis-3.0', 'modulation', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_group', 'modulation_view', 'channel_tables'),
    },
    'ofdm': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('ofdm', 'docsis-3.1', 'downstream', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_group', 'modulation_view', 'channel_tables'),
    },
    'ofdma': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('ofdma', 'docsis-3.1', 'upstream', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_group', 'modulation_view', 'channel_tables'),
    },
    'mixed_mode': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('mixed-mode', 'docsis-3.0', 'docsis-3.1', 'wiki-term'),
        'ui_contexts': ('channel_tables', 'modulation_view'),
    },
    'qam_modulation_order': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('modulation', 'qam', 'wiki-term'),
        'ui_contexts': ('modulation_view', 'channel_tables'),
    },
    'qpsk': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('qpsk', '4qam', 'modulation', 'wiki-term'),
        'ui_contexts': ('modulation_view', 'upstream_channels'),
    },
    'power_level': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('signal', 'ds-power', 'us-power', 'dbmv', 'wiki-term'),
        'ui_contexts': ('dashboard_signal_cards', 'channel_tables'),
        'aliases': ('DS Power', 'US Power'),
    },
    'snr_mer': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('signal', 'snr', 'mer', 'noise', 'wiki-term'),
        'ui_contexts': ('dashboard_signal_cards', 'channel_tables'),
    },
    'correctable_errors': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('errors', 'fec', 'codewords', 'wiki-term'),
        'ui_contexts': ('dashboard_error_cards', 'channel_tables'),
    },
    'uncorrectable_errors': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Glossary.md'),
        'tags': ('errors', 'fec', 'codewords', 'packet-loss-risk', 'wiki-term'),
        'ui_contexts': ('dashboard_error_cards', 'channel_tables'),
        'aliases': ('Errors',),
    },
    't3_t4_timeout': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('events', 'ranging', 'timeout', 'upstream', 'wiki-term'),
        'ui_contexts': ('event_log', 'incident_journal'),
    },
    'cmts': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('cmts', 'provider-side', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_basics',),
        'aliases': ('CCAP',),
    },
    'vcmts': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('vcmts', 'provider-side', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_basics',),
    },
    'remote_phy': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('remote-phy', 'rphy', 'provider-side', 'node', 'wiki-term'),
        'ui_contexts': ('dashboard_docsis_basics',),
    },
    'return_path_interference': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('rueckwegstoerer', 'return-path', 'noise', 'upstream', 'wiki-term'),
        'ui_contexts': ('dashboard_signal_cards', 'event_log'),
    },
    'node_segment': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('node', 'segment', 'node-split', 'service-group', 'wiki-term'),
        'ui_contexts': ('segment_utilization', 'dashboard_docsis_basics'),
    },
    'shared_medium': {
        'source_pages': ('DOCSIS-Glossary.md',),
        'tags': ('shared-medium', 'segment', 'congestion', 'wiki-term'),
        'ui_contexts': ('segment_utilization', 'speedtest_correlation'),
    },
    'health_status': {
        'source_pages': ('DOCSIS-Glossary.md', 'Features-Dashboard.md'),
        'tags': ('health', 'good', 'marginal', 'poor', 'wiki-term', 'app-label'),
        'ui_contexts': ('dashboard_health', 'channel_tables'),
    },
    'dashboard': {
        'source_pages': ('Features-Dashboard.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('dashboard',),
    },
    'in_app_glossary': {
        'source_pages': ('Features-Glossary.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('in_app_glossary',),
    },
    'channel_timeline': {
        'source_pages': ('Features-Channel-Timeline.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('channel_timeline',),
    },
    'signal_trends': {
        'source_pages': ('Features-Signal-Trends.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('signal_trends',),
    },
    'modulation_performance': {
        'source_pages': ('Features-Modulation-Performance.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('modulation_performance',),
    },
    'segment_utilization': {
        'source_pages': ('Features-Segment-Utilization.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('segment_utilization',),
    },
    'correlation_analysis': {
        'source_pages': ('Features-Correlation-Analysis.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('correlation_analysis',),
    },
    'before_after_comparison': {
        'source_pages': ('Features-Before-After-Comparison.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('before_after_comparison',),
    },
    'connection_monitor': {
        'source_pages': ('Features-Connection-Monitor.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('connection_monitor',),
    },
    'event_log': {
        'source_pages': ('Features-Event-Log.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('event_log',),
    },
    'incident_journal': {
        'source_pages': ('Features-Incident-Journal.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('incident_journal',),
    },
    'smart_capture': {
        'source_pages': ('Features-Smart-Capture.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('smart_capture',),
    },
    'speedtest': {
        'source_pages': ('Features-Speedtest.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('speedtest',),
    },
    'bqm': {
        'source_pages': ('Features-BQM.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('bqm',),
    },
    'smokeping': {
        'source_pages': ('Features-Smokeping.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('smokeping',),
    },
    'bnetza': {
        'source_pages': ('Features-BNetzA.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('bnetza',),
    },
    'gaming_index': {
        'source_pages': ('Features-Glossary.md', 'Features-Gaming-Quality.md'),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('gaming_index',),
    },
    'llm_export': {
        'source_pages': ('Features-LLM-Export.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('llm_export',),
    },
    'doctor_diagnostics': {
        'source_pages': ('Doctor-Diagnostics.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('doctor_diagnostics',),
    },
    'pwa_offline': {
        'source_pages': ('PWA-and-Offline.md',),
        'tags': ('docsight-feature', 'app-function'),
        'ui_contexts': ('pwa_offline',),
    },
}


def _metadata_for_term(term_id: str) -> dict[str, tuple[str, ...]]:
    return _GLOSSARY_WIKI_INDEX.get(term_id, {})


def _validate_media_entries(term_id: str, media: Iterable[dict[str, Any]]) -> list[str]:
    """Validate optional glossary media stays local, explicit, and accessible."""
    errors: list[str] = []
    for index, item in enumerate(media):
        if not isinstance(item, dict):
            errors.append(f"{term_id}: media {index} must be an object")
            continue
        raw_src = item.get("src", "")
        raw_alt = item.get("alt", "")
        src = raw_src.strip() if isinstance(raw_src, str) else ""
        decoded_src = unquote(src)
        alt = raw_alt.strip() if isinstance(raw_alt, str) else ""
        if not src:
            errors.append(f"{term_id}: media {index} missing src")
        elif (
            not src.startswith("/static/")
            or decoded_src.startswith(("http://", "https://", "//"))
            or ":" in decoded_src.split("/", 1)[0]
            or "\\" in decoded_src
            or ".." in Path(decoded_src).parts
        ):
            errors.append(f"{term_id}: media {index} src must be a local static path")
        if not alt:
            errors.append(f"{term_id}: media {index} missing alt")
    return errors


_GLOSSARY_I18N_DIR = Path(__file__).with_name("glossary_i18n")


def _normalize_lang(lang: str | None) -> str:
    """Normalize request/app locale IDs to glossary localization file names."""
    if not lang:
        return "en"
    return lang.split("-", 1)[0].split("_", 1)[0].lower()


@lru_cache(maxsize=1)
def _load_glossary_localizations() -> dict[str, dict[str, Any]]:
    """Load optional localized glossary catalogs from JSON files."""
    catalogs: dict[str, dict[str, Any]] = {}
    if not _GLOSSARY_I18N_DIR.exists():
        return catalogs
    for path in sorted(_GLOSSARY_I18N_DIR.glob("*.json")):
        lang = path.stem
        if lang == "en":
            continue
        with path.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
        categories = {item["id"]: item for item in data.get("categories", [])}
        terms = {item["id"]: item for item in data.get("terms", [])}
        catalogs[lang] = {"categories": categories, "terms": terms}
    return catalogs


def get_glossary_localization_languages() -> tuple[str, ...]:
    """Return language IDs that provide localized glossary term content."""
    return tuple(sorted(_load_glossary_localizations()))


def _localized_term_payload(term_id: str, lang: str) -> dict[str, Any]:
    catalog = _load_glossary_localizations().get(_normalize_lang(lang), {})
    term = catalog.get("terms", {}).get(term_id, {})
    return term if isinstance(term, dict) else {}


def _localized_category_payload(category_id: str, lang: str) -> dict[str, Any]:
    catalog = _load_glossary_localizations().get(_normalize_lang(lang), {})
    category = catalog.get("categories", {}).get(category_id, {})
    return category if isinstance(category, dict) else {}



def _category_ids() -> set[str]:
    return {category.id for category in _CATEGORIES}


def _term_ids() -> set[str]:
    return {term.id for term in _TERMS}


def validate_glossary_catalog(terms: Iterable[GlossaryTerm] = _TERMS) -> list[str]:
    """Return schema/link validation errors for the glossary catalog."""
    errors: list[str] = []
    seen: set[str] = set()
    term_list = list(terms)
    term_ids = {term.id for term in term_list}
    category_ids = _category_ids()
    normalized_aliases: dict[str, str] = {}

    for term in term_list:
        if not term.id:
            errors.append("term id is required")
        if term.id in seen:
            errors.append(f"duplicate term id: {term.id}")
        seen.add(term.id)
        if term.category not in category_ids:
            errors.append(f"{term.id}: unknown category {term.category}")
        if not term.title.get("en"):
            errors.append(f"{term.id}: missing English title")
        if "en" not in term.levels:
            errors.append(f"{term.id}: missing English levels")
            continue
        for level in GLOSSARY_LEVELS:
            text = term.levels["en"].get(level, "").strip()
            if not text:
                errors.append(f"{term.id}: missing {level} level")
        for related_id in term.related:
            if related_id not in term_ids:
                errors.append(f"{term.id}: unknown related term {related_id}")
            if related_id == term.id:
                errors.append(f"{term.id}: related term points to itself")
        for token in term.protected_terms:
            if not token:
                errors.append(f"{term.id}: empty protected term")
        errors.extend(_validate_media_entries(term.id, term.media))
        metadata = _metadata_for_term(term.id)
        for field in ("tags", "source_pages", "ui_contexts"):
            values = metadata.get(field, ())
            if not values:
                continue
            for value in values:
                if not value.strip():
                    errors.append(f"{term.id}: empty {field[:-1]}")
        for alias in (term.title.get("en", ""), *term.aliases.get("en", ()), *metadata.get("aliases", ())):
            normalized = alias.strip().casefold()
            if not normalized:
                errors.append(f"{term.id}: empty alias")
                continue
            previous = normalized_aliases.setdefault(normalized, term.id)
            if previous != term.id:
                errors.append(f"{term.id}: duplicate alias '{alias}' also used by {previous}")

    return errors


def get_glossary_categories(lang: str = "en") -> list[dict[str, str]]:
    """Return localized glossary categories."""
    return [category.localized(lang) for category in _CATEGORIES]


def get_glossary_terms(lang: str = "en") -> list[dict[str, Any]]:
    """Return localized glossary terms sorted as one global alphabetical dictionary."""
    localized = [term.localized(lang) for term in _TERMS]
    return sorted(localized, key=lambda item: item["title"].casefold())


def get_glossary_term(term_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Return one localized glossary term by stable ID."""
    for term in _TERMS:
        if term.id == term_id:
            return term.localized(lang)
    return None


def get_related_terms(term: dict[str, Any], lang: str = "en") -> list[dict[str, Any]]:
    """Resolve related term IDs for a localized term dict."""
    related = []
    for term_id in term.get("related", []):
        resolved = get_glossary_term(term_id, lang)
        if resolved:
            related.append(resolved)
    return related
