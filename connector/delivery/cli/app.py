"""CLI entrypoint — декларация Typer-команд и первичная сборка runtime command context.

Модуль отвечает за user-facing CLI surface: парсинг глобальных опций, загрузку конфигурации,
инициализацию root command context и делегирование в runtime orchestration. Бизнес-логика
команд и infra wiring здесь не живут.

Responsibilities:
    - Зарегистрировать команды Typer и их delivery-level опции.
    - Загрузить `AppConfig`, подготовить runtime directories и собрать `CommandContext`.
    - Передать выполнение в `run_with_report()` / `run_without_report()`.

Out of scope:
    - Реализация use cases и pipeline stages.
    - Ручное создание infra-объектов вне DI composition root.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import typer

from connector.common.observability import (
    ObservabilityArtifactKind,
    ServiceComponent,
)
from connector.common.run_id import generate_run_id, resolve_pipeline_run_id
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli import options as cli_options
from connector.delivery.cli.completions import (
    complete_dir,
    complete_path,
    complete_plan,
)

if TYPE_CHECKING:
    from connector.delivery.cli.context import UnboundCommandContext

# ──────────────────────────────────────────────────────────────────────────────
# Ленивая загрузка бизнес-логики (perf: тонкий init для shell-completion/--help).
#
# Построение Typer-дерева (и, как следствие, shell-completion) импортирует ТОЛЬКО
# этот модуль. Хендлеры команд и runtime/DI-граф тянут usecases→domain→infra→polars
# (~0.6с), поэтому их импорт отложен до фактического вызова команды через прокси и
# обёртки ниже, а config/context импортируются локально в телах `main`/`_build_ctx`.
# Инвариант «тонкого init» закреплён тестом import-budget.
# ──────────────────────────────────────────────────────────────────────────────


class _LazyCommandModule:
    """Прокси командного модуля: импорт откладывается до первого обращения к
    атрибуту (`handler`/`Options`), т.е. до реального вызова команды."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._loaded: ModuleType | None = None

    def __getattr__(self, attr: str) -> Any:
        if self._loaded is None:
            self._loaded = importlib.import_module(self._module_name)
        return getattr(self._loaded, attr)


def run_with_report(**kwargs: Any) -> None:
    """Ленивая обёртка над runtime-фасадом (импорт отложен до вызова команды)."""
    from connector.delivery.cli.runtime import run_with_report as _impl

    _impl(**kwargs)


def run_without_report(**kwargs: Any) -> None:
    """Ленивая обёртка над runtime-фасадом (импорт отложен до вызова команды)."""
    from connector.delivery.cli.runtime import run_without_report as _impl

    _impl(**kwargs)


cache_clear_command = _LazyCommandModule("connector.delivery.commands.cache_clear")
cache_refresh_command = _LazyCommandModule("connector.delivery.commands.cache_refresh")
cache_status_command = _LazyCommandModule("connector.delivery.commands.cache_status")
check_api_command = _LazyCommandModule("connector.delivery.commands.check_api")
enrich_command = _LazyCommandModule("connector.delivery.commands.enrich")
import_apply_command = _LazyCommandModule("connector.delivery.commands.import_apply")
import_plan_command = _LazyCommandModule("connector.delivery.commands.import_plan")
maintenance_prune_command = _LazyCommandModule(
    "connector.delivery.commands.maintenance_prune"
)
match_command = _LazyCommandModule("connector.delivery.commands.match")
mapping_command = _LazyCommandModule("connector.delivery.commands.mapping")
normalize_command = _LazyCommandModule("connector.delivery.commands.normalize")
obs_artifacts_command = _LazyCommandModule("connector.delivery.commands.obs_artifacts")
resolve_command = _LazyCommandModule("connector.delivery.commands.resolve")
vault_management_command = _LazyCommandModule(
    "connector.delivery.commands.vault_management"
)

