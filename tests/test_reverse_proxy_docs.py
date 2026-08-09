"""Static contracts for public reverse-proxy deployment boundaries."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "reverse-proxy.md"


def test_path_prefix_guide_is_tracked_and_discoverable():
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert GUIDE.exists()
    assert "[path-prefix reverse-proxy guide](docs/reverse-proxy.md)" in install
    assert "!docs/reverse-proxy.md" in gitignore


def test_environment_example_separates_proxy_trust_contracts():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    proxy_block = example.split("# REVERSE_PROXY=1", 1)[1].split(
        "# LANGUAGE=", 1
    )[0]

    assert "# BASE_PATH=/docsight" in proxy_block
    assert "# REVERSE_PROXY_PREFIX=1" in proxy_block
    assert "client/proto" in example
    assert "separate from client/proto trust" in example


def test_security_policy_records_fail_closed_prefix_boundary():
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    section = security.split("### Reverse-Proxy Path Prefixes", 1)[1].split(
        "### Login Rate Limiting", 1
    )[0]

    for phrase in [
        "Explicit mode",
        "Trusted-prefix mode",
        "exact number of",
        "trusted `X-Forwarded-Prefix` hops",
        "all selected sources must agree",
        "strip any client-supplied",
        "replace the header",
        "generic, unreflected bad request",
        "same-origin mount",
        "Home Assistant may authenticate access to its Ingress",
    ]:
        assert phrase in section


def test_architecture_keeps_platform_wrapper_outside_core():
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    section = architecture.split(
        "### Reverse-proxy mount contract and wrapper boundary", 1
    )[1].split("## System Architecture", 1)[0]

    for phrase in [
        "generic proxy-stripped mount contract",
        "DOCSight Core does not call the",
        "Supervisor API",
        "consume Home Assistant",
        "A Home Assistant wrapper may query",
        "set an explicit `BASE_PATH` before starting",
    ]:
        assert phrase in section


def test_operator_guide_covers_proxy_and_healthcheck_modes():
    guide = GUIDE.read_text(encoding="utf-8")

    for phrase in [
        "BASE_PATH=/docsight",
        "REVERSE_PROXY_PREFIX=1",
        'proxy_set_header X-Forwarded-Prefix ""',
        "proxy_set_header X-Forwarded-Prefix /docsight",
        "replaces, rather than appends to",
        "same origin",
        "within that",
        "http://localhost:${WEB_PORT:-8765}/health",
        "fixed valid synthetic prefix chain",
        "explicit root",
        "does not inherit Home Assistant identity or session state",
    ]:
        assert phrase in guide


def test_runtime_order_and_browser_service_worker_exclusions_remain_explicit():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    login = (ROOT / "app" / "templates" / "login.html").read_text(
        encoding="utf-8"
    )
    setup = (ROOT / "app" / "templates" / "setup.html").read_text(
        encoding="utf-8"
    )

    assert main.index("configure_base_path(web.app)") < main.index(
        "web.app.wsgi_app = ProxyFix("
    )
    assert "x_prefix=0" in main
    assert "serviceWorker.register" not in login
    assert "serviceWorker.register" not in setup
