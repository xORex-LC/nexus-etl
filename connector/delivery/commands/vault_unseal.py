"""
Назначение:
    Delivery helper для runtime unseal prompt.

Граница ответственности:
    - Запрашивает passphrase у оператора.
    - Прокидывает её в composition root перед init `vault_ready`.
    - Не выполняет проверку passphrase и не знает о KDF/HMAC.
"""

from __future__ import annotations

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.interaction import prompt_secret_with_gate


def provide_runtime_unseal_passphrase(ctx: BoundCommandContext) -> None:
    passphrase = prompt_secret_with_gate(
        "Введите unseal passphrase",
        gate=ctx.container.observability.interactive_io_gate(),
    )
    ctx.container.vault_unseal_passphrase.override(passphrase)


__all__ = ["provide_runtime_unseal_passphrase"]
