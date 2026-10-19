from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Config:
    output_dir: Path = Path("output")
    work_dir: Path = Path("work")
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    proxy: str | None = None
    cookies: Path | None = None
    ascii_slug: bool = False
    keep_work: bool = False
    language: str | None = None
    max_height: int = 1080


_ENV = {
    "output_dir": "AUTOCUT_OUTPUT",
    "work_dir": "AUTOCUT_WORKDIR",
    "model": "AUTOCUT_MODEL",
    "device": "AUTOCUT_DEVICE",
    "compute_type": "AUTOCUT_COMPUTE_TYPE",
    "proxy": "AUTOCUT_PROXY",
    "cookies": "AUTOCUT_COOKIES",
    "ascii_slug": "AUTOCUT_ASCII_SLUG",
    "keep_work": "AUTOCUT_KEEP_WORK",
    "language": "AUTOCUT_LANGUAGE",
}

_BOOL_KEYS = {"ascii_slug", "keep_work"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: Path | None = None, **overrides: Any) -> Config:
    data: dict[str, Any] = {
        "output_dir": Path("output"),
        "work_dir": Path("work"),
        "model": "small",
        "device": "cpu",
        "compute_type": "int8",
        "proxy": None,
        "cookies": None,
        "ascii_slug": False,
        "keep_work": False,
        "language": None,
        "max_height": 1080,
    }

    if path is not None and Path(path).exists():
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        data.update({k: v for k, v in loaded.items() if k in data})

    for key, env_name in _ENV.items():
        if env_name in os.environ:
            data[key] = os.environ[env_name]

    for key, value in overrides.items():
        if value is not None and key in data:
            data[key] = value

    for key in _BOOL_KEYS:
        data[key] = _as_bool(data[key])
    data["max_height"] = int(data["max_height"])
    data["output_dir"] = Path(data["output_dir"]).expanduser()
    data["work_dir"] = Path(data["work_dir"]).expanduser()
    if data["cookies"]:
        data["cookies"] = Path(data["cookies"]).expanduser()
    return Config(**data)
