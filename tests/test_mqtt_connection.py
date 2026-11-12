"""MQTT connection handling: a broker that is down at startup or restarts later."""

import logging
import socket
import threading
import time
from unittest.mock import MagicMock

import pytest

from app.modules.mqtt.publisher import MQTTPublisher


class _MiniBroker:
    """Just enough MQTT 3.1.1 to accept a client and record what it publishes."""

    def __init__(self, port=0):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", port))
        self._server.listen()
        self._server.settimeout(0.2)
        self.port = self._server.getsockname()[1]
        self.published = []
        self._clients = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (socket.timeout, OSError):
                continue
            self._clients.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _read_exact(conn, size):
        data = b""
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def _read_packet(self, conn):
        header = self._read_exact(conn, 1)[0]
        length, shift = 0, 0
        while True:
            byte = self._read_exact(conn, 1)[0]
            length |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        return header, self._read_exact(conn, length)

    def _serve(self, conn):
        try:
            while not self._stop.is_set():
                header, body = self._read_packet(conn)
                kind = header >> 4
                if kind == 1:  # CONNECT
                    conn.sendall(b"\x20\x02\x00\x00")
                elif kind == 3:  # PUBLISH (QoS 0)
                    topic_len = int.from_bytes(body[:2], "big")
                    topic = body[2:2 + topic_len].decode()
                    payload = body[2 + topic_len:].decode()
                    self.published.append((topic, payload, bool(header & 0x01)))
                elif kind == 12:  # PINGREQ
                    conn.sendall(b"\xd0\x00")
                elif kind == 14:  # DISCONNECT
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()

    def drop_clients(self):
        for conn in self._clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._clients.clear()

    def close(self):
        self._stop.set()
        self.drop_clients()
        self._server.close()
        self._thread.join(timeout=2)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _publisher(port):
    return MQTTPublisher("127.0.0.1", port=port, topic_prefix="docsight")


@pytest.fixture
def broker():
    instances = []

    def start(port=0):
        instance = _MiniBroker(port)
        instances.append(instance)
        return instance

    yield start
    for instance in instances:
        instance.close()


def test_connect_does_not_fail_when_broker_is_down(broker):
    port = _free_port()
    publisher = _publisher(port)
    try:
        publisher.connect()  # must not raise
        assert not publisher.is_connected
        assert publisher.connection_count == 0

        server = broker(port)
        assert _wait_for(lambda: publisher.is_connected), "publisher never connected once the broker was up"
        assert publisher.connection_count == 1
        assert _wait_for(lambda: ("docsight/status", "online", True) in server.published)
    finally:
        publisher.disconnect()


def test_reconnect_sends_online_again_and_counts_the_connection(broker):
    server = broker()
    publisher = _publisher(server.port)
    try:
        publisher.connect()
        assert _wait_for(lambda: publisher.connection_count == 1)

        server.published.clear()
        server.drop_clients()
        # The broker now holds the "offline" will; the client must announce itself again.
        assert _wait_for(lambda: publisher.connection_count == 2), "publisher did not reconnect"
        assert _wait_for(lambda: ("docsight/status", "online", True) in server.published)
        assert publisher.is_connected
    finally:
        publisher.disconnect()


def test_connect_failures_are_logged_once_per_outage(caplog):
    publisher = object.__new__(MQTTPublisher)
    publisher.host, publisher.port, publisher.topic_prefix = "broker", 1883, "docsight"
    publisher._connected = False
    publisher._connection_count = 0
    publisher._connect_fail_logged = False
    client = MagicMock()

    with caplog.at_level(logging.WARNING, logger="docsis.mqtt"):
        publisher._on_connect_fail(client, None)
        publisher._on_connect_fail(client, None)
        publisher._on_connect(client, None, None, 0)
        publisher._on_connect_fail(client, None)

    warnings = [r for r in caplog.records if "not reachable" in r.getMessage()]
    assert len(warnings) == 2
