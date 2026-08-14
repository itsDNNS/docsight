"""Deterministic Flask application construction for DOCSight."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

from . import web
from .base_path import configure_base_path
from .blueprints import register_blueprints
from .module_loader import ModuleLoader
from .runtime import (
    AuthStateStore,
    DocsightRuntime,
    LoginRateLimiter,
    UpdateChecker,
    attach_runtime,
)


LOG = logging.getLogger("docsis.web")
ModuleLoaderFactory = Callable[[Flask], Any | None]


def default_module_loader_factory(
    config_manager,
    *,
    builtin_base_path: str | None = None,
    search_paths: Sequence[str] | None = None,
) -> ModuleLoaderFactory:
    """Build a per-app module loader using this configuration's enabled set."""
    builtin_path = builtin_base_path or os.path.join(os.path.dirname(__file__), "modules")
    module_paths = list(search_paths or ())

    def build(app: Flask):
        disabled_raw = config_manager.get("disabled_modules", "")
        disabled_ids = {item.strip() for item in disabled_raw.split(",") if item.strip()}
        loader = ModuleLoader(
            app,
            builtin_base_path=builtin_path,
            search_paths=module_paths,
            disabled_ids=disabled_ids,
        )
        loader.load_all()
        return loader

    return build


def install_module_template_loader(app: Flask, module_loader) -> None:
    """Add enabled module template directories to this app's Jinja loader."""
    if module_loader is None:
        return
    loaders = [app.jinja_loader]
    for module in module_loader.get_enabled_modules():
        template_dir = os.path.join(module.path, "templates")
        if os.path.isdir(template_dir):
            loaders.append(FileSystemLoader(template_dir))
    if len(loaders) > 1:
        app.jinja_loader = ChoiceLoader(loaders)


def apply_reverse_proxy(app: Flask, environ: Mapping[str, str]) -> None:
    """Install trusted reverse-proxy handling as the outer WSGI layer."""
    reverse_proxy = environ.get("REVERSE_PROXY", "").strip()
    if not reverse_proxy:
        return
    num_proxies = int(reverse_proxy) if reverse_proxy.isdigit() else 1
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=num_proxies,
        x_proto=num_proxies,
        x_host=0,
        x_prefix=0,
    )
    app.config["SESSION_COOKIE_SECURE"] = True
    LOG.info(
        "Reverse proxy mode: trusting %d hop(s), secure cookies enabled",
        num_proxies,
    )


def create_app(
    *,
    config_manager,
    storage=None,
    on_config_changed: Callable[[], None] | None = None,
    module_loader_factory: ModuleLoaderFactory | None = None,
    environ: Mapping[str, str] | None = None,
    testing: bool = False,
) -> Flask:
    """Create one fully isolated DOCSight application in a fixed order.

    Construction configures Flask, attaches runtime state, initializes auth,
    registers core and blueprint routes, loads modules and templates, then
    installs base-path and reverse-proxy middleware.
    """
    if config_manager is None:
        raise TypeError("config_manager is required")
    env = os.environ if environ is None else environ

    app = Flask("app.web", template_folder="templates")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=web._session_lifetime_days(env)),
        SESSION_REFRESH_EACH_REQUEST=True,
        TESTING=testing,
    )

    auth_state = AuthStateStore(config_manager.data_dir)
    app.secret_key = auth_state.load_or_create_session_key()
    enabled_check = getattr(config_manager, "is_update_check_enabled", None)
    runtime = DocsightRuntime(
        config_manager=config_manager,
        storage=storage,
        on_config_changed=on_config_changed,
        auth_state=auth_state,
        login_rate_limiter=LoginRateLimiter(
            max_attempts=web._LOGIN_MAX_ATTEMPTS,
            window=web._LOGIN_WINDOW,
            lockout_base=web._LOGIN_LOCKOUT_BASE,
            max_tracked_ips=web._LOGIN_MAX_TRACKED_IPS,
        ),
        update_checker=UpdateChecker(
            app_version=web.APP_VERSION,
            is_enabled=enabled_check if callable(enabled_check) else lambda: False,
            ttl=web._UPDATE_CACHE_TTL,
        ),
    )
    attach_runtime(app, runtime)
    web.bootstrap_auth_state(app, runtime)
    web.register_core_routes(app)
    register_blueprints(app)

    loader = module_loader_factory(app) if module_loader_factory else None
    runtime.module_loader = loader
    install_module_template_loader(app, loader)
    configure_base_path(app, env)
    apply_reverse_proxy(app, env)
    return app
