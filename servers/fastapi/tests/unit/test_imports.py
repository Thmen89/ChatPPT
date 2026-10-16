"""Every backend module imports cleanly.

Unit tests mock most collaborators, so a broken import (a removed re-export, a typo'd
name) can hide until the server starts. This walks the packages and imports each module.
"""

import importlib
import pkgutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ["api", "chatppt", "constants", "enums", "models", "services", "templates", "utils"]


def _modules() -> list[str]:
    names = []
    for package in PACKAGES:
        names.append(package)
        for info in pkgutil.walk_packages([str(ROOT / package)], prefix=f"{package}."):
            names.append(info.name)
    return sorted(names)


@pytest.mark.parametrize("name", _modules())
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


def test_server_entrypoint_imports() -> None:
    importlib.import_module("server")
