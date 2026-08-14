import gc

from app.app_factory import create_app, default_module_loader_factory
from app.config import ConfigManager


def test_repeated_full_creation_has_identical_unique_routes(tmp_path):
    snapshots = []
    blueprint_sets = []
    for index in range(3):
        manager = ConfigManager(str(tmp_path / f"data-{index}"))
        app = create_app(
            config_manager=manager,
            module_loader_factory=default_module_loader_factory(manager, search_paths=[]),
            environ={},
            testing=True,
        )
        snapshot = sorted(
            (rule.endpoint, rule.rule, tuple(sorted(rule.methods)))
            for rule in app.url_map.iter_rules()
        )
        snapshots.append(snapshot)
        pairs = [(rule.endpoint, rule.rule) for rule in app.url_map.iter_rules()]
        assert len(pairs) == len(set(pairs))
        assert sorted(
            rule.rule for rule in app.url_map.iter_rules()
            if rule.endpoint == "polling_bp.api_test_modem"
        ) == ["/api/test-fritz", "/api/test-modem"]
        blueprint_sets.append(set(app.blueprints))
        del app
        gc.collect()
    assert snapshots[0] == snapshots[1] == snapshots[2]
    assert blueprint_sets[0] == blueprint_sets[1] == blueprint_sets[2]
