"""The workspace: ONE folder, outside the program, that holds every file the app produces.

    <workspace>/
        config/settings.json          app settings for this PC
        masters/                      Devices.xlsx, MarketDetails.xlsx (editable master data)
        markets/<MARKET>/
            raw/                      source workbooks (copied in, never modified)
            converted/                orders_standard_<stamp>.xlsx
            runs/<run_id>/            one folder per run: run.json, run.log, results, confirmations
            archive/                  anything the user moves out of the way
        logs/app.log                  application log (rotating)

Nothing is ever written next to the program files, so the installed app (or a shared
project folder) stays small and read-only. All writes that replace a file are atomic.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import APP_ID
from .paths import resource

SUBDIRS = ("raw", "converted", "runs", "archive")


# ----------------------------------------------------------------- atomic file helpers
def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same folder, then replace - never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ----------------------------------------------------------------- where the workspace is
def app_config_dir() -> Path:
    """Tiny per-user pointer file (which workspace folder to use). Never holds business data."""
    override = os.environ.get("ORDERS_DESK_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    return Path.home() / ".config" / APP_ID


def default_workspace() -> Path:
    override = os.environ.get("ORDERS_DESK_HOME")
    if override:
        return Path(override)
    return Path.home() / "Documents" / "OrdersDesk"


def resolve_workspace_root() -> Path:
    pointer = read_json(app_config_dir() / "app.json", {}) or {}
    chosen = pointer.get("workspace")
    return Path(chosen) if chosen else default_workspace()


def remember_workspace_root(root: Path) -> None:
    atomic_write_json(app_config_dir() / "app.json", {"workspace": str(root)})


# ----------------------------------------------------------------- settings
@dataclass
class Settings:
    credentials_path: str = ""          # marketlogins.xlsx - stays where the user keeps it
    browser: str = "auto"               # auto | chromium | msedge | chrome
    debug_keep_days: int = 30           # debug dumps older than this can be purged
    last_market: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: d[k] for k in ("credentials_path", "browser", "debug_keep_days", "last_market") if k in d}
        s = cls(**known)
        s.extra = {k: v for k, v in d.items() if k not in known and k != "extra"}
        return s

    def to_dict(self) -> dict:
        d = asdict(self)
        extra = d.pop("extra", {})
        d.update(extra)
        return d


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ---- folders
    @property
    def config_dir(self) -> Path: return self.root / "config"
    @property
    def masters_dir(self) -> Path: return self.root / "masters"
    @property
    def markets_dir(self) -> Path: return self.root / "markets"
    @property
    def logs_dir(self) -> Path: return self.root / "logs"
    @property
    def settings_path(self) -> Path: return self.config_dir / "settings.json"
    @property
    def devices_path(self) -> Path: return self.masters_dir / "Devices.xlsx"
    @property
    def market_details_path(self) -> Path: return self.masters_dir / "MarketDetails.xlsx"

    def market_dir(self, market: str) -> Path:
        return self.markets_dir / market.strip().upper()

    def sub(self, market: str, name: str) -> Path:
        if name not in SUBDIRS:
            raise ValueError(f"unknown market subfolder: {name}")
        return self.market_dir(market) / name

    # ---- lifecycle
    def ensure(self, markets: list[str] | None = None) -> None:
        for d in (self.config_dir, self.masters_dir, self.logs_dir, self.markets_dir):
            d.mkdir(parents=True, exist_ok=True)
        for m in markets or []:
            for name in SUBDIRS:
                self.sub(m, name).mkdir(parents=True, exist_ok=True)
        # seed master data once; never overwrite what the user has edited
        for name in ("Devices.xlsx", "MarketDetails.xlsx"):
            target = self.masters_dir / name
            seed = resource("masters", name)
            if not target.exists() and seed.exists():
                shutil.copy2(seed, target)
        if not self.settings_path.exists():
            self.save_settings(Settings())

    def load_settings(self) -> Settings:
        return Settings.from_dict(read_json(self.settings_path, {}) or {})

    def save_settings(self, s: Settings) -> None:
        atomic_write_json(self.settings_path, s.to_dict())

    def is_writable(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return True
        except OSError:
            return False