app = typer.Typer(no_args_is_help=True, add_completion=True)
cache_app = typer.Typer(no_args_is_help=True)
import_app = typer.Typer(no_args_is_help=True)
maintenance_app = typer.Typer(no_args_is_help=True)
obs_app = typer.Typer(no_args_is_help=True)
user_app = typer.Typer(no_args_is_help=True)
vault_management_app = typer.Typer(no_args_is_help=True)


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _build_ctx(
    ctx: typer.Context,
    dataset: str | None = None,
    *,
    command_key: str | None = None,
) -> UnboundCommandContext:
    from connector.config.projections import to_operational_paths
    from connector.delivery.cli.containers import build_diagnostics_catalog
    from connector.delivery.cli.context import CommandContext, CommandPaths
    from connector.delivery.cli.settings_slice_map import (
        COMMAND_SETTINGS_SLICE_MAP,
        COMMAND_TO_USECASE,
        USECASE_SETTINGS_SLICE_MAP,
    )

    app_config = ctx.obj.get("app_config")
    if app_config is None:
        raise RuntimeError("App config is not initialized")
    operational_paths = to_operational_paths(app_config)
    catalog = build_diagnostics_catalog(
        dataset, strict=app_config.observability.diagnostics.strict
    )
    extra: dict[str, Any] = {
        "sources": ctx.obj.get("sources"),
        "quiet": bool(ctx.obj.get("quiet")),
        "console_log_mirror": bool(ctx.obj.get("console_log_mirror")),
    }
    if command_key:
        usecase_name = COMMAND_TO_USECASE.get(command_key)
        extra["settings_contract"] = {
            "command_key": command_key,
            "command_slices": [
                t.__name__ for t in COMMAND_SETTINGS_SLICE_MAP.get(command_key, ())
            ],
            "usecase": usecase_name,
            "usecase_slices": [
                t.__name__ for t in USECASE_SETTINGS_SLICE_MAP.get(usecase_name, ())
            ]
            if usecase_name
            else [],
        }
    return CommandContext(
        logger=ctx.obj["logger"],
        run_id=ctx.obj["run_id"],
        pipeline_run_id=ctx.obj.get("pipeline_run_id"),
        catalog=catalog,
        strict=app_config.observability.diagnostics.strict,
        app_config=app_config,
        container=None,
        paths=CommandPaths(report_dir=operational_paths.report_dir, work_dir=None),
        extra=extra,
    )


