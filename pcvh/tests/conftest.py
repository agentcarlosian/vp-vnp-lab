"""Keep integration-test writes out of the checked-in blueprint evidence."""
from pathlib import Path
import shutil

import pytest

_BLUEPRINTS = Path(__file__).resolve().parents[1] / "blueprints"


@pytest.fixture
def copy_blueprint(tmp_path):
    def copy(name):
        source = _BLUEPRINTS / name
        return shutil.copytree(
            source,
            tmp_path / source.name,
            ignore=shutil.ignore_patterns(".lake", ".pcvh", "__pycache__", "target", "node_modules"),
        )

    return copy
