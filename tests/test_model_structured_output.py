"""Phase 0 acceptance: structured-output round trip with Ollama.

This test requires a running Ollama server with the configured model pulled.
It is marked with pytest.mark.integration so it can be skipped in CI.
"""

import pytest

from pisa.config import load_config
from pisa.model.ollama import OllamaProvider


ECHO_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["message", "count"],
}


@pytest.mark.integration
def test_structured_output_round_trip():
    """Model returns schema-valid JSON for a simple prompt."""
    config = load_config()
    provider = OllamaProvider(config.model)

    status = provider.health_check()
    if not status.available:
        pytest.skip(f"Ollama not available: {status.message}")

    result = provider.analyze(
        prompt=(
            "Respond with a JSON object containing a 'message' field with the text "
            "'hello from pisa' and a 'count' field with the integer 42."
        ),
        response_schema=ECHO_SCHEMA,
        max_tokens=256,
    )

    assert result["message"] == "hello from pisa"
    assert result["count"] == 42
