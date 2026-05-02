"""Flask Blueprint registration."""


def register_blueprints(app):
    from .config_bp import config_bp
    from .polling_bp import polling_bp
    from .data_bp import data_bp
    from .analysis_bp import analysis_bp
    from .events_bp import events_bp
    from .modules_bp import modules_bp
    from .metrics_bp import metrics_bp
    from .notices_bp import notices_bp
    from .segment_bp import segment_bp
    from .smart_capture_bp import smart_capture_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(polling_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(notices_bp)
    app.register_blueprint(segment_bp)
    app.register_blueprint(smart_capture_bp)
