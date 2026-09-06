"""Encodes the spec's greppable import discipline (POC spec §4)."""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "claude_usage"

FORBIDDEN_REFS = {
    "domain": [
        "claude_usage.application",
        "claude_usage.infrastructure",
        "claude_usage.ui",
        "import wx",
        "import subprocess",
        "from subprocess",
        "import shutil",
        "from shutil",
    ],
    "application": [
        "claude_usage.infrastructure",
        "claude_usage.ui",
        "import wx",
        "import subprocess",
        "from subprocess",
        "import shutil",
        "from shutil",
    ],
    "infrastructure": ["claude_usage.ui", "import wx"],
}

IO_IMPORT = re.compile(r"^(from|import) (json|pathlib|argparse|os|sys)\b", re.M)


def layer_files(layer):
    files = list((PKG / layer).rglob("*.py"))
    assert files, f"no files found under claude_usage/{layer}"
    return files


def test_inward_only_imports():
    for layer, banned in FORBIDDEN_REFS.items():
        for path in layer_files(layer):
            text = path.read_text(encoding="utf-8")
            for needle in banned:
                assert needle not in text, f"{path} references {needle}"


def test_domain_has_no_io_imports():
    for path in layer_files("domain"):
        match = IO_IMPORT.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path} imports {match.group(2)}"
