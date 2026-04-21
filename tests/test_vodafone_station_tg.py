from unittest.mock import patch, MagicMock

from app.drivers.vodafone_station import VodafoneStationDriver

# ===== Embedded fixture HTML =====
# Two pages are fetched per call:
#   status_data  -> /php/status_status_data.php  (js_* markers)
#   status_status -> /?status_status             (_ga.* markers)
FIXTURES = {

"happy_path": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = '0,3,25';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'DOCSIS Online';
_ga.lastRebootReason = 'Power On';
</script>
""",
},

"empty_fields": {
    "status_data": """
<script>
js_HWTypeVersion = '';
js_FWVersion = '';
js_ipv4addr = '';
js_ipv6addr = '';
js_UptimeSinceReboot = '';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = '';
_ga.lastRebootReason = '';
</script>
""",
},

"missing_markers": {
    "status_data": """
<script>
</script>
""",
    "status_status": """
<script>
</script>
""",
},

"unknown_input": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = '0,3,25';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'Scanning Frequencies';
_ga.lastRebootReason = 'Firmware Update';
</script>
""",
},

"malformed_input": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = 'a-b-c';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'DOCSIS Online';
_ga.lastRebootReason = 'Power On';
</script>
""",
},
}

# ===== Helper to mock router responses =====
def mock_router_responses(driver, section_id):
    fixture = FIXTURES[section_id]

    with patch.object(driver._session, "get") as mock_get:
        mock_resp1 = MagicMock()
        mock_resp1.text = fixture["status_data"]
        mock_resp1.raise_for_status = MagicMock()

        mock_resp2 = MagicMock()
        mock_resp2.text = fixture["status_status"]
        mock_resp2.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_resp1, mock_resp2]
        return driver._get_device_info_tg()

# ===== Global driver =====
driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")

# ===== Tests =====
def test_happy_path():
    result = mock_router_responses(driver, "happy_path")
    assert result["hw_version"] == "HW1"
    assert result["sw_version"] == "SW1"
    assert result["docsis_status"].lower() == "online"
    assert result["uptime_seconds"] == 3*3600 + 25*60
    assert result["wan_ipv4"] == "192.168.1.2"
    assert result["wan_ipv6"] == "fe80::1"
    assert result["reboot_reason"].lower() == "power on"

def test_empty_fields():
    result = mock_router_responses(driver, "empty_fields")
    assert result.get("sw_version", "") == ""
    assert result.get("hw_version", "") == ""
    assert result.get("reboot_reason", "") == ""
    assert result.get("docsis_status", "") == ""
    assert result.get("uptime_seconds", "") == 0
    assert result.get("wan_ipv4", "") == ""
    assert result.get("wan_ipv6", "") == ""

def test_missing_marker():
    result = mock_router_responses(driver, "missing_markers")
    assert result.get("sw_version", "") == ""
    assert result.get("hw_version", "") == ""
    assert result.get("reboot_reason", "") == ""
    assert result.get("docsis_status", "") == ""
    assert result.get("uptime_seconds", "") == 0
    assert result.get("wan_ipv4", "") == ""
    assert result.get("wan_ipv6", "") == ""

def test_unknown_input():
    result = mock_router_responses(driver, "unknown_input")
    assert result["docsis_status"] == "scanning frequencies"
    assert result["reboot_reason"] == "firmware update"

def test_malformed_input():
    result = mock_router_responses(driver, "malformed_input")
    assert result["uptime_seconds"] == 0
