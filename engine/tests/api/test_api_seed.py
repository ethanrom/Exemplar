"""Seed CLI: missing inputs fail with one readable line and a non-zero exit, not a traceback."""
from __future__ import annotations

from exemplar.api import seed


def test_missing_frollard_clip_is_a_one_line_error(capsys, tmp_path):
    rc = seed.main(["--frollard", "--no-perceive", "--media-dir", str(tmp_path / "media")])
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 2 and len(err) == 1
    assert err[0].startswith("seed: ") and "frollard_thief.mp4" in err[0] and "--no-perceive skips Bedrock" in err[0]
    assert "Traceback" not in err[0] and str(tmp_path / "media" / "external") in err[0]


def test_missing_input_is_checked_before_anything_is_imported(capsys, tmp_path):
    """--playground-spike is listed first, but the missing frollard clip must stop the run before it imports anything."""
    spike = tmp_path / "spike"
    spike.mkdir()
    (spike / "evt").mkdir()
    (spike / "evt" / "event.json").write_text('{"id": "e1", "start": 1}', encoding="utf-8")
    (spike / "evt" / "clip.mp4").write_bytes(b"x")
    rc = seed.main(["--playground-spike", "--frollard", "--no-perceive", "--spike-dir", str(spike),
                    "--media-dir", str(tmp_path)])
    assert rc == 2 and "frollard clip not found" in capsys.readouterr().err
    from exemplar.api.state import AppState
    from exemplar.settings import get_settings
    st = AppState(settings=get_settings())
    try:
        assert st.store.events.count() == 0
    finally:
        st.shutdown()


def test_missing_playground_recording_is_a_one_line_error(capsys, tmp_path):
    rc = seed.main(["--playground-spike", "--no-perceive", "--media-dir", str(tmp_path)])
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 2 and len(err) == 1 and "Playground recording not found" in err[0]
