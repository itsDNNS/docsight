"""Flask Blueprint registration."""


def register_blueprints(app):
    from .config_bp import config_bp
    from .polling_bp import polling_bp
    from .data_bp import data_bp
    from .analysis_bp import analysis_bp
    from .journal_bp import journal_bp
    from .integrations_bp import integrations_bp
    from .events_bp import events_bp
    from .reports_bp import reports_bp
    from .modules_bp import modules_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(polling_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(journal_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(modules_bp)
