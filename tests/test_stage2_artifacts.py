from pathlib import Path
from typer.testing import CliRunner
from connector.main import app

runner = CliRunner()

def test_import_requires_csv(tmp_path: Path):
    logDir = tmp_path / "logs"
    reportDir = tmp_path / "reports"
    cacheDir = tmp_path / "cache"

    secret = "SUPER_SECRET_PASSWORD"

    result = runner.invoke(
        app,
        [
            "--log-dir", str(logDir),
            "--report-dir", str(reportDir),
            "--cache-dir", str(cacheDir),
            "--host", "1.2.3.4",
            "--port", "5456",
            "--api-username", "user",
            "--api-password", secret,
            "import",
        ],
    )

    assert result.exit_code == 2

    # Требование --csv
    assert "Usage: root import" in (result.stdout + result.stderr)

    # Секрет не должен светиться ни в stdout, ни в stderr
    assert secret not in result.stdout
    assert secret not in result.stderr
