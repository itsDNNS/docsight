# -- Embedded channel strings from real S34 HAR capture --

DS_RAW = (
    "1^Locked^256QAM^43^705000000^ 0.0^40.9^31^0^"
    "|+|2^Locked^256QAM^44^711000000^ 0.1^41.0^25^0^"
    "|+|3^Locked^256QAM^45^717000000^ 0.2^41.1^18^0^"
    "|+|4^Locked^256QAM^46^723000000^ 0.3^41.2^12^0^"
    "|+|5^Locked^256QAM^47^729000000^ 0.4^41.3^8^0^"
    "|+|6^Locked^256QAM^48^735000000^ 0.5^41.4^5^0^"
    "|+|7^Locked^256QAM^49^741000000^ 0.6^41.5^3^0^"
    "|+|8^Locked^256QAM^50^747000000^ 0.7^41.6^2^0^"
    "|+|9^Locked^256QAM^51^753000000^ 0.8^41.7^1^0^"
    "|+|10^Locked^256QAM^52^759000000^ 0.9^41.8^0^0^"
    "|+|11^Locked^256QAM^53^765000000^ 1.0^41.9^0^0^"
    "|+|12^Locked^256QAM^54^771000000^ 1.1^42.0^0^0^"
    "|+|13^Locked^256QAM^55^777000000^ 1.2^42.1^0^0^"
    "|+|14^Locked^256QAM^56^783000000^ 1.3^42.2^0^0^"
    "|+|15^Locked^256QAM^57^789000000^ 1.4^42.3^0^0^"
    "|+|16^Locked^256QAM^58^795000000^ 1.5^42.4^0^0^"
    "|+|17^Locked^256QAM^27^555000000^-0.1^40.8^35^1^"
    "|+|18^Locked^256QAM^28^561000000^-0.2^40.7^40^2^"
    "|+|19^Locked^256QAM^29^567000000^-0.3^40.6^45^3^"
    "|+|20^Locked^256QAM^30^573000000^-0.4^40.5^50^4^"
    "|+|21^Locked^256QAM^31^579000000^-0.5^40.4^55^5^"
    "|+|22^Locked^256QAM^32^585000000^-0.6^40.3^60^6^"
    "|+|23^Locked^256QAM^33^591000000^-0.7^40.2^65^7^"
    "|+|24^Locked^256QAM^34^597000000^-0.8^40.1^70^8^"
    "|+|25^Locked^256QAM^35^603000000^-0.9^40.0^75^9^"
    "|+|26^Locked^256QAM^36^609000000^-1.0^39.9^80^10^"
    "|+|27^Locked^256QAM^37^615000000^-1.1^39.8^85^11^"
    "|+|28^Locked^256QAM^38^621000000^-1.2^39.7^90^12^"
    "|+|29^Locked^256QAM^39^627000000^-1.3^39.6^95^13^"
    "|+|30^Locked^256QAM^40^633000000^-1.4^39.5^100^14^"
    "|+|31^Locked^256QAM^41^639000000^-1.5^39.4^105^15^"
    "|+|32^Locked^256QAM^42^645000000^-1.6^39.3^110^16^"
    "|+|33^Locked^OFDM PLC^193^957000000^ 0.1^43.0^2467857853^7894^"
)

US_RAW = (
    "1^Locked^SC-QAM^3^6400000^29200000^46.5^"
    "|+|2^Locked^SC-QAM^4^6400000^35600000^45.0^"
    "|+|3^Locked^SC-QAM^2^6400000^22800000^44.5^"
    "|+|4^Locked^SC-QAM^1^6400000^16400000^44.0^"
    "|+|5^Locked^OFDMA^41^44400000^36200000^43.8^"
)

HNAP_DS_RESPONSE = {
    "GetMultipleHNAPsResponse": {
        "GetCustomerStatusDownstreamChannelInfoResponse": {
            "CustomerConnDownstreamChannel": DS_RAW,
            "GetCustomerStatusDownstreamChannelInfoResult": "OK",
        },
        "GetCustomerStatusUpstreamChannelInfoResponse": {
            "CustomerConnUpstreamChannel": US_RAW,
            "GetCustomerStatusUpstreamChannelInfoResult": "OK",
        },
    }
}

HNAP_DEVICE_RESPONSE = {
    "GetMultipleHNAPsResponse": {
        "GetCustomerStatusConnectionInfoResponse": {
            "StatusSoftwareModelName": "S34",
            "StatusSoftwareSfVer": "2.5.0.1-2-GA",
            "GetCustomerStatusConnectionInfoResult": "OK",
        },
    }
}

HNAP_DS_RESPONSE_MOTO = {
    "GetMultipleHNAPsResponse": {
        "GetMotoStatusDownstreamChannelInfoResponse": {
            "MotoConnDownstreamChannel": DS_RAW,
            "GetMotoStatusDownstreamChannelInfoResult": "OK",
        },
        "GetMotoStatusUpstreamChannelInfoResponse": {
            "MotoConnUpstreamChannel": US_RAW,
            "GetMotoStatusUpstreamChannelInfoResult": "OK",
        },
    }
}

HNAP_DEVICE_RESPONSE_MOTO = {
    "GetMultipleHNAPsResponse": {
        "GetMotoStatusConnectionInfoResponse": {
            "StatusSoftwareModelName": "SB8200",
            "StatusSoftwareSfVer": "AB01.02.053.05_080901_193.0A.NSH",
            "GetMotoStatusConnectionInfoResult": "OK",
        },
    }
}

HNAP_LOGIN_PHASE1 = {
    "LoginResponse": {
        "Challenge": "ABCDEF1234567890",
        "Cookie": "SESS_12345",
        "PublicKey": "PUB_KEY_9876",
        "LoginResult": "OK",
    }
}

HNAP_LOGIN_PHASE2 = {
    "LoginResponse": {
        "LoginResult": "OK",
    }
}
