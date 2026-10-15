"""Shared fixtures for the perception tests.  Everything here runs offline: Bedrock is a scripted fake and the
ffmpeg clips are synthesised on the fly.  Live tests (real Bedrock + real clips) are opt-in: EXEMPLAR_LIVE=1."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

from exemplar import settings


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls real Bedrock / uses real clips; run with EXEMPLAR_LIVE=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("EXEMPLAR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set EXEMPLAR_LIVE=1 to run (spends Bedrock budget)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def video(tmp_path_factory) -> Path:
    """10 s, 320x240, 10 fps; the red channel ramps 0 -> 255 over the clip so frame time is recoverable."""
    out = tmp_path_factory.mktemp("clips") / "ramp.mp4"
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                        "color=c=black:s=320x240:r=10:d=10", "-vf",
                        "format=gbrp,geq=r='255*T/10':g='0':b='0',format=yuv420p", "-y", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


@pytest.fixture(autouse=True)
def isolated_settings(request, tmp_path, monkeypatch):
    """Offline tests never read the real .env or touch the real data dir, and use fake model ids.
    Live tests keep the real .env (EXEMPLAR_DOTENV) but still write their cache into tmp_path."""
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path / "data"))
    if not request.node.get_closest_marker("live"):
        monkeypatch.setenv("EXEMPLAR_DOTENV", str(tmp_path / "no.env"))
        monkeypatch.setenv("CLAUDE_AWS_FAST_MODEL", "fake-fast-model")
        monkeypatch.setenv("CLAUDE_AWS_MODEL", "fake-strong-model")
        monkeypatch.setenv("CLAUDE_AWS_MODEL_ALIAS", "test-alias")
    settings.get_settings.cache_clear()
    yield tmp_path / "data"
    settings.get_settings.cache_clear()
