"""Make `import eval.*` and `import exemplar.*` work when pytest starts from anywhere; isolate the data dir per test."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh $EXEMPLAR_DATA_DIR (settings are cached, so clear them before and after)."""
    from exemplar.settings import get_settings
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