@app.callback()
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(
        None, "--config", help="Path to config.yml", autocompletion=complete_path
    ),
    run_id: str | None = typer.Option(
        None, "--run-id", help="Run identifier (UUID). If omitted, generated."
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Disable console log mirroring; fatal user-facing errors still go to stderr.",
    ),
    console_log_mirror: bool = typer.Option(
        False,
        "--console-log-mirror",
        help="Mirror structured runtime logs to the console stderr in addition to the log file.",
    ),
    log_level: str | None = typer.Option(
        None, "--log-level", help="Log level: ERROR|WARN|INFO|DEBUG"
    ),
    log_json: bool | None = typer.Option(
        None, "--log-json", help="Enable JSON logging (reserved)"
    ),
    log_dir: str | None = typer.Option(
        None, "--log-dir", help="Directory for logs.", autocompletion=complete_dir
    ),
    report_dir: str | None = typer.Option(
        None, "--report-dir", help="Directory for reports.", autocompletion=complete_dir
    ),
    cache_dir: str | None = typer.Option(
        None,
        "--cache-dir",
        help="Directory for cache (SQLite later).",
        autocompletion=complete_dir,
    ),
    host: str | None = typer.Option(None, "--host", help="API host/IP"),
    port: int | None = typer.Option(None, "--port", help="API port"),
    api_username: str | None = typer.Option(
        None, "--api-username", help="API username"
    ),
    api_password: str | None = typer.Option(
        None, "--api-password", help="API password (avoid; use env/file)"
    ),
    api_passwordFile: str | None = typer.Option(
        None,
        "--api-password-file",
        help="Read API password from file",
        autocompletion=complete_path,
    ),
    tls_skip_verify: bool | None = typer.Option(
        None, "--tls-skip-verify", help="Disable TLS verification"
    ),
    ca_file: str | None = typer.Option(
        None, "--ca-file", help="CA file path", autocompletion=complete_path
    ),
    page_size: int | None = typer.Option(
        None, "--page-size", help="Page size for API pagination"
    ),
    max_pages: int | None = typer.Option(
        None, "--max-pages", help="Max pages to fetch from API"
    ),
    timeout_seconds: float | None = typer.Option(
        None, "--timeout-seconds", help="API timeout in seconds"
    ),
    retries: int | None = typer.Option(
        None, "--retries", help="Retry attempts for API calls"
    ),
    retry_backoff_seconds: float | None = typer.Option(
        None, "--retry-backoff-seconds", help="Base backoff for retries"
    ),
    match_batch_size: int | None = typer.Option(
        None, "--match-batch-size", help="Match micro-batch size"
    ),
    match_flush_interval_ms: int | None = typer.Option(
        None,
        "--match-flush-interval-ms",
        help="Match micro-batch flush interval (ms)",
    ),
    resolve_batch_size: int | None = typer.Option(
        None, "--resolve-batch-size", help="Resolve micro-batch size"
    ),
    resolve_flush_interval_ms: int | None = typer.Option(
        None,
        "--resolve-flush-interval-ms",
        help="Resolve micro-batch flush interval (ms)",
    ),
    strict_diagnostics: bool | None = typer.Option(
        None,
        "--strict-diagnostics/--no-strict-diagnostics",
        help="Fail on unknown diagnostic codes",
    ),
):
    from connector.config.config import SettingsLoadError
    from connector.config.diagnostics import translate_settings_load_error
    from connector.config.loader import load_app_config
    from connector.config.projections import (
        to_dataset_registry_path,
        to_operational_paths,
        to_runtime_path_overrides,
    )
    from connector.delivery.cli.containers import build_diagnostics_catalog
    from connector.domain.dsl.loader import (
        configure_registry_path,
        configure_runtime_paths,
    )
    from connector.domain.models import DiagnosticStage

    if api_passwordFile and not api_password:
        p = Path(api_passwordFile)
        if not p.exists() or not p.is_file():
            typer.echo(
                f"ERROR: api-password-file not found: {api_passwordFile}", err=True
            )
            raise typer.Exit(code=2)
        api_password = p.read_text(encoding="utf-8").strip()

    if not run_id:
        run_id = generate_run_id()
    pipeline_run_id = resolve_pipeline_run_id(run_id)

    cli_overrides = {
        "api.host": host,
        "api.port": port,
        "api.username": api_username,
        "api.password": api_password,
        "observability.logging.level": log_level,
        "observability.logging.sinks.console.format": (
            "json" if log_json is True else "text" if log_json is False else None
        ),
        "paths.log_dir": log_dir,
        "paths.report_dir": report_dir,
        "paths.cache_dir": cache_dir,
        "api.tls_skip_verify": tls_skip_verify,
        "api.ca_file": ca_file,
        "refresh.page_size": page_size,
        "refresh.max_pages": max_pages,
        "api.timeout_seconds": timeout_seconds,
        "api.retries": retries,
        "api.retry_backoff_seconds": retry_backoff_seconds,
        "matching_runtime.match_batch_size": match_batch_size,
        "matching_runtime.match_flush_interval_ms": match_flush_interval_ms,
        "resolver.resolve_batch_size": resolve_batch_size,
        "resolver.resolve_flush_interval_ms": resolve_flush_interval_ms,
        "observability.diagnostics.strict": strict_diagnostics,
    }
    try:
        loaded_app = load_app_config(config, cli_overrides=cli_overrides)
    except SettingsLoadError as exc:
        catalog = build_diagnostics_catalog(None, strict=False)
        diagnostics = translate_settings_load_error(
            catalog=catalog,
            stage=DiagnosticStage.SINK,
            error=exc,
            record_ref=None,
        )
        typer.echo("ERROR: invalid settings configuration", err=True)
        for diag in diagnostics:
            field = f" ({diag.field})" if diag.field else ""
            typer.echo(f"- [{diag.code}]{field} {diag.message}", err=True)
        raise typer.Exit(code=2) from exc
    configure_runtime_paths(to_runtime_path_overrides(loaded_app.app_config))
    configure_registry_path(to_dataset_registry_path(loaded_app.app_config))
    operational_paths = to_operational_paths(loaded_app.app_config)
    _ensure_dir(operational_paths.log_dir)
    _ensure_dir(operational_paths.report_dir)
    _ensure_dir(operational_paths.plans_dir)
    _ensure_dir(operational_paths.cache_dir)

    ctx.obj = {
        "run_id": run_id,
        "pipeline_run_id": pipeline_run_id,
        "app_config": loaded_app.app_config,
        "operational_paths": operational_paths,
        "sources": sorted(
            {v for v in loaded_app.source_trace.values() if v != "default"}
        ),
        "settings_source_trace": loaded_app.source_trace,
        "configPath": config,
        "logger": None,
        "quiet": quiet,
        "console_log_mirror": console_log_mirror,
    }


