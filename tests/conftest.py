"""Shared test fixtures and setup for DOCSight tests."""

from app.web import app


def _register_module_blueprints():
    """Register module blueprints with the Flask app for testing.

    Module blueprints are normally registered by the module loader at runtime.
    In tests, we register them early so they're available before first request.
    """
    blueprints_to_register = []

    try:
        from app.modules.speedtest.routes import bp as speedtest_bp
        blueprints_to_register.append(("speedtest_module", speedtest_bp))
    except ImportError:
        pass

    try:
        from app.modules.bqm.routes import bp as bqm_bp
        blueprints_to_register.append(("bqm_module", bqm_bp))
    except ImportError:
        pass

    try:
        from app.modules.bnetz.routes import bp as bnetz_bp
        blueprints_to_register.append(("bnetz_module", bnetz_bp))
    except ImportError:
        pass

    existing = {b.name for b in app.blueprints.values()}
    for name, bp in blueprints_to_register:
        if name not in existing:
            app.register_blueprint(bp)


_register_module_blueprints()
