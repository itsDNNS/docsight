"""The MQTT connection test reports the broker's answer, never exception text."""

import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from app.config import PASSWORD_MASK

DETAIL = "internal detail /data/.config_key"


class FakeClient:
    def __init__(self, reason=None, error=None):
        self.reason, self.error, self.on_connect, self.stopped = reason, error, None, False

    def connect(self, host, port, keepalive):
        if self.error:
            raise self.error

    def loop_start(self):
        if self.reason:
            self.on_connect(self, None, None, ReasonCode(PacketTypes.CONNACK, self.reason))

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        pass


@pytest.mark.parametrize(("client", "body"), [
    (FakeClient("Success"), {"success": True}),
    (FakeClient("Not authorized"), {"success": False, "error": "MQTT broker refused the connection: Not authorized"}),
    (FakeClient(), {"success": False, "error": "MQTT broker did not answer"}),
    (FakeClient(error=ConnectionRefusedError(DETAIL)), {"success": False, "error": "Cannot reach MQTT broker"}),
    (FakeClient(error=RuntimeError(DETAIL)), {"success": False, "error": "MQTT test failed, see the DOCSight log"}),
], ids=["accepted", "refused", "no-answer", "unreachable", "unexpected"])
def test_mqtt_test_waits_for_the_broker_answer(make_app, make_config, monkeypatch, client, body):
    created = []
    monkeypatch.setattr("app.blueprints.polling_bp.MQTT_ANSWER_SECONDS", 0.01)
    monkeypatch.setattr("app.blueprints.polling_bp.create_client", lambda *args: created.append(args) or client)
    app = make_app(config_manager=make_config({"mqtt_password": "stored-broker-password"}))

    response = app.test_client().post("/api/test-mqtt", json={
        "mqtt_host": "broker.local", "mqtt_port": 8883, "mqtt_user": "u",
        "mqtt_password": PASSWORD_MASK, "mqtt_tls_insecure": "true",
    })

    assert response.get_json() == body
    assert created == [("docsis-test", 8883, "u", "stored-broker-password", True)]
    assert client.stopped
