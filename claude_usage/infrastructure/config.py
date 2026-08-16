"""Adapter reading claude-usage's config.toml. Read-only; the app never writes it."""
from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

from claude_usage.application.ports import Config

DEFAULT_PATH = Path.home() / ".config" / "claude-usage" / "config.toml"

_POLL_SECONDS_RANGE = range(1, 601)
_STALE_MINUTES_RANGE = range(1, 1441)
_REFRESH_TIMEOUT_RANGE = range(5, 601)


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
        refresh_timeout = _read_int(
            data, "refresh_timeout_seconds", 60, _REFRESH_TIMEOUT_RANGE, warnings
        )
        claude_executable = _read_str(data, "claude_executable", warnings)
        return Config(
            poll_seconds=poll_seconds,
            stale_after=timedelta(minutes=stale_minutes),
            refresh_timeout_seconds=refresh_timeout,
            claude_executable=claude_executable,
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


def _read_str(data: dict, key: str, warnings: list[str]) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        warnings.append(f"{key} is invalid — using default")
        return None
    return value