@app.command("mapping")
def mapping(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeMappedItems: bool | None = typer.Option(
        None,
        "--include-mapped-items/--no-include-mapped-items",
        help="Include mapped rows in report items",
        show_default=True,
    ),
):
    opts = mapping_command.Options(
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_mapped_items=includeMappedItems,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="mapping")
    run_with_report(
        ctx=command_ctx,
        command_name="mapping",
        opts=opts,
        handler=mapping_command.handler,
        requirements=Requirements(
            requires_source=True, requires_dataset=True, requires_cache=True
        ),
    )


@app.command("match")
def match(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeMatchedItems: bool | None = typer.Option(
        None,
        "--include-matched-items/--no-include-matched-items",
        help="Include matched rows in report items",
        show_default=True,
    ),
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
):
    opts = match_command.Options(
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_matched_items=includeMatchedItems,
        include_deleted=includeDeleted,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="match")
    run_with_report(
        ctx=command_ctx,
        command_name="match",
        opts=opts,
        handler=match_command.handler,
        requirements=Requirements(
            requires_source=True, requires_dataset=True, requires_cache=True
        ),
    )


@app.command("normalize")
def normalize(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeNormalizedItems: bool | None = typer.Option(
        None,
        "--include-normalized-items/--no-include-normalized-items",
        help="Include normalized rows in report items",
        show_default=True,
    ),
):
    opts = normalize_command.Options(
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_normalized_items=includeNormalizedItems,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="normalize")
    run_with_report(
        ctx=command_ctx,
        command_name="normalize",
        opts=opts,
        handler=normalize_command.handler,
        requirements=Requirements(
            requires_source=True, requires_dataset=True, requires_cache=True
        ),
    )


@app.command("resolve")
def resolve(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeResolvedItems: bool | None = typer.Option(
        None,
        "--include-resolved-items/--no-include-resolved-items",
        help="Include resolved rows in report items",
        show_default=True,
    ),
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
):
    opts = resolve_command.Options(
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_resolved_items=includeResolvedItems,
        include_deleted=includeDeleted,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="resolve")
    run_with_report(
        ctx=command_ctx,
        command_name="resolve",
        opts=opts,
        handler=resolve_command.handler,
        requirements=Requirements(
            requires_source=True, requires_dataset=True, requires_cache=True
        ),
    )


@app.command("enrich")
def enrich(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeEnrichedItems: bool | None = typer.Option(
        None,
        "--include-enriched-items/--no-include-enriched-items",
        help="Include enriched rows in report items",
        show_default=True,
    ),
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = enrich_command.Options(
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_enriched_items=includeEnrichedItems,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="enrich")
    run_with_report(
        ctx=command_ctx,
        command_name="enrich",
        opts=opts,
        handler=enrich_command.handler,
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
            requires_dictionaries=True,
        ),
    )


@import_app.command("plan")
def importPlan(
    ctx: typer.Context,
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    reportIncludeSkipped: bool | None = typer.Option(
        None,
        "--report-include-skipped/--no-report-include-skipped",
        help="Include skipped rows in plan report",
        show_default=True,
    ),
    dataset: str | None = cli_options.DATASET,
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = import_plan_command.Options(
        include_deleted=includeDeleted,
        report_items_limit=reportItemsLimit,
        report_include_skipped=reportIncludeSkipped,
        dataset=dataset,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="import-plan")
    run_with_report(
        ctx=command_ctx,
        command_name="import-plan",
        opts=opts,
        handler=import_plan_command.handler,
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
            requires_dictionaries=True,
        ),
    )


