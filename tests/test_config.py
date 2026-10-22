from pathlib import Path

import pytest
from pydantic import ValidationError

from autocut.config import load_config
from autocut.models import JobOptions

ENV_VARS = [
    "AUTOCUT_OUTPUT", "AUTOCUT_WORKDIR", "AUTOCUT_MODEL",
    "AUTOCUT_PROXY", "AUTOCUT_COOKIES", "AUTOCUT_DEVICE",
    "AUTOCUT_COMPUTE_TYPE", "AUTOCUT_ASCII_SLUG", "AUTOCUT_KEEP_WORK",
    "AUTOCUT_LANGUAGE", "AUTOCUT_MAX_HEIGHT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    cfg = load_config()
    assert cfg.output_dir == Path("output")
    assert cfg.work_dir == Path("work")
    assert cfg.model == "small"
    assert cfg.device == "cpu"


def test_yaml_then_env_override(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output_dir: custom_out\nmodel: base\n", encoding="utf-8")
    monkeypatch.setenv("AUTOCUT_MODEL", "tiny")
    cfg = load_config(cfg_file)
    assert cfg.output_dir == Path("custom_out")
    assert cfg.model == "tiny"


def test_bool_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOCUT_KEEP_WORK", "true")
    assert load_config().keep_work is True


def test_max_height_from_env(monkeypatch):
    monkeypatch.setenv("AUTOCUT_MAX_HEIGHT", "720")
    assert load_config().max_height == 720


def test_max_height_rejects_invalid(monkeypatch):
    monkeypatch.setenv("AUTOCUT_MAX_HEIGHT", "abc")
    with pytest.raises(ValueError, match="целым"):
        load_config()
    monkeypatch.setenv("AUTOCUT_MAX_HEIGHT", "100")
    with pytest.raises(ValueError, match="240"):
        load_config()


def test_job_options_clamp_target():
    opts = JobOptions(min_duration=40, max_duration=50, target_duration=30)
    assert opts.target_duration == 40


def test_job_options_reject_inverted_range():
    with pytest.raises(ValidationError):
        JobOptions(min_duration=70, max_duration=30)
