"""Where bundled files live (works both from source and from a PyInstaller build)."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def package_root() -> Path:
    """Folder that contains the orders_desk package files (qml/, resources/, engine/)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "orders_desk"
    return Path(__file__).resolve().parent


def resource(*parts: str) -> Path:
    return package_root().joinpath("resources", *parts)


def qml_dir() -> Path:
    return package_root() / "qml"