@import_app.command("apply")
def import_apply(
    ctx: typer.Context,
    plan: str | None = typer.Option(
        None, "--plan", help="Path to plan_import.json", autocompletion=complete_plan
    ),
    stopOnFirstError: bool | None = cli_options.STOP_ON_FIRST_ERROR,
    maxActions: int | None = cli_options.MAX_ACTIONS,
    dryRun: bool | None = cli_options.DRY_RUN,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = import_apply_command.Options(
        plan_path=plan,
        stop_on_first_error=stopOnFirstError,
        max_actions=maxActions,
        dry_run=dryRun,
        report_items_limit=reportItemsLimit,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, command_key="import-apply")
    run_with_report(
        ctx=command_ctx,
        command_name="import-apply",
        opts=opts,
        handler=import_apply_command.handler,
        requirements=Requirements(requires_api=True, requires_cache=True),
    )


@app.command("check-api")
def checkApi(ctx: typer.Context):
    opts = check_api_command.Options(api_transport=None)
    command_ctx = _build_ctx(ctx, command_key="check-api")
    run_with_report(
        ctx=command_ctx,
        command_name="check-api",
        opts=opts,
        handler=check_api_command.handler,
        requirements=Requirements(requires_api=True),
    )


@cache_app.command("refresh")
def cacheRefresh(
    ctx: typer.Context,
    page_size: int | None = typer.Option(
        None, "--page-size", help="Page size for API pagination"
    ),
    max_pages: int | None = typer.Option(
        None, "--max-pages", help="Maximum pages to fetch from API"
    ),
    timeout_seconds: float | None = cli_options.TIMEOUT_SECONDS,
    retries: int | None = cli_options.RETRIES,
    retry_backoff_seconds: float | None = cli_options.RETRY_BACKOFF_SECONDS,
    dataset: str | None = cli_options.DATASET,
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
    deps: bool | None = typer.Option(
        None,
        "--deps/--no-deps",
        help="Include dataset dependencies in refresh scope (defaults to cache policy)",
    ),
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
):
    app_config = ctx.obj.get("app_config")
    if app_config is None:
        raise RuntimeError("App config is not initialized")
    opts = cache_refresh_command.Options(
        page_size=page_size if page_size is not None else app_config.refresh.page_size,
        max_pages=max_pages if max_pages is not None else app_config.refresh.max_pages,
        timeout_seconds=timeout_seconds,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
        include_deleted=includeDeleted,
        include_dependencies=deps,
        report_items_limit=reportItemsLimit,
        dataset=dataset,
        api_transport=None,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-refresh")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-refresh",
        opts=opts,
        handler=cache_refresh_command.handler,
        requirements=Requirements(requires_api=True, requires_cache=True),
    )


@cache_app.command("status")
def cacheStatus(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
):
    opts = cache_status_command.Options(dataset=dataset)
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-status")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-status",
        opts=opts,
        handler=cache_status_command.handler,
        requirements=Requirements(requires_cache=True),
    )


@cache_app.command("clear")
def cacheClear(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    cascade: bool | None = typer.Option(
        None,
        "--cascade/--no-cascade",
        help="Cascade clear to dependent datasets (defaults to cache policy)",
    ),
):
    opts = cache_clear_command.Options(dataset=dataset, cascade=cascade)
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-clear")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-clear",
        opts=opts,
        handler=cache_clear_command.handler,
        requirements=Requirements(requires_cache=True),
    )


@vault_management_app.command("init")
def vaultManagementInit(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Skip confirmation step"),
    dryRun: bool = typer.Option(
        False, "--dry-run", help="Validate and show plan without writes"
    ),
    nonInteractive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable interactive prompts; password comes from ENV",
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Run post-operation startup verify",
    ),
):
    opts = vault_management_command.InitOptions(
        force=force,
        dry_run=dryRun,
        non_interactive=nonInteractive,
        verify=verify,
    )
    command_ctx = _build_ctx(ctx, command_key="vault-management-init")
    run_without_report(
        ctx=command_ctx,
        command_name="vault-management-init",
        opts=opts,
        handler=vault_management_command.init_handler,
        requirements=Requirements(requires_vault_schema=True),
    )


@vault_management_app.command("status")
def vaultManagementStatus(
    ctx: typer.Context,
    force: bool = typer.Option(
        False, "--force", help="Accepted for command contract consistency"
    ),
    dryRun: bool = typer.Option(
        False, "--dry-run", help="No-op for read-only status command"
    ),
    nonInteractive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Accepted for command contract consistency",
    ),
    verify: bool = typer.Option(
        False,
        "--verify/--no-verify",
        help="Verify unseal passphrase and startup probe",
    ),
):
    opts = vault_management_command.StatusOptions(
        force=force,
        dry_run=dryRun,
        non_interactive=nonInteractive,
        verify=verify,
    )
    command_ctx = _build_ctx(ctx, command_key="vault-management-status")
    run_without_report(
        ctx=command_ctx,
        command_name="vault-management-status",
        opts=opts,
        handler=vault_management_command.status_handler,
        requirements=Requirements(requires_vault_schema=True),
    )


