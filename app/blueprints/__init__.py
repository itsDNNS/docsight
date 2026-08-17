"""Stable providers for DOCSight's core Flask blueprints."""


def core_blueprints():
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

    return (
        config_bp,
        polling_bp,
        data_bp,
        analysis_bp,
        events_bp,
        modules_bp,
        metrics_bp,
        notices_bp,
        segment_bp,
        smart_capture_bp,
    )
