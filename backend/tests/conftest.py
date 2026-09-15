import os
import sys
import tempfile
from pathlib import Path

import pytest

# подкрутить путь, чтобы тесты видели backend-пакеты
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Пока конфиг ещё не импортирован — направляем DATA_DIR во временную папку.
_TEST_DATA = Path(tempfile.mkdtemp(prefix="autocut_test_"))
os.environ["AUTOCUT_DATA_DIR"] = str(_TEST_DATA)

import jobs  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_jobs(monkeypatch):
    """Полный изоляция: пустой реестр джобов на каждый тест."""
    monkeypatch.setattr(jobs, "_JOBS", {})
    yield