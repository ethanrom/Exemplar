from __future__ import annotations

import json

import pytest

from exemplar.perception.cli import main, parse_roi
from perception_helpers import FakeBedrock, auto_response, text_response


def test_parse_roi():
    assert parse_roi("0,340,480,270") == (0, 340, 480, 270)
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        parse_roi("1,2,3")


def test_cli_prints_compact_summary_and_writes_json(video, tmp_path, capsys):
    out = tmp_path / "t.json"
    fake = FakeBedrock(auto_response)
    rc = main([str(video), "--n", "6", "--clip-id", "demo", "--start", "2", "--dur", "6", "--json", str(out)], client=fake)
    text = capsys.readouterr().out
    assert rc == 0
    assert "clip=demo status=ok mode=fast frames=6 window=6.0s cached=False" in text
    assert "entities: p1:person[hoodie] | k1:package[cardboard_box]" in text
    assert "picks_up(p1,k1)" in text and "summary: A person takes a box" in text
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["trace"]["clip_id"] == "demo" and doc["report"]["attempts"] == 1
    # second run is served from the cache
    assert main([str(video), "--n", "6", "--clip-id", "demo", "--start", "2", "--dur", "6"], client=fake) == 0
    assert "cached=True" in capsys.readouterr().out and len(fake.calls) == 1


def test_cli_failure_exit_code(video, capsys):
    rc = main([str(video), "--strong"], client=FakeBedrock(text_response()))
    assert rc == 2 and "ERROR" in capsys.readouterr().out
