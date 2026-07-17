from __future__ import annotations

import json
from pathlib import Path

from app.config import load_config
from app.provider_model_catalog import ProviderModelCatalog, _model_ids_from_payload


def _config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("VP_OPENAI_COMPAT_API_KEY", "not-persisted-key")
    monkeypatch.setenv("VP_OPENAI_COMPAT_BASE_URL", "https://gateway.example.test/v1")
    return load_config()


def test_model_payload_parser_accepts_common_openai_compatible_shapes() -> None:
    assert _model_ids_from_payload({"data": [{"id": "gpt-a"}, {"id": "gpt-b"}]}) == ["gpt-a", "gpt-b"]
    assert _model_ids_from_payload({"models": [{"name": "model-a"}, "model-b"]}) == ["model-a", "model-b"]
    assert _model_ids_from_payload([{"model": "one"}, {"model": "one"}, {"model": "two"}]) == ["one", "two"]


def test_manual_refresh_replaces_and_persists_models_without_provider_secrets(monkeypatch, tmp_path: Path) -> None:
    config = _config(monkeypatch, tmp_path)
    cache_path = tmp_path / "provider_models.json"
    calls = {"count": 0}

    def fetcher(received_config):
        calls["count"] += 1
        assert received_config is config
        return ["company-gpt-5.4", "company-gpt-5.4-mini", "company-gpt-5.4"]

    catalog = ProviderModelCatalog(cache_path, fetcher=fetcher)
    assert catalog.models_for("openai_compatible") == []

    refreshed = catalog.refresh("openai_compatible", config)

    assert calls["count"] == 1
    assert refreshed["models"] == ["company-gpt-5.4", "company-gpt-5.4-mini"]
    assert ProviderModelCatalog(cache_path).models_for("openai_compatible") == refreshed["models"]
    stored = cache_path.read_text(encoding="utf-8")
    assert "not-persisted-key" not in stored
    assert "gateway.example.test" not in stored
    assert json.loads(stored)["providers"]["openai_compatible"]["models"] == refreshed["models"]
