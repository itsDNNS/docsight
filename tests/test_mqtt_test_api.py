"""The MQTT connection test reports the broker's answer, never exception text."""

import ssl

import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from app.config import PASSWORD_MASK

DETAIL = "internal detail /data/.config_key"
SAVED = {"mqtt_host": "broker.local", "mqtt_port": 8883, "mqtt_user": "u", "mqtt_password": "stored-broker-password"}


class FakeClient:
    def __init__(self, reason=None, error=None, loop_rc=0):
        self.reason, self.error, self.loop_rc = reason, error, loop_rc
        self.on_connect, self.calls = None, []

    def connect(self, host, port):
        self.calls.append("connect")
        if self.error:
            raise self.error

    def loop_start(self):
        self.calls.append("loop_start")
        if self.reason and self.loop_rc == 0:
            self.on_connect(self, None, None, ReasonCode(PacketTypes.CONNACK, self.reason), None)
        return self.loop_rc

    def disconnect(self):
        self.calls.append("disconnect")

    def loop_stop(self):
        self.calls.append("loop_stop")


def _post(make_app, make_config, monkeypatch, client, **body):
    created = []
    monkeypatch.setattr("app.blueprints.polling_bp.MQTT_ANSWER_SECONDS", 0.01)
    monkeypatch.setattr("app.blueprints.polling_bp.create_client", lambda *args: created.append(args) or client)
    app = make_app(config_manager=make_config(SAVED))
    response = app.test_client().post("/api/test-mqtt", json={**SAVED, "mqtt_password": PASSWORD_MASK, **body})
    return response, created


@pytest.mark.parametrize(("client", "body", "calls"), [
    (FakeClient("Success"), {"success": True}, ["connect", "loop_start", "disconnect", "loop_stop"]),
    (FakeClient("Not authorized"), {"success": False, "error": "MQTT broker refused the connection: Not authorized"},
     ["connect", "loop_start", "disconnect", "loop_stop"]),
    (FakeClient(), {"success": False, "error": "MQTT broker did not answer"}, ["connect", "loop_start", "disconnect", "loop_stop"]),
    (FakeClient("Success", loop_rc=4), {"success": False, "error": "MQTT broker did not answer"},
     ["connect", "loop_start", "disconnect"]),
    (FakeClient(error=ConnectionRefusedError(DETAIL)), {"success": False, "error": "Cannot reach MQTT broker"},
     ["connect", "disconnect"]),
    (FakeClient(error=RuntimeError(DETAIL)), {"success": False, "error": "MQTT test failed, see the DOCSight log"},
     ["connect", "disconnect"]),
], ids=["accepted", "refused", "no-answer", "loop-not-started", "unreachable", "unexpected"])
def test_mqtt_test_waits_for_the_broker_answer(make_app, make_config, monkeypatch, client, body, calls):
    response, created = _post(make_app, make_config, monkeypatch, client, mqtt_tls_insecure="true")

    assert response.get_json() == body
    assert created == [("docsis-test", 8883, "u", "stored-broker-password", True)]
    assert client.calls == calls


@pytest.mark.parametrize("changed", [{"mqtt_host": "attacker.example"}, {"mqtt_port": 1883}, {"mqtt_user": "other"}])
def test_saved_password_only_goes_to_the_saved_broker(make_app, make_config, monkeypatch, changed):
    response, created = _post(make_app, make_config, monkeypatch, FakeClient("Success"), **changed)

    assert response.get_json() == {"success": False, "error": "Enter the password to test changed connection settings."}
    assert created == []


def test_new_broker_without_saved_password_can_be_tested(make_app, make_config, monkeypatch):
    created = []
    monkeypatch.setattr("app.blueprints.polling_bp.create_client", lambda *args: created.append(args) or FakeClient("Success"))
    app = make_app(config_manager=make_config({}))

    response = app.test_client().post("/api/test-mqtt", json={"mqtt_host": "new.local", "mqtt_password": PASSWORD_MASK})

    assert response.get_json() == {"success": True}
    assert created == [("docsis-test", 1883, None, None, False)]


@pytest.mark.parametrize(("payload", "error"), [
    (["not", "an", "object"], "No data"),
    ({"mqtt_port": "x"}, "Invalid broker settings"),
    ({"mqtt_port": 8.5}, "Invalid broker settings"),
    ({"mqtt_port": 70000}, "Invalid broker settings"),
    ({"mqtt_host": ["a"]}, "Invalid broker settings"),
    ({"mqtt_user": 5}, "Invalid broker settings"),
])
def test_malformed_requests_are_rejected(make_app, make_config, payload, error):
    app = make_app(config_manager=make_config(SAVED))
    response = app.test_client().post("/api/test-mqtt", json=payload)
    assert (response.status_code, response.get_json()) == (400, {"success": False, "error": error})


@pytest.mark.parametrize(("insecure", "verify", "hostname"), [(False, ssl.CERT_REQUIRED, True), (True, ssl.CERT_NONE, False)])
def test_insecure_tls_skips_the_certificate_check_for_self_signed_brokers(insecure, verify, hostname):
    from app.modules.mqtt.publisher import create_client

    context = create_client("docsis-test", 8883, tls_insecure=insecure)._ssl_context

    assert (context.verify_mode, context.check_hostname) == (verify, hostname)
