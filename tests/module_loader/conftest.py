import json

import pytest
from flask import Flask

from app.module_loader import ModuleLoader


@pytest.fixture
def load_with_regular_module(tmp_path):
    """Add a plain integration module to tmp_path, then load every module there."""
    def load():
        mod_dir = tmp_path / "regular"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.regular", "name": "R", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {},
        }))
        loader = ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)])
        loader.load_all()
        return loader
    return load
