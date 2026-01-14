from typer.testing import CliRunner
from connector.cli import app

runner = CliRunner()

def test_help_shows_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.stdout
    assert "validate" in result.stdout
    assert "check-api" in result.stdout
    assert "cache" in result.stdout

def test_import_requires_csv():
    result = runner.invoke(
        app,
        ["--host", "1.2.3.4", "--port", "5456", "--api-username", "user", "--api-password", "pass", "import"],
    )
    assert result.exit_code == 2
    assert "Usage: root import" in result.stdout

def test_validate_requires_csv():
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 2
