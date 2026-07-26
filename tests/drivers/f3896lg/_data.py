"""Fixture payloads captured from a Virgin Media (UK) Hub 5 in modem mode.

Sagemcom F3896LG-VMB, Liberty Global firmware, /rest/v1/ REST API.
Identifiers (MAC/serial) are anonymised; signal values are real.
"""

DOWNSTREAM = {
    "downstream": {
        "channels": [
            {"channelType": "sc_qam", "channelId": 1, "frequency": 411000000,
             "power": -4.3, "modulation": "qam_256", "snr": 39, "rxMer": 39,
             "correctedErrors": 26, "uncorrectedErrors": 0, "lockStatus": True},
            {"channelType": "sc_qam", "channelId": 2, "frequency": 419000000,
             "power": -4.5, "modulation": "qam_256", "snr": 39, "rxMer": 39,
             "correctedErrors": 30, "uncorrectedErrors": 0, "lockStatus": True},
            # unlocked channel must be skipped
            {"channelType": "sc_qam", "channelId": 3, "frequency": 427000000,
             "power": -4.4, "modulation": "qam_256", "snr": 38, "rxMer": 38,
             "correctedErrors": 0, "uncorrectedErrors": 0, "lockStatus": False},
            # OFDM (DOCSIS 3.1): power scaled x10 by firmware, no frequency key
            {"channelType": "ofdm", "channelId": 41, "channelWidth": 94000000,
             "fftType": "4K", "numberOfActiveSubCarriers": 1840,
             "modulation": "qam_4096", "firstActiveSubcarrier": 1108,
             "lockStatus": True, "rxMer": 0, "power": -118,
             "correctedErrors": 1361678039, "uncorrectedErrors": 483483438},
        ]
    }
}

UPSTREAM = {
    "upstream": {
        "channels": [
            {"channelId": 6, "frequency": 49600000, "lockStatus": True,
             "power": 42.5, "symbolRate": 5120, "modulation": "qam_64",
             "t1Timeout": 0, "t2Timeout": 0, "t3Timeout": 0, "t4Timeout": 0,
             "channelType": "atdma"},
            {"channelId": 7, "frequency": 43100000, "lockStatus": True,
             "power": 42, "symbolRate": 5120, "modulation": "qam_64",
             "t1Timeout": 0, "t2Timeout": 0, "t3Timeout": 0, "t4Timeout": 0,
             "channelType": "atdma"},
            # OFDMA (DOCSIS 3.1): power scaled x10 by firmware
            {"channelId": 12, "channelWidth": 10400000, "lockStatus": True,
             "power": 380, "fftType": "2K", "modulation": "qam_256",
             "channelType": "ofdma", "numberOfActiveSubCarriers": 208,
             "firstActiveSubcarrier": 74, "t3Timeout": 0, "t4Timeout": 0},
        ]
    }
}

STATE = {
    "cablemodem": {
        "bootFilename": "cmreg-example.cm",
        "docsisVersion": "3.1",
        "macAddress": "00:11:22:33:44:55",
        "serialNumber": "EXAMPLE000000",
        "upTime": 72394,
        "accessAllowed": True,
        "status": "operational",
        "maxCPEs": 1,
        "baselinePrivacyEnabled": True,
    }
}

REGISTRATION = {"registration": {"registrationComplete": True, "downstreamLocked": True}}

SERVICEFLOWS = {
    "serviceFlows": [
        {"serviceFlow": {"serviceFlowId": 217640, "direction": "downstream",
                         "maxTrafficRate": 1230000450, "maxTrafficBurst": 42600,
                         "minReservedRate": 0, "maxConcatenatedBurst": 0,
                         "scheduleType": "undefined"}},
        {"serviceFlow": {"serviceFlowId": 217639, "direction": "upstream",
                         "maxTrafficRate": 110000274, "maxTrafficBurst": 42600,
                         "minReservedRate": 0, "maxConcatenatedBurst": 42600,
                         "scheduleType": "best_effort"}},
    ]
}
