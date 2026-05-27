"""Tests for models.dev-based reasoning-effort capability detection (spec v2).

Covers:
  - _models_dev_reasoning_efforts returns full set when supports_reasoning=True
  - _models_dev_reasoning_efforts returns [] when supports_reasoning=False
  - _models_dev_reasoning_efforts returns None on import failure / unknown model
  - Explicit metadata False suppresses broad heuristic fallback
  - Custom providers get full efforts when models.dev returns None
  - get_reasoning_status() reads default model/provider from config when
    called without explicit model/provider and uses models.dev metadata
  - Copilot/GitHub and Codex exact resolvers still work
"""

import sys
import types
from types import SimpleNamespace

import pytest


def _inject_fake_agent_models_dev(monkeypatch, fake_fn):
    """Inject a fake agent.models_dev.get_model_capabilities into sys.modules."""
    fake_agent = types.ModuleType("agent")
    fake_models_dev = types.ModuleType("agent.models_dev")
    fake_models_dev.get_model_capabilities = fake_fn
    fake_agent.models_dev = fake_models_dev
    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "agent.models_dev", fake_models_dev)
    return fake_models_dev


def _remove_fake_agent_models_dev(monkeypatch):
    """Remove any injected fake agent.models_dev from sys.modules."""
    monkeypatch.delitem(sys.modules, "agent", raising=False)
    monkeypatch.delitem(sys.modules, "agent.models_dev", raising=False)


# ── _models_dev_reasoning_efforts unit tests ─────────────────────────────────

class TestModelsDevReasoningEfforts:
    """Test the _models_dev_reasoning_efforts helper directly."""

    def test_returns_full_efforts_when_supports_reasoning_true(self, monkeypatch):
        """When fake metadata says supports_reasoning=True, return full set."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=True),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg._models_dev_reasoning_efforts("gemini-2.5-flash", "gemini")
            assert result == list(cfg.VALID_REASONING_EFFORTS)
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_returns_empty_when_supports_reasoning_false(self, monkeypatch):
        """When fake metadata says supports_reasoning=False, return []."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=False),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg._models_dev_reasoning_efforts("gemini-2.5-flash", "gemini")
            assert result == []
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_returns_none_on_import_failure(self, monkeypatch):
        """When agent.models_dev is not importable, return None."""
        _remove_fake_agent_models_dev(monkeypatch)
        import api.config as cfg
        result = cfg._models_dev_reasoning_efforts("gemini-2.5-flash", "gemini")
        assert result is None

    def test_returns_none_when_capabilities_none(self, monkeypatch):
        """When get_model_capabilities returns None, return None."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: None,
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg._models_dev_reasoning_efforts("unknown-model", "unknown")
            assert result is None
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_returns_none_on_call_exception(self, monkeypatch):
        """When get_model_capabilities raises, return None."""

        def _boom(provider, model):
            raise RuntimeError("cache miss")

        _inject_fake_agent_models_dev(monkeypatch, _boom)
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg._models_dev_reasoning_efforts("gemini-2.5-flash", "gemini")
            assert result is None
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_returns_empty_when_supports_reasoning_attr_missing(self, monkeypatch):
        """When the capability object lacks supports_reasoning, treat as False."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(context_window=128000),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg._models_dev_reasoning_efforts("some-model", "some-provider")
            assert result == []
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)


# ── resolve_model_reasoning_efforts integration tests ─────────────────────────

class TestResolveModelReasoningEffortsModelsDev:
    """Test the full resolver order with models.dev injection."""

    def test_models_dev_true_returns_full_efforts(self, monkeypatch):
        """Step 4: models.dev says True → full efforts without hitting heuristics."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=True),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "gemini-2.5-flash", provider_id="gemini"
            )
            assert result == list(cfg.VALID_REASONING_EFFORTS)
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_models_dev_false_suppresses_heuristic_fallback(self, monkeypatch):
        """Step 4: explicit metadata False prevents broad heuristic overrides.

        Even though heuristics would match gemini-2 prefix, the models.dev
        authoritative False must win and return [].
        """
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=False),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "gemini-2.5-flash", provider_id="gemini"
            )
            assert result == []
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_custom_provider_gets_full_efforts_when_models_dev_none(self, monkeypatch):
        """Step 5: custom: provider with no models.dev metadata → full efforts."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: None,
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "my-model", provider_id="custom:local-llm"
            )
            assert result == list(cfg.VALID_REASONING_EFFORTS)
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_kimi_compatibility_fallback_when_models_dev_none(self, monkeypatch):
        """Kimi/Moonshot proxy slugs can be absent from models.dev; preserve fallback."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: None,
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "moonshotai/kimi-k2-thinking", provider_id="kimi-coding"
            )
            assert result == ["low", "medium", "high"]
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_heuristic_fallback_when_models_dev_unavailable(self, monkeypatch):
        """Step 6: heuristics kick in when models.dev returns None."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: None,
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "openai/gpt-5.4-mini", provider_id="openrouter"
            )
            assert result == list(cfg.VALID_REASONING_EFFORTS)
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_openai_codex_gpt55_uses_agent_metadata_full_efforts(self, monkeypatch):
        """OpenAI Codex GPT-5.5 should not be capped by GitHub/Copilot helper.

        The GitHub/Copilot catalog helper currently caps GPT-5-family models at
        high. OpenAI Codex uses the Codex Responses transport, so when Hermes
        Agent metadata says the model supports reasoning, WebUI should expose
        the full effort set including xhigh.
        """
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=True),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "gpt-5.5", provider_id="openai-codex"
            )
            assert result == list(cfg.VALID_REASONING_EFFORTS)
            assert "xhigh" in result
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_copilot_acp_always_returns_empty(self, monkeypatch):
        """Step 2: copilot-acp is explicitly unsupported regardless of metadata."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=True),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            result = cfg.resolve_model_reasoning_efforts(
                "copilot-agent", provider_id="copilot-acp"
            )
            assert result == []
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)


# ── get_reasoning_status integration test ──────────────────────────────────────

class TestGetReasoningStatusModelsDev:
    """Test that get_reasoning_status uses models.dev when no model is given."""

    def test_uses_config_default_model_with_models_dev(self, tmp_path, monkeypatch):
        """Step 7 / boot-time fix: when called without model/provider,
        get_reasoning_status reads config defaults and applies models.dev."""
        _inject_fake_agent_models_dev(
            monkeypatch,
            lambda provider, model: SimpleNamespace(supports_reasoning=True),
        )
        import importlib
        import api.config as cfg
        importlib.reload(cfg)
        try:
            config_path = tmp_path / "config.yaml"
            monkeypatch.setattr(cfg, "_get_config_path", lambda: config_path)
            import yaml as _yaml
            config_path.write_text(
                _yaml.dump({
                    "model": {
                        "default": "gemini-2.5-flash",
                        "provider": "gemini",
                    },
                }),
                encoding="utf-8",
            )
            cfg.reload_config()
            status = cfg.get_reasoning_status()
            assert status["supported_efforts"] == list(cfg.VALID_REASONING_EFFORTS)
            assert status["supports_reasoning_effort"] is True
        finally:
            _remove_fake_agent_models_dev(monkeypatch)
            importlib.reload(cfg)

    def test_empty_model_returns_empty_efforts(self, monkeypatch):
        """resolve_model_reasoning_efforts([]) returns [] regardless."""
        import api.config as cfg
        result = cfg.resolve_model_reasoning_efforts("")
        assert result == []