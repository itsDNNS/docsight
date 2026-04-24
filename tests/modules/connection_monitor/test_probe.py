"""Tests for the Connection Monitor probe engine."""

import socket
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.modules.connection_monitor.probe import ProbeEngine, ProbeResult


def _gai(family, sockaddr):
    """Return a single getaddrinfo tuple for the given family/sockaddr."""
    return [(family, socket.SOCK_STREAM, 0, "", sockaddr)]


class TestProbeResult:
    def test_success_result(self):
        r = ProbeResult(latency_ms=12.5, timeout=False, method="icmp")
        assert r.latency_ms == 12.5
        assert r.timeout is False
        assert r.method == "icmp"

    def test_timeout_result(self):
        r = ProbeResult(latency_ms=None, timeout=True, method="tcp")
        assert r.latency_ms is None
        assert r.timeout is True


class TestProbeEngineAutoDetection:
    def test_auto_selects_icmp_when_helper_check_succeeds(self):
        helper_ok = subprocess.CompletedProcess(
            args=["docsight-icmp-helper", "--check"],
            returncode=0,
            stdout="ok\n",
            stderr="",
        )
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=True), \
             patch("app.modules.connection_monitor.probe.os.access", return_value=True), \
             patch("app.modules.connection_monitor.probe.subprocess.run", return_value=helper_ok), \
             patch("app.modules.connection_monitor.probe.socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "icmp"

    def test_auto_selects_icmp_when_raw_socket_available(self):
        mock_sock = MagicMock()
        with patch("app.modules.connection_monitor.probe.socket.socket", return_value=mock_sock):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "icmp"

    def test_auto_falls_back_to_tcp_on_permission_error(self):
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=False), \
             patch("app.modules.connection_monitor.probe.socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_auto_falls_back_to_tcp_on_os_error(self):
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=False), \
             patch("app.modules.connection_monitor.probe.socket.socket", side_effect=OSError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_explicit_icmp(self):
        engine = ProbeEngine(method="icmp")
        assert engine.detected_method == "icmp"

    def test_explicit_tcp(self):
        engine = ProbeEngine(method="tcp")
        assert engine.detected_method == "tcp"

    def test_capability_info(self):
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=False), \
             patch("app.modules.connection_monitor.probe.socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            info = engine.capability_info()
            assert info["method"] == "tcp"
            assert "reason" in info


class TestTCPProbe:
    def test_tcp_success(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is False
            assert result.method == "tcp"
            assert result.latency_ms is not None
            assert result.latency_ms >= 0

    def test_tcp_timeout(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.side_effect = socket.timeout
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "tcp"

    def test_tcp_connection_refused(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 111  # ECONNREFUSED
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None


class TestICMPProbe:
    def test_icmp_helper_success(self):
        helper_ok = subprocess.CompletedProcess(
            args=["docsight-icmp-helper", "1.1.1.1", "2000"],
            returncode=0,
            stdout="5.23\n",
            stderr="",
        )
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=True), \
             patch("app.modules.connection_monitor.probe.os.access", return_value=True), \
             patch("app.modules.connection_monitor.probe.subprocess.run", side_effect=[
                 subprocess.CompletedProcess(
                     args=["docsight-icmp-helper", "--check"],
                     returncode=0,
                     stdout="ok\n",
                     stderr="",
                 ),
                 helper_ok,
             ]):
            engine = ProbeEngine(method="auto")
            result = engine.probe("1.1.1.1")
            assert result.timeout is False
            assert result.method == "icmp"
            assert result.latency_ms == 5.23

    def test_icmp_helper_timeout(self):
        with patch("app.modules.connection_monitor.probe.os.path.isfile", return_value=True), \
             patch("app.modules.connection_monitor.probe.os.access", return_value=True), \
             patch("app.modules.connection_monitor.probe.subprocess.run", side_effect=[
                 subprocess.CompletedProcess(
                     args=["docsight-icmp-helper", "--check"],
                     returncode=0,
                     stdout="ok\n",
                     stderr="",
                 ),
                 subprocess.CompletedProcess(
                     args=["docsight-icmp-helper", "1.1.1.1", "2000"],
                     returncode=1,
                     stdout="TIMEOUT\n",
                     stderr="",
                 ),
             ]):
            engine = ProbeEngine(method="auto")
            result = engine.probe("1.1.1.1")
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "icmp"

    def test_icmp_success(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=5.2, timeout=False, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is False
            assert result.latency_ms == 5.2
            assert result.method == "icmp"

    def test_icmp_timeout(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is True
            assert result.latency_ms is None


class TestIPv6Support:
    """Regression coverage for issue #361 — IPv6 targets must be probable."""

    def test_tcp_probe_uses_af_inet6_for_ipv6_literal(self):
        """An IPv6 literal must produce an AF_INET6 TCP socket."""
        engine = ProbeEngine(method="tcp")
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=_gai(socket.AF_INET6, ("2606:4700:4700::1111", 443, 0, 0)),
        ), patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            result = engine.probe("2606:4700:4700::1111", tcp_port=443)
            assert mock_cls.call_args.args[0] == socket.AF_INET6
            assert mock_cls.call_args.args[1] == socket.SOCK_STREAM
            sockaddr = mock_instance.connect_ex.call_args.args[0]
            assert sockaddr[0] == "2606:4700:4700::1111"
            assert sockaddr[1] == 443
            assert result.timeout is False
            assert result.method == "tcp"

    def test_tcp_probe_uses_af_inet_for_ipv4_literal(self):
        """IPv4 literals keep using AF_INET."""
        engine = ProbeEngine(method="tcp")
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=_gai(socket.AF_INET, ("1.1.1.1", 443)),
        ), patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            engine.probe("1.1.1.1", tcp_port=443)
            assert mock_cls.call_args.args[0] == socket.AF_INET
            sockaddr = mock_instance.connect_ex.call_args.args[0]
            assert sockaddr == ("1.1.1.1", 443)

    def test_tcp_probe_resolves_aaaa_only_hostname_to_ipv6(self):
        """A hostname returning only AAAA records must use AF_INET6."""
        engine = ProbeEngine(method="tcp")
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=_gai(socket.AF_INET6, ("2001:db8::1", 443, 0, 0)),
        ), patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            engine.probe("v6only.example.test", tcp_port=443)
            assert mock_cls.call_args.args[0] == socket.AF_INET6
            sockaddr = mock_instance.connect_ex.call_args.args[0]
            assert sockaddr[0] == "2001:db8::1"

    def test_tcp_probe_unresolvable_host_returns_clean_timeout(self):
        """A getaddrinfo failure must produce a timeout result, not raise."""
        engine = ProbeEngine(method="tcp")
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            side_effect=socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided"),
        ):
            result = engine.probe("definitely-not-resolvable.invalid", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "tcp"

    def test_icmp_helper_passes_ipv6_literal_unchanged(self):
        """The helper subprocess must receive the IPv6 literal verbatim."""
        helper_check = subprocess.CompletedProcess(
            args=["docsight-icmp-helper", "--check"],
            returncode=0,
            stdout="ok\n",
            stderr="",
        )
        helper_run = subprocess.CompletedProcess(
            args=["docsight-icmp-helper", "2606:4700:4700::1111", "2000"],
            returncode=0,
            stdout="7.50\n",
            stderr="",
        )
        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=True
        ), patch(
            "app.modules.connection_monitor.probe.os.access", return_value=True
        ), patch(
            "app.modules.connection_monitor.probe.subprocess.run",
            side_effect=[helper_check, helper_run],
        ) as mock_run:
            engine = ProbeEngine(method="auto")
            result = engine.probe("2606:4700:4700::1111")
            second_call = mock_run.call_args_list[1]
            invoked_args = second_call.args[0]
            assert invoked_args[1] == "2606:4700:4700::1111"
            assert result.timeout is False
            assert result.latency_ms == 7.5
            assert result.method == "icmp"

    def test_icmp_raw_fallback_uses_icmpv6_for_ipv6_target(self):
        """When the helper is missing, ICMPv6 must be attempted for IPv6 hosts."""
        engine = ProbeEngine(method="icmp")

        opened: list[tuple] = []

        def fake_socket(family, type_, proto):
            opened.append((family, type_, proto))
            return MagicMock(
                sendto=MagicMock(),
                recvfrom=MagicMock(side_effect=socket.timeout),
                close=MagicMock(),
                settimeout=MagicMock(),
            )

        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=[(
                socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6, "",
                ("2606:4700:4700::1111", 0, 0, 0),
            )],
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            result = engine.probe("2606:4700:4700::1111")
            assert any(
                entry[0] == socket.AF_INET6 and entry[2] == socket.IPPROTO_ICMPV6
                for entry in opened
            ), f"expected ICMPv6 raw socket, opened={opened}"
            assert result.method == "icmp"
            assert result.timeout is True

    def test_icmp_unresolvable_host_returns_clean_timeout(self):
        """A DNS failure on the ICMP path must not raise."""
        engine = ProbeEngine(method="icmp")
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            side_effect=socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided"),
        ):
            result = engine.probe("definitely-not-resolvable.invalid")
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "icmp"


