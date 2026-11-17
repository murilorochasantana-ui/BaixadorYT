import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def dados_temporarios(tmp_path, monkeypatch):
    """Cada teste usa uma pasta de dados própria (nunca mexe no config real do usuário)."""
    monkeypatch.setenv("ESTUDIO_DADOS", str(tmp_path / "dados"))
    yield tmp_path


def pytest_configure(config):
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
