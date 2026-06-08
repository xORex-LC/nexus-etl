"""
Назначение:
    Delivery boundary для user-facing CLI команд `vault-management`.

Граница ответственности:
    - Принимает CLI-опции, выполняет confirm/admin-gate/unseal prompts.
    - Передаёт passphrase в usecase как runtime input.
    - Не реализует KDF/HMAC, rewrap алгоритмы и storage IO напрямую.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import structlog
import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.interaction import (
    confirm_with_gate,
    prompt_secret_with_gate,
)
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultAdminAccessDeniedError,
    VaultAdminPasswordConfigError,
    VaultDomainError,
    VaultManagementOperationError,
)
from connector.usecases.management.vault.models import VaultKeyManagementStatus
from connector.usecases.management.vault.usecase import VaultKeyManagementUseCase


@dataclass(frozen=True)
class CommonOptions:
    force: bool = False
    dry_run: bool = False
    non_interactive: bool = False
    verify: bool = True


@dataclass(frozen=True)
class InitOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class StatusOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class RotateOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class RewrapOptions(CommonOptions):
    pass


class _NoopPostVerifier:
    """No-op post-verify адаптер для режима `--no-verify`."""

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        _ = keyring


_LOGGER = structlog.get_logger(__name__)


def init_handler(
    ctx: BoundCommandContext, opts: InitOptions, report_sink
) -> CommandResult:
    _ = report_sink
    try:
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="init")
        if gate_result is not None:
            return gate_result

        usecase = _build_key_management_usecase(ctx=ctx, verify=opts.verify)
        status = usecase.status()
        if opts.dry_run:
            can_apply = not status.initialized
            _emit_json_payload(
                {
                    "operation": "init",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "already_initialized": status.initialized,
                }
            )
            return result_with(
                SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID
            )

        passphrase = _prompt_new_unseal_passphrase(ctx)
        result = usecase.init_keyring(passphrase=passphrase)
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="init", exc=exc)


def status_handler(
    ctx: BoundCommandContext, opts: StatusOptions, report_sink
) -> CommandResult:
    _ = report_sink
    try:
        gate_result = _verify_admin_access(
            ctx=ctx, non_interactive=opts.non_interactive, operation="status"
        )
        if gate_result is not None:
            return gate_result

        usecase = _build_key_management_usecase(ctx=ctx, verify=opts.verify)
        status = usecase.status()
        verified = False
        if opts.verify and status.initialized:
            usecase.verify_unseal(passphrase=_prompt_current_unseal_passphrase(ctx))
            verified = True
        _emit_json_payload(_status_payload(status=status, verified=verified))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="status", exc=exc)


def rotate_handler(
    ctx: BoundCommandContext, opts: RotateOptions, report_sink
) -> CommandResult:
    _ = report_sink
    try:
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="rotate")
        if gate_result is not None:
            return gate_result

        usecase = _build_key_management_usecase(ctx=ctx, verify=opts.verify)
        status = usecase.status()
        if opts.dry_run:
            can_apply = status.initialized
            _emit_json_payload(
                {
                    "operation": "rotate",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "active_key_version": status.active_key_version,
                    "dek_total": status.dek_total,
                }
            )
            return result_with(
                SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID
            )

        current_passphrase = _prompt_current_unseal_passphrase(ctx)
        new_passphrase = _prompt_new_unseal_passphrase(ctx)
        result = usecase.rotate_and_rewrap(
            current_passphrase=current_passphrase,
            new_passphrase=new_passphrase,
        )
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="rotate", exc=exc)


def rewrap_handler(
    ctx: BoundCommandContext, opts: RewrapOptions, report_sink
) -> CommandResult:
    _ = report_sink
    try:
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="rewrap")
        if gate_result is not None:
            return gate_result

        usecase = _build_key_management_usecase(ctx=ctx, verify=opts.verify)
        status = usecase.status()
        if opts.dry_run:
            can_apply = status.initialized
            _emit_json_payload(
                {
                    "operation": "rewrap",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "active_key_version": status.active_key_version,
                    "dek_rewrap_required": status.dek_rewrap_required,
                }
            )
            return result_with(
                SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID
            )

        result = usecase.rewrap_all_dek(
            passphrase=_prompt_current_unseal_passphrase(ctx)
        )
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="rewrap", exc=exc)


def _prepare_manual_operation(
    *,
    ctx: BoundCommandContext,
    opts: CommonOptions,
    operation: str,
) -> CommandResult | None:
    confirm_result = _confirm_operation(ctx=ctx, opts=opts, operation=operation)
    if confirm_result is not None:
        return confirm_result
    return _verify_admin_access(
        ctx=ctx, non_interactive=opts.non_interactive, operation=operation
    )


def _confirm_operation(
    *,
    ctx: BoundCommandContext,
    opts: CommonOptions,
    operation: str,
) -> CommandResult | None:
    if opts.dry_run or opts.force:
        return None
    if opts.non_interactive:
        typer.echo(
            "ERROR: --non-interactive требует --force для отключения confirm-step",
            err=True,
        )
        return result_with(SystemErrorCode.DATA_INVALID)
    confirmed = confirm_with_gate(
        f"Подтвердить выполнение vault-management операции '{operation}'?",
        gate=ctx.container.observability.interactive_io_gate(),
        default=False,
    )
    if confirmed:
        return None
    typer.echo("Операция отменена пользователем.", err=True)
    return result_with(SystemErrorCode.OK)


def _verify_admin_access(
    *,
    ctx: BoundCommandContext,
    non_interactive: bool,
    operation: str,
) -> CommandResult | None:
    gate = ctx.container.vault_admin_password_gate()
    try:
        gate.verify_manual_access(non_interactive=non_interactive)
    except VaultAdminPasswordConfigError as exc:
        return _map_error_to_result(operation=operation, exc=exc)
    except VaultAdminAccessDeniedError as exc:
        return _map_error_to_result(operation=operation, exc=exc)
    return None


def _build_key_management_usecase(
    *,
    ctx: BoundCommandContext,
    verify: bool,
) -> VaultKeyManagementUseCase:
    post_verify = ctx.container.vault_post_verifier() if verify else _NoopPostVerifier()
    return ctx.container.vault_key_management_usecase(post_verify=post_verify)


def _prompt_current_unseal_passphrase(ctx: BoundCommandContext) -> str:
    return prompt_secret_with_gate(
        "Введите unseal passphrase",
        gate=ctx.container.observability.interactive_io_gate(),
    )


def _prompt_new_unseal_passphrase(ctx: BoundCommandContext) -> str:
    return prompt_secret_with_gate(
        "Введите новую unseal passphrase",
        gate=ctx.container.observability.interactive_io_gate(),
        confirmation_prompt=True,
    )


def _status_payload(
    *,
    status: VaultKeyManagementStatus,
    verified: bool,
) -> dict[str, object]:
    payload = asdict(status)
    payload["operation"] = "status"
    payload["verified"] = verified
    return payload


def _emit_json_payload(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _map_error_to_result(*, operation: str, exc: Exception) -> CommandResult:
    _LOGGER.error(
        "vault_mgmt_delivery_failed",
        component="vault_management",
        operation=operation,
        error_type=type(exc).__name__,
    )

    if isinstance(exc, VaultAdminAccessDeniedError):
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        return result_with(SystemErrorCode.AUTH_FORBIDDEN)
    if isinstance(
        exc,
        (
            VaultAdminPasswordConfigError,
            SecretKeyConfigError,
            VaultManagementOperationError,
        ),
    ):
        if isinstance(exc, VaultDomainError):
            typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        else:
            typer.echo(f"ERROR: {exc}", err=True)
        return result_with(SystemErrorCode.DATA_INVALID)
    if isinstance(exc, VaultDomainError):
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)

    typer.echo("ERROR: vault-management command failed (see logs)", err=True)
    return result_with(SystemErrorCode.INTERNAL_ERROR)


__all__ = [
    "CommonOptions",
    "InitOptions",
    "StatusOptions",
    "RotateOptions",
    "RewrapOptions",
    "init_handler",
    "status_handler",
    "rotate_handler",
    "rewrap_handler",
]