class TestIPv6Regressions:
    """Regression coverage for the Codex review blockers on the #361 fix."""

    def test_icmp_raw_fallback_resolves_ipv4_literal_without_eai_service(self):
        """Raw ICMP must resolve IPv4 literals without tripping EAI_SERVICE.

        Linux/glibc returns EAI_SERVICE when ``getaddrinfo`` is called with
        ``port=0`` and ``SOCK_RAW`` — so the partial fix always fell straight to
        timeout before opening any raw socket, regressing IPv4 too.
        """
        opened: list[tuple] = []

        def fake_socket(family, type_, proto):
            opened.append((family, type_, proto))
            m = MagicMock()
            m.recvfrom.side_effect = socket.timeout
            return m

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            engine = ProbeEngine(method="icmp")
            engine.probe("1.1.1.1")

        assert any(
            fam == socket.AF_INET
            and type_ == socket.SOCK_RAW
            and proto == socket.IPPROTO_ICMP
            for fam, type_, proto in opened
        ), f"expected AF_INET/IPPROTO_ICMP raw socket; opened={opened}"

    def test_icmp_raw_fallback_resolves_ipv6_literal_without_eai_service(self):
        """Raw ICMPv6 must be reachable for an IPv6 literal via real getaddrinfo."""
        opened: list[tuple] = []

        def fake_socket(family, type_, proto):
            opened.append((family, type_, proto))
            m = MagicMock()
            m.recvfrom.side_effect = socket.timeout
            return m

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            engine = ProbeEngine(method="icmp")
            engine.probe("2606:4700:4700::1111")

        assert any(
            fam == socket.AF_INET6
            and type_ == socket.SOCK_RAW
            and proto == socket.IPPROTO_ICMPV6
            for fam, type_, proto in opened
        ), f"expected AF_INET6/IPPROTO_ICMPV6 raw socket; opened={opened}"

    def test_tcp_probe_iterates_when_first_family_socket_creation_fails(self):
        """TCP must try the next resolved address if the first socket fails."""
        engine = ProbeEngine(method="tcp")
        infos = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.1", 443)),
        ]
        created: list[tuple[int, int]] = []

        def fake_socket(family, type_, *args, **kwargs):
            created.append((family, type_))
            if family == socket.AF_INET6:
                raise OSError(97, "Address family not supported by protocol")
            m = MagicMock()
            m.connect_ex.return_value = 0
            return m

        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            result = engine.probe("dualstack.example.test", tcp_port=443)

        assert result.timeout is False
        assert result.method == "tcp"
        families = [fam for fam, _ in created]
        assert socket.AF_INET6 in families
        assert socket.AF_INET in families

    def test_tcp_probe_iterates_when_first_family_connect_fails(self):
        """TCP must try the next resolved address if the first connect_ex fails."""
        engine = ProbeEngine(method="tcp")
        infos = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.1", 443)),
        ]
        attempts: list[tuple[int, tuple]] = []

        def fake_socket(family, type_, *args, **kwargs):
            m = MagicMock()

            def connect_ex(sockaddr):
                attempts.append((family, sockaddr))
                return 0 if family == socket.AF_INET else 111  # ECONNREFUSED on v6

            m.connect_ex.side_effect = connect_ex
            return m

        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            result = engine.probe("dualstack.example.test", tcp_port=443)

        assert result.timeout is False
        assert result.method == "tcp"
        assert len(attempts) == 2
        assert attempts[0][0] == socket.AF_INET6
        assert attempts[1][0] == socket.AF_INET

    def test_tcp_probe_socket_oserror_does_not_escape(self):
        """Socket creation failure must return a clean timeout, never raise.

        Previously ``socket.socket`` sat outside the try/except, so an
        unsupported first family escaped into the collector as
        ``probe_method="error"``.
        """
        engine = ProbeEngine(method="tcp")
        infos = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
        ]
        with patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=OSError(97, "Address family not supported by protocol"),
        ):
            result = engine.probe("v6only.example.test", tcp_port=443)

        assert result.timeout is True
        assert result.latency_ms is None
        assert result.method == "tcp"

    def test_icmp_helper_c_source_handles_ipv6(self):
        """The setuid helper source must handle AF_INET6/ICMPv6 (not IPv4-only)."""
        helper_src = (
            Path(__file__).resolve().parents[3] / "tools" / "icmp_probe_helper.c"
        )
        src = helper_src.read_text()
        assert "AF_UNSPEC" in src, "helper must resolve with AF_UNSPEC, not AF_INET"
        assert "AF_INET6" in src, "helper must open AF_INET6 sockets"
        assert "IPPROTO_ICMPV6" in src, "helper must speak IPPROTO_ICMPV6"
        assert (
            "ICMP6_ECHO_REQUEST" in src or "128" in src
        ), "helper must send ICMPv6 echo request (type 128)"
        assert (
            "ICMP6_ECHO_REPLY" in src or "129" in src
        ), "helper must parse ICMPv6 echo reply (type 129)"


