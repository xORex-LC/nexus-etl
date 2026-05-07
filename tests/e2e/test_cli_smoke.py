from pathlib import Path

from typer.testing import CliRunner
from connector.main import app
from tests.runtime_test_support import tracked_employees_runtime_roots, write_runtime_config

runner = CliRunner()

def test_help_shows_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.stdout
    assert "mapping" in result.stdout
    assert "check-api" in result.stdout
    assert "cache" in result.stdout
    assert "vault-management" in result.stdout

def test_import_requires_subcommand():
    result = runner.invoke(
        app,
        ["--host", "1.2.3.4", "--port", "5456", "--api-username", "user", "--api-password", "pass", "import"],
    )
    assert result.exit_code == 2
    assert "Usage: root import" in result.stdout

def test_mapping_requires_configured_source(tmp_path: Path):
    roots = tracked_employees_runtime_roots()
    config_path = write_runtime_config(
        tmp_path,
        registry_path=roots["registry_path"],
        datasets_root=roots["datasets_root"],
        source_data_root=tmp_path / "missing-sources",
        source_projection_root=roots["source_projection_root"],
        target_projection_root=roots["target_projection_root"],
        dictionary_specs_root=roots["dictionary_specs_root"],
        dictionary_data_root=roots["dictionary_data_root"],
    )
    result = runner.invoke(app, ["--config", str(config_path), "mapping"])
    assert result.exit_code == 2
