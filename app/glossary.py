"""Canonical in-app glossary data model and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

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

    def localized(self, lang: str = "en") -> dict[str, Any]:
        """Return a template-friendly localized term, falling back to English."""
        translation = _localized_term_payload(self.id, lang)
        title = translation.get("title") or self.title.get(lang) or self.title["en"]
        metadata = _metadata_for_term(self.id)
        aliases = tuple(translation.get("aliases") or self.aliases.get(lang) or self.aliases.get("en", ()))
        aliases = _unique((*aliases, *metadata.get("aliases", ())))
        levels = translation.get("levels") or self.levels.get(lang) or self.levels["en"]
        misconceptions = tuple(translation.get("misconceptions") or self.misconceptions.get(lang) or self.misconceptions.get("en", ()))
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
        'DOCSIS is the standard cable modems use to communicate with the cable network.',
        'DOCSIS carries internet service over coax cable. DOCSight reads modem, channel, and signal data from supported DOCSIS devices.',
        'DOCSIS combines downstream and upstream channels such as SC-QAM, OFDM, and OFDMA. DOCSight interprets the modem-visible evidence but does not see the whole provider network.',
        'DOCSIS defines the cable modem access layer between the cable modem and provider-side CMTS/CCAP systems over the HFC/coax segment.',
        ('DOCSIS is not DSL; DOCSIS channel values should not be read like DSL sync values.',),
    ),
    _term(
        'downstream',
        'docsis_terms',
        'Downstream',
        ('Download direction', 'DS', 'Downstream channels'),
        ('DOCSIS', 'SC-QAM', 'OFDM'),
        ('upstream', 'sc_qam', 'ofdm', 'power_level', 'snr_mer'),
        'Downstream is data coming from the internet toward your home.',
        'In DOCSIS, downstream channels carry data from the provider network to the modem. DOCSight shows downstream channel state separately from upstream state.',
        'Downstream may use SC-QAM and/or OFDM channels. Power, SNR/MER, modulation, profile information, and lock state explain whether the modem receives them cleanly.',
        'Downstream may use SC-QAM and/or OFDM channels. Power, SNR/MER, modulation, profile information, and lock state explain whether the modem receives them cleanly.',
    ),
    _term(
        'upstream',
        'docsis_terms',
        'Upstream',
        ('Upload direction', 'US', 'Upstream channels'),
        ('DOCSIS', 'SC-QAM', 'OFDMA'),
        ('downstream', 'ofdma', 'power_level', 'return_path_interference', 't3_t4_timeout'),
        'Upstream is data going from your home toward the internet.',
        'In DOCSIS, upstream channels carry data from the modem back to the provider network. DOCSight uses them for upload-side signal evidence.',
        'Upstream may use SC-QAM and/or OFDMA. High transmit power, channel drops, T3/T4 events, or return-path noise can point to upload-side impairment.',
        'Upstream may use SC-QAM and/or OFDMA. High transmit power, channel drops, T3/T4 events, or return-path noise can point to upload-side impairment.',
    ),
    _term(
        'channel_bonding',
        'docsis_terms',
        'Channel bonding',
        ('Bonded channels', 'Channel bundle', 'DOCSIS bonding'),
        ('DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('downstream', 'upstream', 'sc_qam', 'ofdm', 'ofdma'),
        'Channel bonding lets a modem use several cable channels together.',
        'DOCSIS modems often use multiple downstream and upstream channels at once. DOCSight groups visible channels so you can see what is bonded and healthy.',
        'Bonded-channel interpretation must keep channel family, direction, lock state, and profile availability separate; it is not automatically the same as speedtest throughput.',
        'Bonded-channel interpretation must keep channel family, direction, lock state, and profile availability separate; it is not automatically the same as speedtest throughput.',
    ),
    _term(
        'sc_qam',
        'docsis_terms',
        'SC-QAM',
        ('Single-carrier QAM', 'DOCSIS 3.0 channel', 'QAM channel'),
        ('SC-QAM', 'DOCSIS', 'QAM'),
        ('qam_modulation_order', 'channel_bonding', 'ofdm', 'mixed_mode'),
        'SC-QAM is the classic narrow DOCSIS channel type.',
        'SC-QAM channels are traditional DOCSIS 3.0-style channels. DOCSight can usually show their power, SNR/MER, modulation, and health.',
        'SC-QAM uses a single carrier with a fixed channel width and QAM modulation order. DOCSight can estimate gross channel context when the modem exposes enough data.',
        'SC-QAM uses a single carrier with a fixed channel width and QAM modulation order. DOCSight can estimate gross channel context when the modem exposes enough data.',
    ),
    _term(
        'ofdm',
        'docsis_terms',
        'OFDM',
        ('DOCSIS 3.1 downstream', 'Orthogonal frequency-division multiplexing'),
        ('OFDM', 'DOCSIS', 'SC-QAM'),
        ('ofdma', 'sc_qam', 'mixed_mode', 'qam_modulation_order'),
        'OFDM is the DOCSIS 3.1 downstream channel type with many tiny subcarriers.',
        'DOCSIS 3.1 uses OFDM downstream for wide, flexible receive channels. DOCSight labels OFDM separately from SC-QAM because the evidence and capacity math are different.',
        'OFDM interpretation depends on profiles, subcarrier health, exclusions, and provider-side scheduling. Missing profile data should be shown as unknown, not guessed.',
        'OFDM interpretation depends on profiles, subcarrier health, exclusions, and provider-side scheduling. Missing profile data should be shown as unknown, not guessed.',
    ),
    _term(
        'ofdma',
        'docsis_terms',
        'OFDMA',
        ('DOCSIS 3.1 upstream', 'Orthogonal frequency-division multiple access'),
        ('OFDMA', 'DOCSIS', 'SC-QAM'),
        ('ofdm', 'upstream', 'mixed_mode', 'return_path_interference'),
        'OFDMA is the DOCSIS 3.1 upstream channel type.',
        'OFDMA lets many modems share pieces of a wide upstream block. DOCSight labels it separately from SC-QAM upstream channels.',
        'OFDMA depends on profile, subcarrier, minislot, return-path noise, and scheduling context. DOCSight should avoid simple SC-QAM-style capacity guesses when the data is incomplete.',
        'OFDMA depends on profile, subcarrier, minislot, return-path noise, and scheduling context. DOCSight should avoid simple SC-QAM-style capacity guesses when the data is incomplete.',
    ),
    _term(
        'mixed_mode',
        'docsis_terms',
        'Mixed mode (3.0 + 3.1)',
        ('DOCSIS 3.0 + 3.1', 'Mixed DOCSIS mode', 'SC-QAM plus OFDM'),
        ('DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('docsis', 'sc_qam', 'ofdm', 'ofdma', 'channel_bonding'),
        'Mixed mode means DOCSIS 3.0 and DOCSIS 3.1 channel types are used together.',
        'Many modern modems show SC-QAM channels together with OFDM downstream or OFDMA upstream. DOCSight treats each channel family separately.',
        'Mixed mode is normal during DOCSIS 3.1 deployments. SC-QAM totals, OFDM/OFDMA profiles, and channel health should not be collapsed into one invented number.',
        'Mixed mode is normal during DOCSIS 3.1 deployments. SC-QAM totals, OFDM/OFDMA profiles, and channel health should not be collapsed into one invented number.',
    ),
    _term(
        'qam_modulation_order',
        'docsis_terms',
        'QAM / modulation order',
        ('QAM', '256-QAM', '4096-QAM', 'Modulation'),
        ('QAM', 'DOCSIS', 'SC-QAM', 'OFDM', 'OFDMA'),
        ('sc_qam', 'qpsk', 'snr_mer', 'ofdm', 'ofdma'),
        'Modulation is how data is packed into the cable signal.',
        'Higher QAM levels can carry more bits per symbol, but they need a cleaner signal. DOCSight shows modulation so drops are visible.',
        'QAM must be interpreted with channel family and SNR/MER. SC-QAM has a simpler relationship than OFDM/OFDMA profile-based channels.',
        'QAM must be interpreted with channel family and SNR/MER. SC-QAM has a simpler relationship than OFDM/OFDMA profile-based channels.',
    ),
    _term(
        'qpsk',
        'docsis_terms',
        'QPSK (4QAM)',
        ('4QAM', 'Quadrature Phase Shift Keying'),
        ('QPSK', 'QAM', 'DOCSIS'),
        ('qam_modulation_order', 'upstream', 'snr_mer', 'return_path_interference'),
        'QPSK, shown as 4QAM, is a very low modulation level.',
        'In DOCSIS, an upstream drop to 4QAM/QPSK usually means the signal quality is severely degraded. DOCSight displays it as 4QAM for consistency with other modulation labels.',
        'QPSK encodes 2 bits per symbol and is much less efficient than higher QAM orders. It is useful evidence when correlated with upstream power, SNR/MER, noise, or T3/T4 events.',
        'QPSK encodes 2 bits per symbol and is much less efficient than higher QAM orders. It is useful evidence when correlated with upstream power, SNR/MER, noise, or T3/T4 events.',
    ),
    _term(
        'power_level',
        'docsis_terms',
        'Power level',
        ('Signal level', 'dBmV', 'Receive power', 'Transmit power'),
        ('dBmV',),
        ('downstream', 'upstream', 'snr_mer', 'return_path_interference'),
        'Power level is how strong the cable signal looks to the modem, or how hard the modem must talk back.',
        'DOCSight can show downstream receive power and upstream transmit power when the modem exposes them. Values outside expected ranges can indicate cabling or return-path issues.',
        'Power must be interpreted by direction and channel type. Downstream receive power and upstream transmit power describe different sides of the DOCSIS link.',
        'Power must be interpreted by direction and channel type. Downstream receive power and upstream transmit power describe different sides of the DOCSIS link.',
    ),
    _term(
        'snr_mer',
        'docsis_terms',
        'SNR/MER',
        ('Signal-to-noise ratio', 'Modulation error ratio', 'MER', 'SNR'),
        ('SNR', 'MER', 'DOCSIS', 'QAM'),
        ('power_level', 'qam_modulation_order', 'correctable_errors', 'uncorrectable_errors'),
        'SNR/MER says how clear the signal is compared with noise.',
        'SNR and MER are quality measurements. Better values usually mean the modem can decode the channel more reliably.',
        'SNR/MER should be interpreted alongside modulation, channel family, error counters, and time trends. One value alone is weaker evidence than a correlated pattern.',
        'SNR/MER should be interpreted alongside modulation, channel family, error counters, and time trends. One value alone is weaker evidence than a correlated pattern.',
    ),
    _term(
        'correctable_errors',
        'docsis_terms',
        'Correctable errors',
        ('Correctables', 'Corrected codewords', 'FEC corrected'),
        ('DOCSIS', 'FEC', 'DOCSight'),
        ('uncorrectable_errors', 'snr_mer', 'power_level'),
        'Correctable errors are small mistakes the modem could repair.',
        'Correctable counters can rise even on a working line. DOCSight makes them useful by showing rate, timing, affected channels, and whether uncorrectables also rise.',
        'Correctables reflect FEC work. Growth during noise events, high rates on specific channels, or correlation with low MER is stronger evidence than an old cumulative total.',
        'Correctables reflect FEC work. Growth during noise events, high rates on specific channels, or correlation with low MER is stronger evidence than an old cumulative total.',
        ('A high old correctable total is not automatically an active fault.',),
    ),
    _term(
        'uncorrectable_errors',
        'docsis_terms',
        'Uncorrectable errors',
        ('Uncorrectables', 'Uncorrected codewords', 'FEC uncorrected'),
        ('DOCSIS', 'FEC'),
        ('correctable_errors', 'snr_mer', 'power_level'),
        'Uncorrectable errors are mistakes the modem could not repair.',
        'Uncorrectables can mean lost channel-level data, especially when they grow during the observation window. DOCSight treats growth and timing as more important than one old total.',
        'For evidence, keep raw counters separate from derived growth. Resets, wraparound, and modem reboots can change raw totals.',
        'For evidence, keep raw counters separate from derived growth. Resets, wraparound, and modem reboots can change raw totals.',
        ('A single old uncorrectable total does not prove a current fault by itself.',),
    ),
    _term(
        't3_t4_timeout',
        'docsis_terms',
        'T3 / T4 timeout',
        ('T3 timeout', 'T4 timeout', 'Ranging timeout', 'DOCSIS timeout'),
        ('T3', 'T4', 'DOCSIS', 'CMTS'),
        ('upstream', 'return_path_interference', 'event_log'),
        'T3 and T4 timeouts are modem events where DOCSIS communication with the provider side was interrupted.',
        'A T3 timeout usually means a missed ranging response; a T4 timeout is more severe and can lead to a resync. DOCSight uses them as timing evidence.',
        'Timeouts should be read with event logs, upstream channel state, transmit power, return-path noise symptoms, and maintenance windows.',
        'Timeouts should be read with event logs, upstream channel state, transmit power, return-path noise symptoms, and maintenance windows.',
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
        'CMTS/CCAP systems affect channel availability, profiles, scheduling, and provisioning. DOCSight should not infer provider-side state without an explicit supported source.',
        'CMTS/CCAP systems affect channel availability, profiles, scheduling, and provisioning. DOCSight should not infer provider-side state without an explicit supported source.',
    ),
    _term(
        'vcmts',
        'docsis_terms',
        'vCMTS',
        ('Virtual CMTS', 'Software CMTS', 'CableOS'),
        ('vCMTS', 'CMTS', 'DOCSIS'),
        ('cmts', 'remote_phy', 'docsis'),
        'A vCMTS is a software-based CMTS used in modern cable access networks.',
        'A vCMTS provides CMTS functions on general-purpose server infrastructure instead of only dedicated hardware. DOCSight treats it as provider-side context.',
        'vCMTS information can explain network architecture, but local modem evidence still does not reveal all provider-side scheduling, profile, or service-flow policy.',
        'vCMTS information can explain network architecture, but local modem evidence still does not reveal all provider-side scheduling, profile, or service-flow policy.',
    ),
    _term(
        'remote_phy',
        'docsis_terms',
        'Remote PHY',
        ('R-PHY', 'Remote PHY device', 'RPD'),
        ('Remote PHY', 'DOCSIS', 'CMTS'),
        ('cmts', 'vcmts', 'node_segment'),
        'Remote PHY moves RF-layer work closer to the neighborhood.',
        'In modern cable networks, Remote PHY can place PHY-layer functions in a remote node while the provider controls the service centrally. DOCSight normally sees only modem-side effects.',
        'R-PHY/RPD and vCMTS designs affect where RF and MAC functions live. DOCSight should not infer exact provider topology unless a supported source exposes it.',
        'R-PHY/RPD and vCMTS designs affect where RF and MAC functions live. DOCSight should not infer exact provider topology unless a supported source exposes it.',
    ),
    _term(
        'return_path_interference',
        'docsis_terms',
        'Rückwegstörer',
        ('Return-path interferer', 'Return path noise', 'Upstream ingress'),
        ('DOCSIS', 'SNR', 'MER', 'OFDMA'),
        ('upstream', 'power_level', 't3_t4_timeout', 'snr_mer'),
        'A Rückwegstörer is interference in the upstream return path.',
        'Return-path interference can make uploads and modem ranging unstable. DOCSight can show symptoms such as upstream power changes, lower modulation, T3/T4 events, or packet loss.',
        'Return-path ingress is often shared and intermittent. Provider-side spectrum or plant data is needed to localize it with confidence.',
        'Return-path ingress is often shared and intermittent. Provider-side spectrum or plant data is needed to localize it with confidence.',
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
        'Service groups and node boundaries influence contention, channel load, and upgrade planning. A local modem cannot expose the full segment population by itself.',
        'Service groups and node boundaries influence contention, channel load, and upgrade planning. A local modem cannot expose the full segment population by itself.',
    ),
    _term(
        'shared_medium',
        'docsis_terms',
        'Shared medium',
        ('Cable segment', 'Shared access network'),
        ('DOCSIS', 'CMTS', 'DOCSight'),
        ('node_segment', 'segment_utilization', 'speedtest'),
        'Cable internet shares parts of the access network with other users on the same segment.',
        'A shared medium can be busy even when your own modem signal looks clean. DOCSight separates local modem evidence from provider-side utilization claims.',
        'Shared-medium behavior depends on service-group sizing, scheduling, channel capacity, and active subscriber demand. A single modem cannot prove total segment load.',
        'Shared-medium behavior depends on service-group sizing, scheduling, channel capacity, and active subscriber demand. A single modem cannot prove total segment load.',
        ('A good signal level does not prove that the provider segment is uncongested.',),
    ),
    _term(
        'health_status',
        'docsis_terms',
        'Health status',
        ('Good', 'Marginal', 'Poor', 'Signal health', 'Channel health'),
        ('DOCSight', 'DOCSIS', 'SNR', 'dBmV'),
        ('power_level', 'snr_mer', 'correctable_errors', 'uncorrectable_errors'),
        "Health status is DOCSight's short label for whether visible signal evidence looks good, marginal, or poor.",
        'Health status summarizes modem-visible evidence such as power, SNR/MER, channel lock, and errors. It is a triage label, not a provider fault verdict by itself.',
        'Status labels compress evidence for scanning. Raw values and timestamps remain important for support, escalation, and before/after comparisons.',
        'Status labels compress evidence for scanning. Raw values and timestamps remain important for support, escalation, and before/after comparisons.',
    ),
    _term(
        'dashboard',
        'docsight_features',
        'Dashboard',
        ('Home view', 'Overview'),
        (),
        ('health_status', 'power_level', 'snr_mer', 'event_log', 'gaming_index'),
        "Dashboard is a DOCSight feature for understanding the app's diagnostic evidence.",
        'The dashboard is the main DOCSight view for current cable-connection health. It combines status, modem/provider info, signal cards, channel tables, recent events, and optional speed/gaming evidence.',
        'The dashboard is the main DOCSight view for current cable-connection health. It combines status, modem/provider info, signal cards, channel tables, recent events, and optional speed/gaming evidence. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'The dashboard is the main DOCSight view for current cable-connection health. It combines status, modem/provider info, signal cards, channel tables, recent events, and optional speed/gaming evidence. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'in_app_glossary',
        'docsight_features',
        'In-App Glossary',
        ('Glossary', 'Contextual help'),
        (),
        ('dashboard', 'docsis', 'power_level'),
        "In-App Glossary is a DOCSight feature for understanding the app's diagnostic evidence.",
        'The In-App Glossary explains DOCSIS terms and DOCSight features directly in the app. Info icons and the glossary view link dashboard values to plain-language explanations.',
        'The In-App Glossary explains DOCSIS terms and DOCSight features directly in the app. Info icons and the glossary view link dashboard values to plain-language explanations. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'The In-App Glossary explains DOCSIS terms and DOCSight features directly in the app. Info icons and the glossary view link dashboard values to plain-language explanations. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'channel_timeline',
        'docsight_features',
        'Channel Timeline',
        ('Timeline', 'Channel history'),
        (),
        ('downstream', 'upstream', 'signal_trends'),
        "Channel Timeline is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Channel Timeline shows how modem-visible channel state changes over time, so drops, lock changes, and signal shifts are easier to compare.',
        'Channel Timeline shows how modem-visible channel state changes over time, so drops, lock changes, and signal shifts are easier to compare. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Channel Timeline shows how modem-visible channel state changes over time, so drops, lock changes, and signal shifts are easier to compare. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'signal_trends',
        'docsight_features',
        'Signal Trends',
        ('Signal history', 'Trend charts'),
        (),
        ('power_level', 'snr_mer', 'channel_timeline'),
        "Signal Trends is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Signal Trends turns repeated modem readings into time-series views for power, SNR/MER, errors, and related signal evidence.',
        'Signal Trends turns repeated modem readings into time-series views for power, SNR/MER, errors, and related signal evidence. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Signal Trends turns repeated modem readings into time-series views for power, SNR/MER, errors, and related signal evidence. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'modulation_performance',
        'docsight_features',
        'Modulation Performance',
        ('Modulation view', 'QAM performance'),
        ('DOCSight', 'QAM'),
        ('qam_modulation_order', 'sc_qam', 'ofdm', 'ofdma'),
        "Modulation Performance is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Modulation Performance focuses on QAM/channel-family behavior so degraded modulation and capacity-sensitive signal problems are easier to spot.',
        'Modulation Performance focuses on QAM/channel-family behavior so degraded modulation and capacity-sensitive signal problems are easier to spot. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Modulation Performance focuses on QAM/channel-family behavior so degraded modulation and capacity-sensitive signal problems are easier to spot. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'segment_utilization',
        'docsight_features',
        'Segment Utilization',
        ('Segment load', 'Node load'),
        (),
        ('shared_medium', 'node_segment', 'speedtest'),
        "Segment Utilization is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Segment Utilization is DOCSight’s view for separating local signal evidence from shared-segment load signals when supported data is available.',
        'Segment Utilization is DOCSight’s view for separating local signal evidence from shared-segment load signals when supported data is available. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Segment Utilization is DOCSight’s view for separating local signal evidence from shared-segment load signals when supported data is available. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'correlation_analysis',
        'docsight_features',
        'Correlation Analysis',
        ('Correlation view', 'Signal correlation'),
        (),
        ('signal_trends', 'speedtest', 'event_log'),
        "Correlation Analysis is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Correlation Analysis compares signal, error, event, speed, and external evidence over time to show which symptoms happen together.',
        'Correlation Analysis compares signal, error, event, speed, and external evidence over time to show which symptoms happen together. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Correlation Analysis compares signal, error, event, speed, and external evidence over time to show which symptoms happen together. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'before_after_comparison',
        'docsight_features',
        'Before/After Comparison',
        ('Comparison view', 'Repair comparison'),
        (),
        ('signal_trends', 'incident_journal', 'dashboard'),
        "Before/After Comparison is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Before/After Comparison helps compare snapshots around a change, repair, reboot, or provider visit so improvements and regressions are visible.',
        'Before/After Comparison helps compare snapshots around a change, repair, reboot, or provider visit so improvements and regressions are visible. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Before/After Comparison helps compare snapshots around a change, repair, reboot, or provider visit so improvements and regressions are visible. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'connection_monitor',
        'docsight_features',
        'Connection Monitor',
        ('Ping monitor', 'Availability monitor'),
        (),
        ('speedtest', 'event_log', 'incident_journal'),
        "Connection Monitor is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Connection Monitor tracks reachability/latency over time, making dropouts and timing evidence easier to export and discuss.',
        'Connection Monitor tracks reachability/latency over time, making dropouts and timing evidence easier to export and discuss. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Connection Monitor tracks reachability/latency over time, making dropouts and timing evidence easier to export and discuss. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'event_log',
        'docsight_features',
        'Event Log',
        ('Events', 'Modem events'),
        (),
        ('t3_t4_timeout', 'connection_monitor', 'incident_journal'),
        "Event Log is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Event Log collects recent modem or app-visible events so timeouts, resyncs, and other symptoms can be correlated with signal and user impact.',
        'Event Log collects recent modem or app-visible events so timeouts, resyncs, and other symptoms can be correlated with signal and user impact. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Event Log collects recent modem or app-visible events so timeouts, resyncs, and other symptoms can be correlated with signal and user impact. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'incident_journal',
        'docsight_features',
        'Incident Journal',
        ('Journal', 'ISP evidence journal'),
        (),
        ('event_log', 'connection_monitor', 'before_after_comparison'),
        "Incident Journal is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Incident Journal is DOCSight’s place to record incidents, evidence, and notes for troubleshooting or provider escalation.',
        'Incident Journal is DOCSight’s place to record incidents, evidence, and notes for troubleshooting or provider escalation. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Incident Journal is DOCSight’s place to record incidents, evidence, and notes for troubleshooting or provider escalation. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'smart_capture',
        'docsight_features',
        'Smart Capture',
        ('Capture', 'Evidence capture'),
        (),
        ('incident_journal', 'dashboard', 'signal_trends'),
        "Smart Capture is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Smart Capture helps collect relevant DOCSight evidence around a problem window instead of relying on one isolated screenshot.',
        'Smart Capture helps collect relevant DOCSight evidence around a problem window instead of relying on one isolated screenshot. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Smart Capture helps collect relevant DOCSight evidence around a problem window instead of relying on one isolated screenshot. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'speedtest',
        'docsight_features',
        'Speedtest',
        ('Speed test', 'Throughput test'),
        (),
        ('dashboard', 'segment_utilization', 'gaming_index'),
        "Speedtest is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Speedtest integration records measured download, upload, latency, and jitter so user-visible performance can be compared with DOCSIS evidence.',
        'Speedtest integration records measured download, upload, latency, and jitter so user-visible performance can be compared with DOCSIS evidence. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Speedtest integration records measured download, upload, latency, and jitter so user-visible performance can be compared with DOCSIS evidence. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'bqm',
        'docsight_features',
        'BQM',
        ('Broadband Quality Monitor', 'ThinkBroadband BQM'),
        (),
        ('connection_monitor', 'incident_journal', 'correlation_analysis'),
        "BQM is a DOCSight feature for understanding the app's diagnostic evidence.",
        'BQM integration brings external latency/loss monitoring into DOCSight so packet-loss windows can be compared with modem evidence.',
        'BQM integration brings external latency/loss monitoring into DOCSight so packet-loss windows can be compared with modem evidence. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'BQM integration brings external latency/loss monitoring into DOCSight so packet-loss windows can be compared with modem evidence. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'smokeping',
        'docsight_features',
        'Smokeping',
        ('SmokePing', 'Latency graph'),
        (),
        ('connection_monitor', 'bqm', 'correlation_analysis'),
        "Smokeping is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Smokeping support lets DOCSight use latency history as another evidence source for intermittent connectivity problems.',
        'Smokeping support lets DOCSight use latency history as another evidence source for intermittent connectivity problems. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Smokeping support lets DOCSight use latency history as another evidence source for intermittent connectivity problems. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'bnetza',
        'docsight_features',
        'BNetzA measurement',
        ('Broadband measurement', 'Bundesnetzagentur measurement'),
        (),
        ('speedtest', 'incident_journal', 'before_after_comparison'),
        "BNetzA measurement is a DOCSight feature for understanding the app's diagnostic evidence.",
        'BNetzA measurement support helps attach official broadband-measurement evidence to DOCSight’s diagnostic timeline.',
        'BNetzA measurement support helps attach official broadband-measurement evidence to DOCSight’s diagnostic timeline. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'BNetzA measurement support helps attach official broadband-measurement evidence to DOCSight’s diagnostic timeline. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'gaming_index',
        'docsight_features',
        'Gaming Index',
        ('Gaming Quality Index', 'Gaming quality', 'Latency quality'),
        (),
        ('dashboard', 'speedtest', 'health_status'),
        "Gaming Index is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Gaming Index is a quick DOCSight quality signal for latency-sensitive use. It combines latency-sensitive evidence with DOCSIS health when available.',
        'Gaming Index is a quick DOCSight quality signal for latency-sensitive use. It combines latency-sensitive evidence with DOCSIS health when available. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Gaming Index is a quick DOCSight quality signal for latency-sensitive use. It combines latency-sensitive evidence with DOCSIS health when available. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'llm_export',
        'docsight_features',
        'LLM Export',
        ('AI export', 'Support export'),
        (),
        ('incident_journal', 'correlation_analysis', 'smart_capture'),
        "LLM Export is a DOCSight feature for understanding the app's diagnostic evidence.",
        'LLM Export packages selected DOCSight evidence into a support-friendly text export so diagnostics can be reviewed without exposing unrelated app state.',
        'LLM Export packages selected DOCSight evidence into a support-friendly text export so diagnostics can be reviewed without exposing unrelated app state. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'LLM Export packages selected DOCSight evidence into a support-friendly text export so diagnostics can be reviewed without exposing unrelated app state. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'doctor_diagnostics',
        'docsight_features',
        'Doctor Diagnostics',
        ('Doctor', 'Diagnostics'),
        (),
        ('dashboard', 'incident_journal', 'smart_capture'),
        "Doctor Diagnostics is a DOCSight feature for understanding the app's diagnostic evidence.",
        'Doctor Diagnostics guides checks around DOCSight setup, modem access, and diagnostic evidence so configuration problems are easier to separate from line problems.',
        'Doctor Diagnostics guides checks around DOCSight setup, modem access, and diagnostic evidence so configuration problems are easier to separate from line problems. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'Doctor Diagnostics guides checks around DOCSight setup, modem access, and diagnostic evidence so configuration problems are easier to separate from line problems. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
    ),
    _term(
        'pwa_offline',
        'docsight_features',
        'PWA and Offline Mode',
        ('PWA', 'Offline shell'),
        (),
        ('dashboard', 'in_app_glossary'),
        "PWA and Offline Mode is a DOCSight feature for understanding the app's diagnostic evidence.",
        'PWA and Offline Mode make the DOCSight shell installable and keep the app structure available while avoiding stale live data pretending to be current.',
        'PWA and Offline Mode make the DOCSight shell installable and keep the app structure available while avoiding stale live data pretending to be current. It should be read as an app feature explanation, not as a new DOCSIS protocol term.',
        'PWA and Offline Mode make the DOCSight shell installable and keep the app structure available while avoiding stale live data pretending to be current. Keep the feature evidence boundary explicit: DOCSight can organize and correlate supported data sources, but it should not invent provider-side facts.',
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
    """Return localized glossary terms sorted by category order and title."""
    localized = [term.localized(lang) for term in _TERMS]
    category_order = {category.id: index for index, category in enumerate(_CATEGORIES)}
    return sorted(
        localized,
        key=lambda item: (category_order.get(item["category"], 999), item["title"].lower()),
    )


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
