"""Market catalogue (which markets exist and how each one is converted)."""
from __future__ import annotations

from dataclasses import dataclass

from .paths import resource
from .workspace import read_json


@dataclass(frozen=True)
class Market:
    id: str
    status: str                 # active | not_configured | included_in_dallas_workbook
    converter: str | None       # standard | dallas | None
    description: str
    login_market: str           # name used to look the login up in marketlogins.xlsx
    aliases: tuple = ()

    @property
    def can_convert(self) -> bool:
        return self.status == "active" and bool(self.converter)

    @property
    def can_place(self) -> bool:
        return self.status == "active"

    @property
    def visible(self) -> bool:
        # LUFKIN is processed inside the Dallas workbook - no tile of its own
        return self.status != "included_in_dallas_workbook"


def load_markets() -> dict[str, Market]:
    raw = read_json(resource("config", "markets.json"), {}) or {}
    out: dict[str, Market] = {}
    for key, cfg in raw.items():
        out[key] = Market(
            id=key,
            status=cfg.get("status", "not_configured"),
            converter=cfg.get("converter"),
            description=cfg.get("description", ""),
            login_market=str(cfg.get("login_market") or key).upper(),
            aliases=tuple(str(a).upper() for a in cfg.get("aliases", [])),
        )
    return out


def resolve(markets: dict[str, Market], name: str) -> Market:
    wanted = name.strip().upper()
    if wanted in markets:
        return markets[wanted]
    for m in markets.values():
        if wanted in m.aliases:
            return m
    raise KeyError(f"Unknown market: {name}")
