"""Canonical in-app glossary data model and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

GLOSSARY_LEVELS: tuple[str, ...] = ("eli5", "basic", "advanced", "technician")


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

    def localized(self, lang: str = "en") -> dict[str, Any]:
        """Return a template-friendly localized term, falling back to English."""
        translation = _localized_term_payload(self.id, lang)
        title = translation.get("title") or self.title.get(lang) or self.title["en"]
        aliases = tuple(translation.get("aliases") or self.aliases.get(lang) or self.aliases.get("en", ()))
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
    ("cable_basics", "Cable/DOCSIS basics", "Core terms for understanding cable internet and what DOCSight can observe."),
    ("modulation_channels", "Modulation and channels", "How DOCSIS channels carry data and why channel technology matters."),
    ("signal_quality", "Signal quality", "Power, noise, and line-quality terms that help explain modem-visible signal health."),
    ("error_counters", "Error counters", "Corrected and uncorrected codeword counters, including what raw totals can and cannot prove."),
    ("capacity_throughput", "Capacity and throughput", "Boundaries between channel diagnostics, gross capacity, tariff speed, and speedtests."),
    ("modem_state", "Modem and provisioning state", "Provisioning, partial service, reboot, and configuration states visible around the modem."),
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
        "docsis",
        "cable_basics",
        "DOCSIS",
        ("Cable internet", "Data Over Cable Service Interface Specification"),
        ("DOCSIS", "DSL", "DOCSight"),
        ("dsl_vs_cable", "coaxial_cable", "cmts", "shared_medium", "sc_qam", "capacity_vs_throughput"),
        "DOCSIS is the language a cable modem uses to talk to the cable network. It is cable internet, not DSL over a phone line.",
        "DOCSIS carries internet service over coax cable. DOCSight reads modem, channel, and signal data from supported cable devices, so its diagnostics describe the cable link rather than a DSL line.",
        "DOCSIS networks combine downstream and upstream channels such as SC-QAM, OFDM, and OFDMA. DOCSight can interpret local modem-visible signal and channel data, but it cannot see every provider-side segment or routing condition.",
        "DOCSIS defines the cable modem access layer between the CM and CMTS over the HFC/coax segment. Local channel telemetry is useful for RF and MAC-layer diagnostics, but provider provisioning, segment load, CMTS policy, and IP routing remain outside the modem-only evidence boundary.",
        ("DOCSIS is not DSL; DSL values and cable channel values should not be compared one-to-one.",),
    ),
    _term(
        "dsl_vs_cable",
        "cable_basics",
        "DSL vs. cable",
        ("DSL", "Phone line vs coax"),
        ("DSL", "DOCSIS", "DOCSight"),
        ("docsis", "coaxial_cable", "shared_medium", "snr_mer"),
        "DSL and cable are two different ways to bring internet home. DSL uses phone wiring; cable internet uses coax cable and DOCSIS.",
        "DOCSight is built around cable/DOCSIS evidence. Cable modem values such as channels, modulation, SNR/MER, and DOCSIS capacity should not be read like DSL sync rates or DSL line statistics.",
        "DSL usually presents a point-to-point line with sync-rate style values. DOCSIS uses shared coax segments, bonded channels, and CMTS scheduling, so modem channel diagnostics need different interpretation.",
        "Do not map DSL attenuation, sync, or profile concepts directly onto DOCSIS RF/MAC evidence. DOCSIS channel state, OFDM/OFDMA profiles, service flows, and CMTS behavior describe a different access architecture.",
        ("A cable channel list is not a DSL sync table.",),
    ),
    _term(
        "coaxial_cable",
        "cable_basics",
        "Coaxial cable",
        ("Coax", "Antenna cable", "Cable line"),
        ("DOCSIS", "HFC", "DOCSight"),
        ("docsis", "dsl_vs_cable", "power_level", "attenuation"),
        "Coax is the round cable that carries TV and cable internet signals. Your cable modem uses it to connect to the DOCSIS network.",
        "Cable internet runs over coaxial cable between your home and the provider network. Splitters, connectors, and in-home wiring can affect signal levels and quality.",
        "DOCSIS coax paths are RF paths: power level, SNR/MER, ingress, attenuation, and channel lock can change when cabling, splitters, or amplifiers are poor or mis-sized.",
        "In HFC networks, the coax leg carries downstream and upstream RF channels between the modem and the access network. DOCSight can show modem-visible RF symptoms but not the entire physical plant topology.",
    ),
    _term(
        "cable_modem_router",
        "cable_basics",
        "Cable modem/router",
        ("Modem", "Gateway", "Cable router", "Bridge mode"),
        ("DOCSIS", "DOCSight", "IP"),
        ("docsis", "provisioning", "ip_throughput", "resync_reboot"),
        "The modem/router is the box that connects your home network to the cable network.",
        "A cable modem handles DOCSIS on the provider side. Many devices also act as routers, Wi-Fi access points, or gateways for your home IP network.",
        "A gateway combines DOCSIS modem functions with routing/NAT/Wi-Fi. Bridge mode may expose routing to another device, but DOCSIS signal and channel evidence still belongs to the modem side.",
        "Separate DOCSIS-layer observations from LAN/router behavior. Good RF and channel state does not rule out Wi-Fi, NAT, firewall, routing, or client-side bottlenecks behind the modem.",
    ),
    _term(
        "cmts",
        "cable_basics",
        "CMTS",
        ("Cable Modem Termination System", "Remote PHY", "Provider headend"),
        ("CMTS", "DOCSIS", "DOCSight"),
        ("docsis", "shared_medium", "provisioning", "segment_utilization"),
        "The CMTS is the provider-side system your cable modem talks to.",
        "A CMTS or related provider-side access system manages DOCSIS modems, channels, scheduling, and service configuration. DOCSight usually sees only the modem side of that relationship.",
        "Provider-side systems schedule upstream access, provide downstream channels, apply provisioning, and participate in service-flow limits. Local modem evidence can hint at problems but cannot fully describe CMTS policy.",
        "CMTS, CCAP, Remote PHY, and node architectures affect channel availability, profile assignment, scheduling, and impairment handling. DOCSight should not infer provider-side state unless an explicit supported source exposes it.",
    ),
    _term(
        "node_segment",
        "cable_basics",
        "Node/segment",
        ("Segment", "Service group", "Cable node", "Node split"),
        ("DOCSIS", "CMTS", "DOCSight"),
        ("shared_medium", "segment_utilization", "cmts"),
        "A segment is the part of the cable network shared by a group of homes.",
        "People in the same cable segment share some access-network capacity. A node split can reduce how many users share the same resources, but DOCSight normally cannot see the full segment population.",
        "Service groups and node boundaries influence contention, channel load, and upgrade planning. A local modem can expose its own channel state, not a complete list of neighboring modems or total provider demand.",
        "Segment interpretation depends on provider topology, service-group sizing, Remote PHY/CMTS design, and active subscribers. Treat complete utilization as provider-side evidence unless measured through a supported source.",
    ),
    _term(
        "shared_medium",
        "cable_basics",
        "Shared medium",
        ("Cable segment", "Node", "Shared access network"),
        ("DOCSIS", "CMTS", "DOCSight"),
        ("docsis", "node_segment", "segment_utilization", "capacity_vs_throughput"),
        "A cable segment is like a road that several homes use. Your modem can have a clean signal even when the road is busy.",
        "Cable networks share parts of the access network between multiple users. Segment load can affect real speeds, and DOCSight cannot directly measure every other modem on the segment.",
        "DOCSIS capacity is shared across channels and service groups. Local modem stats show your channel and signal state, while contention and scheduling happen at the provider side.",
        "Shared-medium behavior depends on service-group sizing, CMTS scheduling, OFDMA/OFDM profiles, provisioning, and active subscriber demand. DOCSight can highlight local RF/channel symptoms but should not infer complete segment utilization unless a supported data source exposes it.",
        ("A good signal level does not prove that the provider segment is uncongested.",),
    ),
    _term(
        "downstream",
        "modulation_channels",
        "Downstream",
        ("Download direction", "DS", "Downstream channels"),
        ("DOCSIS", "SC-QAM", "OFDM"),
        ("upstream", "sc_qam", "ofdm", "channel_bonding"),
        "Downstream is data coming from the internet toward your home.",
        "In DOCSIS, downstream channels carry data from the provider network to the modem. DOCSight shows downstream channel state separately from upstream state because the directions behave differently.",
        "Downstream may use SC-QAM and/or OFDM channels. Power, SNR/MER, modulation, profile information, and lock state help explain whether the modem receives the channels cleanly.",
        "Downstream evidence describes the receive path and downstream channel set visible to the modem. It should not be confused with end-to-end application download throughput, which also depends on provisioning, scheduling, routing, and clients.",
    ),
    _term(
        "upstream",
        "modulation_channels",
        "Upstream",
        ("Upload direction", "US", "Upstream channels"),
        ("DOCSIS", "SC-QAM", "OFDMA"),
        ("downstream", "ofdma", "power_level", "partial_service"),
        "Upstream is data going from your home toward the internet, like an upload leaving your house.",
        "In DOCSIS, upstream channels carry data from the modem back to the provider network. Upstream problems often show up as high transmit power, channel drops, or noisy return-path behavior.",
        "Upstream may use SC-QAM and/or OFDMA. It is scheduled by the provider-side system, so local modem data shows transmit conditions but not every reason upload throughput may vary.",
        "Upstream interpretation needs transmit power, channel lock, modulation/profile state, ranging status, and return-path noise context. DOCSight should keep modem-visible RF evidence separate from CMTS-side scheduling or service-flow policy.",
    ),
    _term(
        "channel_bonding",
        "modulation_channels",
        "Channel bonding",
        ("Bonded channels", "Channel bundle", "DOCSIS bonding"),
        ("DOCSIS", "SC-QAM", "OFDM", "OFDMA"),
        ("downstream", "upstream", "sc_qam", "ofdm", "ofdma"),
        "Channel bonding lets a modem use several cable channels together, like using more than one lane.",
        "DOCSIS modems often use multiple downstream and upstream channels at the same time. More bonded channels can add capacity, but it still does not guarantee a matching speedtest result.",
        "Bonding combines several channel resources, while scheduling, modulation, signal quality, service limits, and protocol overhead determine what can become usable throughput.",
        "Bonded-channel capacity must distinguish SC-QAM sums from OFDM/OFDMA profile-dependent capacity. Service-flow limits, MAC scheduling, FEC, RF impairment, and contention separate bonded PHY capacity from application goodput.",
    ),
    _term(
        "sc_qam",
        "modulation_channels",
        "SC-QAM",
        ("Single-carrier QAM", "DOCSIS 3.0 channel", "QAM channel"),
        ("SC-QAM", "DOCSIS", "QAM", "Layer-1"),
        ("qam_modulation_order", "channel_width_symbol_rate", "ofdm", "capacity_vs_throughput"),
        "SC-QAM is one kind of cable channel. Think of it as one lane that can carry data between the cable network and your modem.",
        "SC-QAM channels are traditional DOCSIS channels. DOCSight can often estimate their gross Layer-1 capacity from modulation and channel details.",
        "SC-QAM uses a single carrier with a fixed channel width and QAM modulation order. Higher modulation can carry more bits per symbol, but the estimate is still gross channel capacity, not IP throughput.",
        "For DOCSIS SC-QAM channels, modulation order, symbol rate, channel width, and PHY overhead determine gross Layer-1 estimates. FEC, MAC framing, scheduling, bonding, and IP overhead separate that estimate from usable application throughput.",
        ("An SC-QAM capacity estimate is not a speedtest result.",),
    ),
    _term(
        "ofdm",
        "modulation_channels",
        "OFDM",
        ("DOCSIS 3.1 downstream", "Orthogonal frequency-division multiplexing"),
        ("OFDM", "DOCSIS", "SC-QAM"),
        ("ofdma", "sc_qam", "qam_modulation_order", "capacity_vs_throughput"),
        "OFDM is a newer downstream cable channel type that splits a wide channel into many tiny pieces.",
        "DOCSIS 3.1 uses OFDM downstream for flexible, high-capacity receive channels. DOCSight may show their signal state even when it cannot calculate the same simple capacity number as SC-QAM.",
        "OFDM downstream channels use many subcarriers and profiles. Real usable capacity depends on profile assignment, subcarrier health, exclusion bands, and provider-side scheduling.",
        "OFDM capacity estimation requires profile and subcarrier context. Without sufficient profile data, DOCSight should treat OFDM as observed but not included in SC-QAM-only gross capacity sums.",
        ("Missing OFDM capacity does not mean the channel is unused; DOCSight may simply lack safe profile-level data.",),
    ),
    _term(
        "ofdma",
        "modulation_channels",
        "OFDMA",
        ("DOCSIS 3.1 upstream", "Orthogonal frequency-division multiple access"),
        ("OFDMA", "DOCSIS", "SC-QAM"),
        ("ofdm", "upstream", "power_level", "capacity_vs_throughput"),
        "OFDMA is a newer upstream cable channel type that lets many modems share tiny pieces of a wide channel.",
        "DOCSIS 3.1 uses OFDMA upstream for flexible upload channels. DOCSight may show OFDMA signal or power data, but simple SC-QAM-style capacity math is usually not safe without more detail.",
        "OFDMA upstream capacity depends on subcarrier allocation, profile assignment, minislot scheduling, return-path noise, and provider-side decisions that a modem page may not expose fully.",
        "OFDMA telemetry needs profile/subcarrier and scheduling context for safe interpretation. Aggregate report power and per-subcarrier evidence should not be mixed unless the driver exposes the exact intended metric.",
        ("An OFDMA channel without a displayed capacity number can still be active and important.",),
    ),
    _term(
        "qam_modulation_order",
        "modulation_channels",
        "QAM / modulation order",
        ("QAM", "256-QAM", "4096-QAM", "Modulation"),
        ("QAM", "DOCSIS", "SC-QAM", "OFDM", "OFDMA"),
        ("sc_qam", "ofdm", "snr_mer", "layer1_capacity"),
        "Modulation is how data is packed into the cable signal. Higher QAM numbers can carry more data, but need a cleaner signal.",
        "QAM/modulation order affects how many bits a channel can carry. If signal quality is poor, a channel may need a lower modulation and therefore carry less gross capacity.",
        "Higher modulation orders increase bits per symbol but reduce tolerance for noise and distortion. Modulation must be interpreted with SNR/MER, channel type, and profile context.",
        "For SC-QAM, modulation order directly feeds Layer-1 capacity estimates with symbol rate and channel width. For OFDM/OFDMA, profile/subcarrier assignment makes the relationship more complex than one label per channel.",
    ),
    _term(
        "channel_width_symbol_rate",
        "modulation_channels",
        "Channel width / symbol rate",
        ("Channel width", "Symbol rate", "MHz", "Msym/s"),
        ("DOCSIS", "SC-QAM", "MHz"),
        ("sc_qam", "qam_modulation_order", "layer1_capacity"),
        "Channel width is how much frequency space a channel uses. Symbol rate is how fast signal steps are sent inside that channel.",
        "For supported SC-QAM channels, channel width, symbol rate, and modulation help estimate gross Layer-1 capacity. These inputs still do not produce real IP throughput by themselves.",
        "DOCSIS channel plans use defined widths and symbol rates. Capacity math depends on the channel family; SC-QAM can be estimated more directly than OFDM/OFDMA without profile data.",
        "Capacity calculations should keep channel-family assumptions explicit. EuroDOCSIS/DOCSIS widths, symbol rates, modulation order, and PHY overhead must not be reused blindly across OFDM/OFDMA profiles.",
    ),
    _term(
        "power_level",
        "signal_quality",
        "Power level",
        ("Signal level", "dBmV", "Receive power", "Transmit power"),
        ("dBmV", "DOCSIS", "DOCSight"),
        ("coaxial_cable", "attenuation", "upstream", "snr_mer"),
        "Power level is how strong the cable signal looks to the modem, or how hard the modem must talk back.",
        "DOCSight can show downstream receive power and upstream transmit power when the modem exposes them. Values outside expected ranges can indicate cabling, splitter, amplifier, or return-path issues.",
        "Power must be interpreted by direction and channel type. A clean-looking downstream value does not automatically prove upstream health, and high upstream transmit power can suggest the modem is working hard to reach the provider side.",
        "Power diagnostics need units, direction, channel family, and device-driver semantics. OFDMA aggregate power and per-1.6 MHz report power should not be treated as interchangeable metrics.",
    ),
    _term(
        "snr_mer",
        "signal_quality",
        "SNR/MER",
        ("Signal-to-noise ratio", "Modulation error ratio", "MER", "SNR"),
        ("SNR", "MER", "DOCSIS", "QAM"),
        ("power_level", "ingress_noise", "qam_modulation_order", "uncorrectable_errors"),
        "SNR/MER says how clear the signal is compared with noise. Clearer signal makes higher data packing more reliable.",
        "SNR and MER are quality measurements. Better values usually mean the modem can decode the channel more reliably, but they still do not directly equal speedtest performance.",
        "SNR/MER should be interpreted alongside modulation, channel family, and error counters. A marginal value can cause lower profiles, correctable errors, or uncorrectable errors depending on severity.",
        "MER/SNR thresholds are modulation- and implementation-dependent. DOCSight should avoid claiming provider fault from one value alone; correlation with channel lock, modulation profile, FEC counters, and time trend is stronger evidence.",
    ),
    _term(
        "attenuation",
        "signal_quality",
        "Attenuation",
        ("Signal loss", "Damping", "Cable loss"),
        ("DOCSIS", "dBmV", "DOCSight"),
        ("coaxial_cable", "power_level", "ingress_noise"),
        "Attenuation means the signal gets weaker as it travels through cable, splitters, and connectors.",
        "Some signal loss is normal, but too much loss can push power levels out of range or force the modem to transmit harder upstream. DOCSight sees the effect, not every physical cause.",
        "Attenuation can come from cable length, splitters, wall outlets, filters, bad connectors, or plant conditions. It often appears indirectly through receive power, transmit power, SNR/MER, or channel stability.",
        "Do not infer a precise dB loss path from modem stats alone. Treat attenuation as a diagnostic hypothesis supported by direction-specific power changes, topology knowledge, and before/after wiring evidence.",
    ),
    _term(
        "ingress_noise",
        "signal_quality",
        "Ingress/noise",
        ("Noise", "Ingress", "Interference", "Return-path noise"),
        ("DOCSIS", "SNR", "MER", "OFDMA"),
        ("snr_mer", "correctable_errors", "uncorrectable_errors", "upstream"),
        "Noise is unwanted signal mixed into the cable signal. Too much noise makes data harder to read.",
        "Ingress and noise can reduce SNR/MER, cause errors, or make upstream communication unstable. DOCSight can show symptoms when the modem exposes affected signal and error data.",
        "Noise may be intermittent, direction-specific, or limited to certain frequencies. A time trend across affected channels is usually more useful than one isolated snapshot.",
        "Return-path ingress, impulse noise, common-path distortion, and local cabling faults can affect DOCSIS channels differently. DOCSight should present modem-visible evidence without claiming full plant localization.",
    ),
    _term(
        "correctable_errors",
        "error_counters",
        "Correctable errors",
        ("Correctables", "Corrected codewords", "FEC corrected"),
        ("DOCSIS", "FEC", "DOCSight"),
        ("uncorrectable_errors", "snr_mer", "ingress_noise"),
        "Correctable errors are small mistakes the modem could fix before they became lost data.",
        "Correctable counters can rise even on a working line. The rate, timing, affected channels, and whether uncorrectables also rise matter more than one raw total.",
        "Correctables reflect FEC work. Growth during noise events, high rates on specific channels, or correlation with low MER can be useful; old cumulative totals alone are weak evidence.",
        "Keep raw modem counters separate from derived rates. DOCSight should preserve cumulative values as evidence while using observation windows, baselines, and growth rates for health interpretation.",
        ("A high old correctable total is not automatically an active fault.",),
    ),
    _term(
        "uncorrectable_errors",
        "error_counters",
        "Uncorrectable errors",
        ("Uncorrectables", "Uncorrected codewords", "FEC uncorrected"),
        ("DOCSIS", "FEC", "DOCSight"),
        ("correctable_errors", "snr_mer", "ingress_noise"),
        "Uncorrectable errors are mistakes the modem could not fix. They are more serious than correctable errors.",
        "Uncorrectables can indicate lost data at the channel level, especially when they grow during the observation window. Their timing and growth rate matter more than an old counter total.",
        "Uncorrectables should be correlated with SNR/MER, channel lock, modulation changes, and user-visible symptoms. A reset or reboot can also change raw counter behavior.",
        "For evidence, retain raw uncorrectable counters and compute derived growth from a known baseline. Avoid rewriting modem totals; distinguish counter resets, wraparound, and current observation-window spikes.",
    ),
    _term(
        "layer1_capacity",
        "capacity_throughput",
        "Layer-1 capacity",
        ("PHY capacity", "Physical layer capacity", "Channel capacity"),
        ("Layer-1", "DOCSIS", "SC-QAM", "IP"),
        ("gross_vs_net_capacity", "sc_qam", "capacity_vs_throughput"),
        "Layer-1 capacity is a theory number for what the cable signal layer can carry before real-world overhead is removed.",
        "DOCSight may estimate Layer-1 gross capacity for supported SC-QAM channels. This is useful channel context, but it is not a promise of usable internet speed.",
        "Layer-1 capacity sits below MAC scheduling, FEC, bonding behavior, service-flow limits, IP overhead, application behavior, and segment load. It is one diagnostic layer, not the whole connection.",
        "PHY/Layer-1 capacity should be labeled as gross channel evidence. Do not equate it with service-flow rates, TCP/UDP goodput, speedtest results, or contractual tariff speed.",
    ),
    _term(
        "gross_vs_net_capacity",
        "capacity_throughput",
        "Gross vs. net capacity",
        ("Gross capacity", "Net throughput", "Overhead"),
        ("DOCSIS", "Layer-1", "IP"),
        ("layer1_capacity", "ip_throughput", "speedtest"),
        "Gross is before overhead. Net is closer to what is left after the network uses some space for making communication work.",
        "A gross channel estimate starts before DOCSIS, IP, and application overhead. Net throughput is lower and also depends on scheduling, provider limits, clients, and the path to the server.",
        "Gross-to-net differences come from PHY overhead, FEC, MAC framing, contention, service-flow shaping, IP/TCP/UDP overhead, and application behavior. Different tests measure different layers.",
        "Keep measurement layer explicit: PHY gross capacity, MAC/service-flow rates, IP throughput, and application goodput are separate. Mixing those layers creates misleading comparisons.",
    ),
    _term(
        "ip_throughput",
        "capacity_throughput",
        "IP throughput",
        ("Internet throughput", "Goodput", "Usable speed"),
        ("IP", "DOCSIS", "Speedtest"),
        ("gross_vs_net_capacity", "speedtest", "tariff_speed"),
        "IP throughput is the real data that makes it through your internet connection after network overhead and limits.",
        "IP throughput is closer to what apps and speedtests experience than channel capacity is. It depends on DOCSIS health, provider configuration, routing, Wi-Fi/LAN, and the remote server.",
        "Throughput can be lower than channel capacity because of provisioning, scheduling, contention, traffic shaping, packet loss, latency, client limits, and server-side bottlenecks.",
        "Goodput/throughput is an end-to-end result. DOCSight modem diagnostics can explain local DOCSIS-layer evidence, but they should not claim sole causality for an IP throughput result without supporting data.",
    ),
    _term(
        "speedtest",
        "capacity_throughput",
        "Speedtest",
        ("Speed test", "Download test", "Upload test", "Ookla"),
        ("Speedtest", "IP", "DOCSIS", "DOCSight"),
        ("ip_throughput", "tariff_speed", "capacity_vs_throughput"),
        "A speedtest checks how fast data moves to and from a test server right now.",
        "A speedtest is an end-to-end measurement at one moment. It is affected by DOCSIS health, tariff limits, segment load, Wi-Fi/LAN, routing, and the chosen test server.",
        "Speedtests can help validate user impact, but they are not the same as channel diagnostics. A low result needs correlation with modem evidence, client path, and provider/service limits.",
        "Treat speedtest data as IP/application-layer evidence. Compare it against tariff speed and diagnostic timelines, not directly against PHY gross SC-QAM capacity or raw channel counts.",
    ),
    _term(
        "tariff_speed",
        "capacity_throughput",
        "Tariff speed",
        ("Booked speed", "Plan speed", "Contract speed", "Provisioned speed"),
        ("DOCSIS", "CMTS", "IP"),
        ("provisioning", "speedtest", "capacity_vs_throughput"),
        "Tariff speed is the internet plan you pay for, such as a booked download and upload rate.",
        "Tariff speed is a product and provisioning boundary. DOCSight channel data can show whether the cable link looks healthy, but it cannot prove every provider-side policy or contractual detail.",
        "The plan speed is usually enforced through provider configuration and service-flow limits. Real speed also depends on network load, modem state, routing, and local client conditions.",
        "Do not infer the exact subscriber service-flow configuration solely from channel capacity. Use explicit provisioning or speedtest evidence when available, and keep DOCSight capacity labels separate from tariff claims.",
    ),
    _term(
        "segment_utilization",
        "capacity_throughput",
        "Segment utilization",
        ("Segment load", "Congestion", "Node load", "Service group load"),
        ("DOCSIS", "CMTS", "DOCSight"),
        ("shared_medium", "node_segment", "speedtest"),
        "Segment utilization means how busy the shared cable segment is.",
        "A busy segment can reduce real speeds even when your modem signal looks good. DOCSight should not claim exact segment utilization unless a supported source exposes that data.",
        "Segment load depends on service-group sizing, active subscribers, channel capacity, CMTS scheduling, and time of day. Local modem evidence may show symptoms but not the full utilization denominator.",
        "Complete utilization requires provider-side or supported external evidence. Avoid deriving total segment load from a single modem's channel list, speedtest, or signal state alone.",
        ("Good modem signal is not proof of an uncongested segment.",),
    ),
    _term(
        "capacity_vs_throughput",
        "capacity_throughput",
        "Capacity vs. speedtest",
        ("Throughput", "Capacity vs throughput"),
        ("Layer-1", "SC-QAM", "Speedtest", "IP", "DOCSight"),
        ("layer1_capacity", "gross_vs_net_capacity", "speedtest", "tariff_speed", "shared_medium"),
        "Capacity is what the cable lane could carry in theory. A speedtest is what your connection delivers right now after many other things are included.",
        "DOCSight capacity estimates describe channel-level gross capacity, especially for supported SC-QAM channels. They are not your tariff speed, not a speedtest, and not guaranteed real IP throughput.",
        "Layer-1 channel capacity is before MAC, FEC, scheduling, bonding, segment load, traffic shaping, and IP/application overhead. Speedtests measure an end-to-end path at one moment in time.",
        "Do not equate PHY gross capacity with service-flow rate limits or TCP/UDP goodput. CMTS scheduling, provisioning, OFDM/OFDMA profile availability, RF impairment, queueing, peering, and test-server behavior can all dominate observed throughput.",
        ("A channel capacity sum is not proof that a customer should see the same number in a speedtest.", "Tariff speed is a product configuration; DOCSight channel diagnostics are local evidence."),
    ),
    _term(
        "provisioning",
        "modem_state",
        "Provisioning",
        ("Provisioned service", "Service flow", "Activation", "Plan config"),
        ("DOCSIS", "CMTS", "IP"),
        ("bootfile_config_file", "tariff_speed", "partial_service"),
        "Provisioning is how the provider tells the modem what service it should have.",
        "Provisioning controls whether the modem is allowed online and which service limits apply. DOCSight may show hints, but the provider-side configuration is not always fully visible from the modem.",
        "Provisioning can affect tariff speed, service flows, modem authorization, bootfile/config assignment, and enabled features. It is separate from raw RF signal quality.",
        "Treat provisioning as a provider-controlled DOCSIS/MAC-layer contract. Local modem pages may expose bootfile names or service state, but not all CMTS policy or subscriber-account logic.",
    ),
    _term(
        "bootfile_config_file",
        "modem_state",
        "Bootfile/config file",
        ("Bootfile", "Config file", "DOCSIS config", "Service config"),
        ("DOCSIS", "CMTS", "DOCSight"),
        ("provisioning", "tariff_speed", "cable_modem_router"),
        "The bootfile/config file is provider instructions the modem receives when it starts.",
        "A DOCSIS config file can define service behavior such as rate limits and enabled features. Some modems expose the name; DOCSight should not assume the full contents from the name alone.",
        "Bootfile evidence can support provisioning diagnosis, but names are provider-specific and may not map cleanly to public tariff labels. It should be used carefully and with other evidence.",
        "DOCSIS config files are part of modem registration/provisioning. Without the actual file contents and CMTS context, a displayed filename is only a hint, not a complete service-flow contract.",
    ),
    _term(
        "partial_service",
        "modem_state",
        "Partial service",
        ("Partial bonding", "Missing channels", "Partial channel lock"),
        ("DOCSIS", "SC-QAM", "OFDM", "OFDMA"),
        ("channel_bonding", "downstream", "upstream", "resync_reboot"),
        "Partial service means the modem is online but not using all expected channels or functions.",
        "A modem in partial service may still provide internet, but with fewer channels, lower resilience, or reduced performance. DOCSight can help show which visible channel families are affected.",
        "Partial service can come from RF issues, profile/channel problems, maintenance, provisioning, or modem/CMTS behavior. It should be interpreted with channel lock, errors, power, and event timing.",
        "Do not treat partial service as one fixed cause. Diagnose by direction, channel family, event log, RF metrics, and whether the condition persists across resync/reboot or provider maintenance windows.",
    ),
    _term(
        "resync_reboot",
        "modem_state",
        "Resync/reboot",
        ("Modem reboot", "Resynchronization", "Ranging restart", "Reconnect"),
        ("DOCSIS", "CMTS", "DOCSight"),
        ("partial_service", "provisioning", "correctable_errors", "uncorrectable_errors"),
        "A reboot restarts the modem. A resync makes it reconnect to the cable network.",
        "Reboots and resyncs can temporarily clear counters, change channel assignment, or restore service after a fault. If they happen unexpectedly, the timing is important evidence.",
        "A resync can be triggered by maintenance, RF instability, provisioning changes, power loss, modem firmware, or provider-side events. Compare before/after snapshots rather than reading one state alone.",
        "For evidence, preserve timestamps, event logs, channel changes, and counter-baseline effects around reboot/resync events. Do not interpret reset counters as proof that earlier impairment never happened.",
    ),
)

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
        for alias in (term.title.get("en", ""), *term.aliases.get("en", ())):
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
