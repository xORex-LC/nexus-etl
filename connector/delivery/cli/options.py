from __future__ import annotations

import typer


# Common dataset options
DATASET = typer.Option(None, "--dataset", help="Dataset name")

# Source options
CSV_HAS_HEADER = typer.Option(None, "--csv-has-header", help="CSV has header row")

# Report options
REPORT_ITEMS_LIMIT = typer.Option(None, "--report-items-limit", help="Max items stored in report")
REPORT_DIR = typer.Option(None, "--report-dir", help="Report output directory")

# API options
TIMEOUT_SECONDS = typer.Option(None, "--timeout-seconds", help="API timeout in seconds")
RETRIES = typer.Option(None, "--retries", help="API retries")
RETRY_BACKOFF_SECONDS = typer.Option(None, "--retry-backoff-seconds", help="API retry backoff")

# Cache options
CACHE_DIR = typer.Option(None, "--cache-dir", help="Cache directory")
INCLUDE_DELETED = typer.Option(None, "--include-deleted", help="Include soft-deleted records")

# Secrets options
SECRETS_FROM = typer.Option(None, "--secrets-from", help="Secrets provider (none|prompt|vault)")
VAULT_MODE = typer.Option(
    None,
    "--vault-mode",
    help="Vault runtime mode (auto|on|off). Default: auto",
)

# Plan/apply options
MAX_ACTIONS = typer.Option(None, "--max-actions", help="Max number of actions")
DRY_RUN = typer.Option(None, "--dry-run", help="Do not perform write operations")
STOP_ON_FIRST_ERROR = typer.Option(None, "--stop-on-first-error", help="Stop on first error")
RESOURCE_EXISTS_RETRIES = typer.Option(None, "--resource-exists-retries", help="Retries for resource exists")
