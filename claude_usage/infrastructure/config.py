"""Adapter reading claude-usage's config.toml. Read-only; the app never writes it."""
from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

from claude_usage.application.ports import Config

DEFAULT_PATH = Path.home() / ".config" / "claude-usage" / "config.toml"

_POLL_SECONDS_RANGE = range(1, 601)
_STALE_MINUTES_RANGE = range(1, 1441)


class TomlConfigSource:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else DEFAULT_PATH

    def read_config(self) -> Config:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return Config()
        except OSError:
            return Config(warnings=("could not read config.toml — using defaults",))

        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return Config(warnings=("malformed config.toml — using defaults",))

        warnings: list[str] = []
        poll_seconds = _read_int(data, "poll_seconds", 10, _POLL_SECONDS_RANGE, warnings)
        stale_minutes = _read_int(
            data, "stale_after_minutes", 15, _STALE_MINUTES_RANGE, warnings
        )
        return Config(
            poll_seconds=poll_seconds,
            stale_after=timedelta(minutes=stale_minutes),
            warnings=tuple(warnings),
        )


def _read_int(
    data: dict, key: str, default: int, valid_range: range, warnings: list[str]
) -> int:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value not in valid_range:
        warnings.append(f"{key} is invalid — using default")
        return default
    return value
