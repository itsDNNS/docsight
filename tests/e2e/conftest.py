"""Declarative E2E fixture and server-profile wiring."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from tests.e2e.prefix_proxy import serve_prefix_proxy
from tests.e2e.support.application import (
    seed_fritzbox_segment_data,
    serve_server,
)
from tests.e2e.support.lifecycle import (
    ProcessSpec,
    artifact_log_path,
    reserve_local_port,
    running_processes,
)
from tests.e2e.support.profiles import ServerProfile, ServerTarget

DEMO_PROFILE = ServerProfile("demo", configured=True, demo_mode=True)
AUTH_PROFILE = ServerProfile("auth", configured=True, demo_mode=True)
CONFIGURED_PROFILE = ServerProfile(
    "configured", configured=True, demo_mode=False
)
SETUP_PROFILE = ServerProfile("setup", configured=False, demo_mode=False)
FIRST_RUN_PROFILE = ServerProfile(
    "first-run-production-startup",
    configured=False,
    demo_mode=False,
    production_startup=True,
)
FRITZBOX_PROFILE = ServerProfile(
    "fritzbox",
    configured=True,
    demo_mode=True,
    modem_type="fritzbox",
    post_seed_callback=seed_fritzbox_segment_data,
)
AUTH_TEST_CREDENTIAL = "e2e-test-password"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """WSL2-friendly Chromium launch arguments to prevent flakiness."""

    return {
        **browser_type_launch_args,
        "args": [
            *(browser_type_launch_args.get("args", [])),
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-sandbox",
        ],
    }


def _new_target(
    label,
    data_dir,
    profile,
    *,
    admin_password=None,
    readiness_headers=(),
):
    reservation = reserve_local_port()
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    identity = f"{label}-{worker}-{reservation.port}"
    target = ServerTarget(
        identity=identity,
        data_dir=str(data_dir),
        port=reservation.port,
        profile=profile,
        admin_password=admin_password,
    )
    spec = ProcessSpec(
        identity=identity,
        reservation=reservation,
        process_target=serve_server,
        args=(target,),
        readiness_path=profile.mount_path,
        readiness_headers=readiness_headers,
        log_path=artifact_log_path(identity),
        secrets=(admin_password,) if admin_password else (),
        data_path=target.data_dir,
    )
    return target, spec


def _new_proxy(label, upstream_port, mount_path, forwarded_prefix_chain):
    reservation = reserve_local_port()
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    identity = f"{label}-{worker}-{reservation.port}"
    spec = ProcessSpec(
        identity=identity,
        reservation=reservation,
        process_target=serve_prefix_proxy,
        args=(
            reservation.port,
            upstream_port,
            mount_path,
            forwarded_prefix_chain,
        ),
        readiness_path=mount_path,
        log_path=artifact_log_path(identity),
    )
    return reservation.port, spec


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    target, spec = _new_target(
        "demo", tmp_path_factory.mktemp("docsight_e2e_demo"), DEMO_PROFILE
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture(scope="session")
def auth_server(tmp_path_factory):
    target, spec = _new_target(
        "auth",
        tmp_path_factory.mktemp("docsight_e2e_auth"),
        AUTH_PROFILE,
        admin_password=AUTH_TEST_CREDENTIAL,
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture(scope="session")
def configured_server(tmp_path_factory):
    target, spec = _new_target(
        "configured",
        tmp_path_factory.mktemp("docsight_e2e_configured"),
        CONFIGURED_PROFILE,
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture()
def first_run_server(tmp_path):
    target, spec = _new_target(
        "first-run", tmp_path / "first-run", FIRST_RUN_PROFILE
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture(scope="session")
def setup_server(tmp_path_factory):
    target, spec = _new_target(
        "setup", tmp_path_factory.mktemp("docsight_e2e_setup"), SETUP_PROFILE
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture()
def isolated_setup_server(tmp_path):
    target, spec = _new_target(
        "isolated-setup", tmp_path / "isolated-setup", SETUP_PROFILE
    )
    with running_processes([spec]):
        yield {"url": target.base_url, "data_dir": target.data_dir}


@pytest.fixture(scope="session")
def fritzbox_server(tmp_path_factory):
    target, spec = _new_target(
        "fritzbox",
        tmp_path_factory.mktemp("docsight_e2e_fritzbox"),
        FRITZBOX_PROFILE,
    )
    with running_processes([spec]):
        yield target.base_url


@pytest.fixture()
def demo_page(page, live_server):
    page.goto(live_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def settings_page(page, live_server):
    page.goto(f"{live_server}/settings")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def configured_page(page, configured_server):
    page.goto(configured_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def auth_page(page, auth_server):
    return page


@pytest.fixture()
def setup_page(page, setup_server):
    page.goto(setup_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture()
def fritzbox_page(page, fritzbox_server):
    page.goto(fritzbox_server)
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture(
    scope="session",
    params=["", "/docsight"],
    ids=["root-mount", "docsight-mount"],
)
def path_prefix_servers(request, tmp_path_factory):
    """Serve auth and setup apps through real root/prefix WSGI mounts."""

    mount_path = request.param
    label = "root" if not mount_path else "docsight"
    credential = "browser-contract-password"
    auth_profile = ServerProfile(
        f"path-prefix-auth-{label}",
        configured=True,
        demo_mode=True,
        mount_path=mount_path,
    )
    setup_profile = ServerProfile(
        f"path-prefix-setup-{label}",
        configured=False,
        demo_mode=False,
        mount_path=mount_path,
    )
    auth_target, auth_spec = _new_target(
        f"mount-auth-{label}",
        tmp_path_factory.mktemp(f"docsight_mount_auth_{label}"),
        auth_profile,
        admin_password=credential,
    )
    setup_target, setup_spec = _new_target(
        f"mount-setup-{label}",
        tmp_path_factory.mktemp(f"docsight_mount_setup_{label}"),
        setup_profile,
    )
    with running_processes([auth_spec, setup_spec]):
        yield {
            "mount_path": mount_path,
            "app_url": auth_target.base_url,
            "setup_url": setup_target.base_url,
            "password": credential,
        }


@dataclass(frozen=True)
class NetworkPrefixCase:
    label: str
    mount_path: str
    base_path: str | None
    trusted_prefix_hops: int | None
    forwarded_prefix_chain: str | None


_NETWORK_PREFIX_CASES = [
    pytest.param(
        NetworkPrefixCase(
            "explicit-docsight",
            "/docsight",
            "/docsight",
            None,
            None,
        ),
        id="explicit-docsight-mount",
    ),
    pytest.param(
        NetworkPrefixCase(
            "trusted-docsight",
            "/docsight",
            None,
            2,
            "/docsight, /docsight",
        ),
        id="trusted-docsight-mount",
    ),
    pytest.param(
        NetworkPrefixCase(
            "explicit-wrapper-shape",
            "/api/hassio_ingress/synthetic-test-entry",
            "/api/hassio_ingress/synthetic-test-entry",
            None,
            None,
        ),
        id="explicit-wrapper-shaped-mount",
    ),
]


class _RedactedProxyServers(dict):
    def __repr__(self) -> str:
        return "<real proxy server contract>"


@pytest.fixture(scope="session", params=_NETWORK_PREFIX_CASES)
def real_proxy_servers(request, tmp_path_factory):
    """Run DOCSight behind separate prefix-stripping HTTP proxy processes."""

    case = request.param
    credential = "network-proxy-test-password"
    auth_profile = ServerProfile(
        f"network-proxy-auth-{case.label}",
        configured=True,
        demo_mode=True,
        base_path=case.base_path,
        trusted_prefix_hops=case.trusted_prefix_hops,
    )
    setup_profile = ServerProfile(
        f"network-proxy-setup-{case.label}",
        configured=False,
        demo_mode=False,
        base_path=case.base_path,
        trusted_prefix_hops=case.trusted_prefix_hops,
    )
    auth_target, auth_spec = _new_target(
        f"proxy-upstream-auth-{case.label}",
        tmp_path_factory.mktemp(f"network_proxy_auth_{case.label}"),
        auth_profile,
        admin_password=credential,
        readiness_headers=(
            (("X-Forwarded-Prefix", case.forwarded_prefix_chain),)
            if case.forwarded_prefix_chain
            else ()
        ),
    )
    setup_target, setup_spec = _new_target(
        f"proxy-upstream-setup-{case.label}",
        tmp_path_factory.mktemp(f"network_proxy_setup_{case.label}"),
        setup_profile,
        readiness_headers=(
            (("X-Forwarded-Prefix", case.forwarded_prefix_chain),)
            if case.forwarded_prefix_chain
            else ()
        ),
    )
    auth_proxy_port, auth_proxy_spec = _new_proxy(
        f"proxy-auth-{case.label}",
        auth_target.port,
        case.mount_path,
        case.forwarded_prefix_chain,
    )
    setup_proxy_port, setup_proxy_spec = _new_proxy(
        f"proxy-setup-{case.label}",
        setup_target.port,
        case.mount_path,
        case.forwarded_prefix_chain,
    )
    with running_processes(
        [auth_spec, setup_spec, auth_proxy_spec, setup_proxy_spec]
    ):
        yield _RedactedProxyServers(
            {
                "mount_path": case.mount_path,
                "app_url": (
                    f"http://127.0.0.1:{auth_proxy_port}{case.mount_path}"
                ),
                "setup_url": (
                    f"http://127.0.0.1:{setup_proxy_port}{case.mount_path}"
                ),
                "password": credential,
            }
        )
