from __future__ import annotations

import pytest

from connector.common.interactive_io import InteractiveIoGate
from connector.infra.secrets.prompt_provider import PromptSecretProvider

pytestmark = pytest.mark.unit


def test_prompt_secret_provider_activates_interactive_gate() -> None:
    interactive_io_gate = InteractiveIoGate()

    def _prompt(_message: str) -> str:
        assert interactive_io_gate.is_active() is True
        return "secret-value"

    provider = PromptSecretProvider(
        prompt_secret=_prompt,
        interactive_io_gate=interactive_io_gate,
    )

    value = provider.get_secret(dataset="employees", field="password", row_id="row-1")

    assert value == "secret-value"
