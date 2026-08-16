from datetime import timedelta

from claude_usage.application.ports import Config
from claude_usage.infrastructure.config import TomlConfigSource


def write_toml(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_absent_file_returns_defaults_silently(tmp_path):
    config = TomlConfigSource(tmp_path / "missing.toml").read_config()
    assert config == Config()
    assert config.warnings == ()


def test_valid_file_overrides_defaults(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 30\nstale_after_minutes = 5\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 30
    assert config.stale_after == timedelta(minutes=5)
    assert config.warnings == ()


def test_malformed_toml_gives_defaults_and_one_warning(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = [unterminated")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert config.stale_after == timedelta(minutes=15)
    assert len(config.warnings) == 1


def test_unreadable_file_gives_defaults_and_one_warning(tmp_path):
    # A directory raises OSError on read_bytes — the "unreadable" case,
    # distinct from "absent" (FileNotFoundError).
    config = TomlConfigSource(tmp_path).read_config()
    assert config.poll_seconds == 10
    assert len(config.warnings) == 1


def test_wrong_type_defaults_that_key_and_warns_others_still_apply(tmp_path):
    path = write_toml(tmp_path, 'poll_seconds = "thirty"\nstale_after_minutes = 5\n')
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert config.stale_after == timedelta(minutes=5)
    assert len(config.warnings) == 1
    assert "poll_seconds" in config.warnings[0]


def test_out_of_range_rejected_to_default_not_clamped(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 9999\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 10
    assert len(config.warnings) == 1


def test_unknown_keys_ignored_without_warning(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 20\nfuture_knob = true\n")
    config = TomlConfigSource(path).read_config()
    assert config.poll_seconds == 20
    assert config.warnings == ()


def test_refresh_timeout_valid_override(tmp_path):
    path = write_toml(tmp_path, "refresh_timeout_seconds = 120\n")
    config = TomlConfigSource(path).read_config()
    assert config.refresh_timeout_seconds == 120
    assert config.warnings == ()


def test_refresh_timeout_out_of_range_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, "refresh_timeout_seconds = 4\n")
    config = TomlConfigSource(path).read_config()
    assert config.refresh_timeout_seconds == 60
    assert len(config.warnings) == 1
    assert "refresh_timeout_seconds" in config.warnings[0]


def test_claude_executable_absent_is_none(tmp_path):
    path = write_toml(tmp_path, "poll_seconds = 20\n")
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert config.warnings == ()


def test_claude_executable_valid_string(tmp_path):
    path = write_toml(tmp_path, 'claude_executable = "/opt/claude/bin/claude"\n')
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable == "/opt/claude/bin/claude"
    assert config.warnings == ()


def test_claude_executable_wrong_type_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, "claude_executable = 7\n")
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert len(config.warnings) == 1
    assert "claude_executable" in config.warnings[0]


def test_claude_executable_empty_string_defaults_and_warns(tmp_path):
    path = write_toml(tmp_path, 'claude_executable = ""\n')
    config = TomlConfigSource(path).read_config()
    assert config.claude_executable is None
    assert len(config.warnings) == 1
