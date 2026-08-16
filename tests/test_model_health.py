"""Phase 0 acceptance: model health check returns a valid status."""

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider
from pisa.model.provider import ProviderStatus


def test_health_check_returns_provider_status():
    config = load_config()
    provider = OllamaProvider(config.model)
    status = provider.health_check()
    assert isinstance(status, ProviderStatus)
    assert isinstance(status.available, bool)
    assert isinstance(status.message, str)
    assert status.model_name == config.model.model


def test_health_check_reports_server_down_gracefully(monkeypatch):
    """If Ollama is not running, health_check should not raise."""
    from pisa.config import ModelConfig

    bad_config = ModelConfig(base_url="http://localhost:99999")
    provider = OllamaProvider(bad_config)
    status = provider.health_check()
    assert not status.available
    assert not status.server_reachable
    assert "Cannot reach" in status.message
