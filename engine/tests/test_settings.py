from exemplar import settings


def test_settings_from_env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("CLAUDE_AWS_REGION=test-region-1\nCLAUDE_AWS_MODEL_ALIAS=strong-alias\n", encoding="utf-8")
    (tmp_path / "token").write_text("tok123\n", encoding="utf-8")
    for k in ("CLAUDE_AWS_REGION", "CLAUDE_AWS_MODEL_ALIAS", "RING_PLAYGROUND_TOKEN", "RING_TOKEN_FILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EXEMPLAR_DOTENV", str(env))
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path / "data"))
    settings.get_settings.cache_clear()
    s = settings.get_settings()
    assert s.aws_region == "test-region-1" and s.model_alias == "strong-alias"
    assert s.ring_token == "tok123"
    assert s.data_dir == tmp_path / "data" and s.db_path.parent == tmp_path / "data" and s.engine_port == 8787
    settings.get_settings.cache_clear()