@vault_management_app.command("rotate")
def vaultManagementRotate(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Skip confirmation step"),
    dryRun: bool = typer.Option(
        False, "--dry-run", help="Validate and show plan without writes"
    ),
    nonInteractive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable interactive prompts; password comes from ENV",
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Run post-operation startup verify",
    ),
):
    opts = vault_management_command.RotateOptions(
        force=force,
        dry_run=dryRun,
        non_interactive=nonInteractive,
        verify=verify,
    )
    command_ctx = _build_ctx(ctx, command_key="vault-management-rotate")
    run_without_report(
        ctx=command_ctx,
        command_name="vault-management-rotate",
        opts=opts,
        handler=vault_management_command.rotate_handler,
        requirements=Requirements(requires_vault_schema=True),
    )


@vault_management_app.command("rewrap")
def vaultManagementRewrap(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Skip confirmation step"),
    dryRun: bool = typer.Option(
        False, "--dry-run", help="Validate and show plan without writes"
    ),
    nonInteractive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable interactive prompts; password comes from ENV",
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Run post-operation startup verify",
    ),
):
    opts = vault_management_command.RewrapOptions(
        force=force,
        dry_run=dryRun,
        non_interactive=nonInteractive,
        verify=verify,
    )
    command_ctx = _build_ctx(ctx, command_key="vault-management-rewrap")
    run_without_report(
        ctx=command_ctx,
        command_name="vault-management-rewrap",
        opts=opts,
        handler=vault_management_command.rewrap_handler,
        requirements=Requirements(requires_vault_schema=True),
    )


@maintenance_app.command("prune")
def maintenancePrune(
    ctx: typer.Context,
    component: ServiceComponent | None = typer.Option(
        None,
        "--component",
        help="Optional component filter (e.g. planner, applier, cache).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Ignore same-day retention markers and run prune immediately.",
    ),
):
    opts = maintenance_prune_command.Options(component=component, force=force)
    command_ctx = _build_ctx(ctx, command_key="maintenance-prune")
    run_with_report(
        ctx=command_ctx,
        command_name="maintenance-prune",
        opts=opts,
        handler=maintenance_prune_command.handler,
        requirements=Requirements(),
    )


@obs_app.command("latest")
def obsLatest(
    ctx: typer.Context,
    component: ServiceComponent = typer.Argument(
        ..., help="Logical service component (planner, applier, enricher, ...)."
    ),
    artifact: ObservabilityArtifactKind = typer.Option(
        ObservabilityArtifactKind.REPORT,
        "--artifact",
        help="Artifact type to display.",
    ),
):
    opts = obs_artifacts_command.LatestOptions(
        component=component,
        artifact=artifact,
    )
    command_ctx = _build_ctx(ctx, command_key="obs-latest")
    run_with_report(
        ctx=command_ctx,
        command_name="obs-latest",
        opts=opts,
        handler=obs_artifacts_command.latest_handler,
        requirements=Requirements(),
    )


@obs_app.command("tail")
def obsTail(
    ctx: typer.Context,
    component: ServiceComponent = typer.Argument(
        ..., help="Logical service component (planner, applier, enricher, ...)."
    ),
    artifact: ObservabilityArtifactKind = typer.Option(
        ObservabilityArtifactKind.LOG,
        "--artifact",
        help="Artifact type to read tail from.",
    ),
    lines: int = typer.Option(
        20,
        "--lines",
        min=1,
        help="How many last lines to print.",
    ),
):
    opts = obs_artifacts_command.TailOptions(
        component=component,
        artifact=artifact,
        lines=lines,
    )
    command_ctx = _build_ctx(ctx, command_key="obs-tail")
    run_with_report(
        ctx=command_ctx,
        command_name="obs-tail",
        opts=opts,
        handler=obs_artifacts_command.tail_handler,
        requirements=Requirements(),
    )


app.add_typer(cache_app, name="cache")
app.add_typer(import_app, name="import")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(obs_app, name="obs")
app.add_typer(user_app, name="user")
app.add_typer(vault_management_app, name="vault-management")