class TestDualStackFallback:
    """Codex gate 2: ICMP fallback must iterate addrinfo like TCP does.

    The partial fix resolved every (family, sockaddr) but then probed only
    ``addresses[0]``. A dual-stack hostname whose first usable family was
    IPv6 — e.g. IPv6 socket unsupported, sendto hits ENETUNREACH, or the
    echo never replies — would time out instead of falling back to IPv4.
    The C helper had the symmetrical bug in ``resolve_any``.
    """

    def test_icmp_raw_fallback_tries_ipv4_when_ipv6_socket_creation_fails(self):
        """IPv6 raw socket creation OSError must not short-circuit IPv4."""
        infos = [
            (
                socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6, "",
                ("2001:db8::1", 0, 0, 0),
            ),
            (
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP, "",
                ("198.51.100.1", 0),
            ),
        ]
        opened: list[tuple[int, int, int]] = []

        def fake_socket(family, type_, proto):
            opened.append((family, type_, proto))
            if family == socket.AF_INET6:
                raise OSError(97, "Address family not supported by protocol")
            m = MagicMock()
            m.recvfrom.side_effect = socket.timeout
            return m

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            engine = ProbeEngine(method="icmp")
            result = engine.probe("dualstack.example.test")

        families = [fam for fam, _, _ in opened]
        assert socket.AF_INET6 in families, (
            f"expected IPv6 attempt first; opened={opened}"
        )
        assert socket.AF_INET in families, (
            f"expected IPv4 fallback after IPv6 socket error; opened={opened}"
        )
        assert result.method == "icmp"

    def test_icmp_raw_fallback_tries_ipv4_when_ipv6_sendto_fails(self):
        """ENETUNREACH on the IPv6 address must not short-circuit IPv4."""
        infos = [
            (
                socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6, "",
                ("2001:db8::1", 0, 0, 0),
            ),
            (
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP, "",
                ("198.51.100.1", 0),
            ),
        ]
        opened: list[tuple[int, int, int]] = []

        def fake_socket(family, type_, proto):
            opened.append((family, type_, proto))
            m = MagicMock()
            if family == socket.AF_INET6:
                m.sendto.side_effect = OSError(101, "Network is unreachable")
            else:
                m.recvfrom.side_effect = socket.timeout
            return m

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            engine = ProbeEngine(method="icmp")
            result = engine.probe("dualstack.example.test")

        families = [fam for fam, _, _ in opened]
        assert socket.AF_INET6 in families
        assert socket.AF_INET in families, (
            f"expected IPv4 fallback after IPv6 sendto error; opened={opened}"
        )
        assert result.method == "icmp"

    def test_icmp_raw_fallback_returns_ipv4_success_after_ipv6_timeout(self):
        """When IPv6 times out with no reply, iterate to IPv4 and use its answer."""
        infos = [
            (
                socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6, "",
                ("2001:db8::1", 0, 0, 0),
            ),
            (
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP, "",
                ("198.51.100.1", 0),
            ),
        ]
        attempts: list[tuple[str, tuple]] = []

        def fake_v6(sockaddr):
            attempts.append(("v6", sockaddr))
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")

        def fake_v4(sockaddr):
            attempts.append(("v4", sockaddr))
            return ProbeResult(latency_ms=4.2, timeout=False, method="icmp")

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ):
            engine = ProbeEngine(method="icmp")
            with patch.object(engine, "_icmp_raw_v6", side_effect=fake_v6), \
                 patch.object(engine, "_icmp_raw_v4", side_effect=fake_v4):
                result = engine.probe("dualstack.example.test")

        assert [a[0] for a in attempts] == ["v6", "v4"], (
            f"must iterate v6 then v4; got {attempts}"
        )
        assert result.timeout is False
        assert result.method == "icmp"
        assert result.latency_ms == 4.2

    def test_icmp_raw_fallback_all_addresses_failing_returns_timeout(self):
        """Every address failing still produces a timeout ProbeResult (method=icmp)."""
        infos = [
            (
                socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6, "",
                ("2001:db8::1", 0, 0, 0),
            ),
            (
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP, "",
                ("198.51.100.1", 0),
            ),
        ]

        def fake_socket(*_args, **_kwargs):
            m = MagicMock()
            m.recvfrom.side_effect = socket.timeout
            return m

        with patch(
            "app.modules.connection_monitor.probe.os.path.isfile", return_value=False
        ), patch(
            "app.modules.connection_monitor.probe.socket.getaddrinfo",
            return_value=infos,
        ), patch(
            "app.modules.connection_monitor.probe.socket.socket",
            side_effect=fake_socket,
        ):
            engine = ProbeEngine(method="icmp")
            result = engine.probe("dualstack.example.test")

        assert result.timeout is True
        assert result.latency_ms is None
        assert result.method == "icmp"

    def test_icmp_helper_c_source_reserves_bounded_per_address_budget(self, tmp_path):
        """Helper must bound each address's wait so a silent first address does
        not starve later addresses of time.

        Compiles the helper and invokes a ``--plan <total_ms> <count>``
        diagnostic mode that simulates the main loop's budget allocation
        without needing raw-socket privileges. With N addresses and total T,
        every address must receive a non-zero budget strictly less than T,
        and the sum must not exceed T — otherwise a first address that sends
        but never replies can consume the whole window and the second address
        is never attempted.
        """
        helper_src = (
            Path(__file__).resolve().parents[3] / "tools" / "icmp_probe_helper.c"
        )
        binary = tmp_path / "icmp_probe_helper"
        compile_result = subprocess.run(
            ["gcc", "-O2", "-Wall", "-Werror", "-o", str(binary), str(helper_src)],
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr

        for total_ms, count in [(2000, 2), (3000, 3), (2000, 4)]:
            plan = subprocess.run(
                [str(binary), "--plan", str(total_ms), str(count)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert plan.returncode == 0, plan.stderr
            budgets = [int(x) for x in plan.stdout.split()]
            assert len(budgets) == count, (
                f"--plan {total_ms} {count} must emit {count} budgets; got {budgets}"
            )
            for i, budget in enumerate(budgets):
                assert budget > 0, (
                    f"address {i} of {count} got zero budget with total={total_ms}; "
                    f"a silent first address would starve later ones. budgets={budgets}"
                )
                assert budget < total_ms, (
                    f"address {i} budget must be strictly bounded below total; "
                    f"got {budget} with total={total_ms}. budgets={budgets}"
                )
            assert sum(budgets) <= total_ms, (
                f"sum of per-address budgets must not exceed total={total_ms}; "
                f"got sum={sum(budgets)} budgets={budgets}"
            )

    def test_icmp_helper_c_source_iterates_addrinfo_while_live(self):
        """Helper must probe each address before freeing the addrinfo list.

        Pre-fix, ``resolve_any`` picked the first usable entry, freed the
        list, and main sent exactly one packet to that address. After the
        fix, ``sendto`` must run while the addrinfo list is still live —
        i.e. at least one ``freeaddrinfo`` call appears AFTER ``sendto``
        in source order. That is the textual signature of a proper loop.
        """
        import re

        helper_src = (
            Path(__file__).resolve().parents[3] / "tools" / "icmp_probe_helper.c"
        )
        src = helper_src.read_text()

        getaddrinfo_calls = [m.start() for m in re.finditer(r"\bgetaddrinfo\s*\(", src)]
        freeaddrinfo_calls = [m.start() for m in re.finditer(r"\bfreeaddrinfo\s*\(", src)]
        sendto_calls = [m.start() for m in re.finditer(r"\bsendto\s*\(", src)]

        assert getaddrinfo_calls, "helper must still call getaddrinfo"
        assert sendto_calls, "helper must still call sendto"
        assert freeaddrinfo_calls, "helper must still call freeaddrinfo"

        earliest_sendto = min(sendto_calls)
        assert any(pos > earliest_sendto for pos in freeaddrinfo_calls), (
            "freeaddrinfo must run AFTER sendto in source order; otherwise the "
            "helper is picking one address, freeing the list, then probing — "
            "which cannot iterate across address families."
        )
