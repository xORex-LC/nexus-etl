"""
Назначение:
    Delivery boundary для user-facing CLI команд `vault-management`.

Граница ответственности:
    - Принимает уже распарсенные CLI-опции и вызывает usecase-оркестраторы.
    - Выполняет confirm/password gate для manual операций.
    - Не реализует rotate/rewrap бизнес-алгоритмы и не делает прямой IO в vault DB.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace

import structlog
import typer

from connector.common.time import getUtcNowIso
from connector.config.projections import to_vault_management_settings
from connector.delivery.cli.context import BoundCommandContext
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
from connector.infra.secrets import parse_master_keyring
from connector.infra.secrets.env_key_provider import DEFAULT_MASTER_KEYS_ENV
from connector.usecases.management.vault.models import VaultKeyManagementStatus
from connector.usecases.operations.vault_management_settings import VaultManagementSettings


@dataclass(frozen=True)
class CommonOptions:
    force: bool = False
    dry_run: bool = False
    non_interactive: bool = False
    verify: bool = True
    managed_env_file: str | None = None


@dataclass(frozen=True)
class InitOptions(CommonOptions):
    import_existing_env: bool = False


@dataclass(frozen=True)
class StatusOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class RotateOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class RewrapOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class DeleteKeyOptions(CommonOptions):
    pass


@dataclass(frozen=True)
class RunMaintenanceOptions(CommonOptions):
    pass


class _NoopPostVerifier:
    """Назначение:
        No-op post-verify адаптер для режима `--no-verify`.
    """

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        _ = keyring


_LOGGER = structlog.get_logger(__name__)


def init_handler(ctx: BoundCommandContext, opts: InitOptions, report_sink) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        usecase = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="init")
        if gate_result is not None:
            return gate_result

        status = usecase.status()
        import_keyring: tuple[VaultMasterKey, ...] | None = None
        if opts.import_existing_env:
            import_keyring = _load_import_existing_env_keyring()

        if opts.dry_run:
            can_apply = status.active_key_version is None
            _emit_json_payload(
                {
                    "operation": "init",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "managed_env_file": settings.managed_env_file,
                    "already_initialized": status.active_key_version is not None,
                    "import_existing_env": opts.import_existing_env,
                    "import_key_count": len(import_keyring) if import_keyring is not None else 0,
                }
            )
            return result_with(SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID)

        result = usecase.init_keyring(initial_keyring=import_keyring)
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="init", exc=exc)


def status_handler(ctx: BoundCommandContext, opts: StatusOptions, report_sink) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        usecase = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        status = usecase.status()
        _emit_json_payload(_status_payload(status=status, settings=settings))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="status", exc=exc)


def rotate_handler(ctx: BoundCommandContext, opts: RotateOptions, report_sink) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        usecase = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="rotate")
        if gate_result is not None:
            return gate_result

        status = usecase.status()
        if opts.dry_run:
            can_apply = status.active_key_version is not None
            _emit_json_payload(
                {
                    "operation": "rotate",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "managed_env_file": settings.managed_env_file,
                    "active_key_version": status.active_key_version,
                    "dek_total": status.dek_total,
                }
            )
            return result_with(SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID)

        result = usecase.rotate_and_rewrap()
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="rotate", exc=exc)


def rewrap_handler(ctx: BoundCommandContext, opts: RewrapOptions, report_sink) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        usecase = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="rewrap")
        if gate_result is not None:
            return gate_result

        status = usecase.status()
        if opts.dry_run:
            can_apply = status.active_key_version is not None
            _emit_json_payload(
                {
                    "operation": "rewrap",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "managed_env_file": settings.managed_env_file,
                    "active_key_version": status.active_key_version,
                    "dek_rewrap_required": status.dek_rewrap_required,
                }
            )
            return result_with(SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID)

        result = usecase.rewrap_all_dek()
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="rewrap", exc=exc)


def delete_key_handler(ctx: BoundCommandContext, opts: DeleteKeyOptions, report_sink) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        usecase = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="delete-key")
        if gate_result is not None:
            return gate_result

        status = usecase.status()
        if opts.dry_run:
            can_apply = status.active_key_version is not None
            _emit_json_payload(
                {
                    "operation": "delete_key",
                    "dry_run": True,
                    "can_apply": can_apply,
                    "managed_env_file": settings.managed_env_file,
                    "active_key_version": status.active_key_version,
                    "mode": "replace_flow",
                }
            )
            return result_with(SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID)

        result = usecase.delete_key()
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="delete-key", exc=exc)


def run_maintenance_handler(
    ctx: BoundCommandContext,
    opts: RunMaintenanceOptions,
    report_sink,
) -> CommandResult:
    _ = report_sink
    settings = _resolve_settings(ctx, opts)
    try:
        key_management = _build_key_management_usecase(ctx=ctx, settings=settings, verify=opts.verify)
        rotation_policy = ctx.container.vault_rotation_policy(interval=settings.auto_rotate_interval)
        maintenance = ctx.container.vault_maintenance_usecase(
            key_management=key_management,
            rotation_policy=rotation_policy,
        )
        gate_result = _prepare_manual_operation(ctx=ctx, opts=opts, operation="run-maintenance")
        if gate_result is not None:
            return gate_result

        status = key_management.status()
        if opts.dry_run:
            action, can_apply, due = _maintenance_dry_run_plan(
                status=status,
                rotation_policy=rotation_policy,
            )
            _emit_json_payload(
                {
                    "operation": "run_maintenance",
                    "dry_run": True,
                    "managed_env_file": settings.managed_env_file,
                    "action": action,
                    "due": due,
                    "can_apply": can_apply,
                    "bridge_keyring": status.bridge_keyring,
                    "active_key_version": status.active_key_version,
                }
            )
            return result_with(SystemErrorCode.OK if can_apply else SystemErrorCode.DATA_INVALID)

        result = maintenance.run_if_due()
        _emit_json_payload(asdict(result))
        return result_with(SystemErrorCode.OK)
    except Exception as exc:  # noqa: BLE001
        return _map_error_to_result(operation="run-maintenance", exc=exc)


def _prepare_manual_operation(
    *,
    ctx: BoundCommandContext,
    opts: CommonOptions,
    operation: str,
) -> CommandResult | None:
    confirm_result = _confirm_operation(opts=opts, operation=operation)
    if confirm_result is not None:
        return confirm_result
    return _verify_admin_access(ctx=ctx, non_interactive=opts.non_interactive, operation=operation)


def _confirm_operation(*, opts: CommonOptions, operation: str) -> CommandResult | None:
    if opts.dry_run or opts.force:
        return None
    if opts.non_interactive:
        typer.echo(
            "ERROR: --non-interactive требует --force для отключения confirm-step",
            err=True,
        )
        return result_with(SystemErrorCode.DATA_INVALID)
    confirmed = typer.confirm(
        f"Подтвердить выполнение vault-management операции '{operation}'?",
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


def _resolve_settings(ctx: BoundCommandContext, opts: CommonOptions) -> VaultManagementSettings:
    """Назначение:
        Построить effective settings snapshot с локальным CLI-override path.

    Контракт:
        - Базовый snapshot приходит из CONFIG-пайплайна (`ENV > config.yml > defaults`).
        - `--managed-env-file` применяется поверх него как верхний слой CLI.
    """
    base = to_vault_management_settings(ctx.app_config)
    if opts.managed_env_file is None:
        return base
    return replace(base, managed_env_file=opts.managed_env_file)


def _build_key_management_usecase(
    *,
    ctx: BoundCommandContext,
    settings: VaultManagementSettings,
    verify: bool,
):
    keyring_store = ctx.container.vault_managed_keyring_store(managed_env_file=settings.managed_env_file)
    post_verify = ctx.container.vault_post_verifier() if verify else _NoopPostVerifier()
    return ctx.container.vault_key_management_usecase(
        keyring_store=keyring_store,
        post_verify=post_verify,
    )


def _load_import_existing_env_keyring() -> tuple[VaultMasterKey, ...]:
    raw = os.environ.get(DEFAULT_MASTER_KEYS_ENV)
    if raw is None or not raw.strip():
        raise VaultManagementOperationError(
            "Import source env variable is empty",
            details={
                "reason": "import_existing_env_missing",
                "env_var": DEFAULT_MASTER_KEYS_ENV,
            },
        )
    keyring = parse_master_keyring(raw, env_var=DEFAULT_MASTER_KEYS_ENV)
    if len(keyring) != 1:
        raise VaultManagementOperationError(
            "Import source keyring must contain exactly one key",
            details={
                "reason": "import_existing_env_requires_single_key",
                "env_var": DEFAULT_MASTER_KEYS_ENV,
                "key_count": len(keyring),
            },
        )
    return keyring


def _status_payload(
    *,
    status: VaultKeyManagementStatus,
    settings: VaultManagementSettings,
) -> dict[str, object]:
    payload = asdict(status)
    payload["operation"] = "status"
    payload["managed_env_file"] = settings.managed_env_file
    return payload


def _maintenance_dry_run_plan(
    *,
    status: VaultKeyManagementStatus,
    rotation_policy,
) -> tuple[str, bool, bool]:
    if status.bridge_keyring:
        return "bridge_finalize", True, False
    due = rotation_policy.is_due(last_rotated_at=status.last_rotated_at, now_utc=getUtcNowIso())
    if not due:
        return "no_op", True, False
    can_apply = status.active_key_version is not None
    return "rotate", can_apply, True


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
    if isinstance(exc, (VaultAdminPasswordConfigError, SecretKeyConfigError, VaultManagementOperationError)):
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
    "DeleteKeyOptions",
    "RunMaintenanceOptions",
    "init_handler",
    "status_handler",
    "rotate_handler",
    "rewrap_handler",
    "delete_key_handler",
    "run_maintenance_handler",
]
