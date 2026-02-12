"""
Fixtures для E2E тестов.

E2E тесты:
- Полный pipeline
- CliRunner, tmp directories
- Mock API
- Медленные (5-30 сек)
"""
import pytest
from typer.testing import CliRunner

@pytest.fixture
def cli_runner():
    return CliRunner()
