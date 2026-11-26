"""File catalogue for the Files screen: lists, classifies, previews and tidies workspace files."""
from __future__ import annotations

import os
import re
import shutil
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .history import safe_name, sha256_of
from .workspace import Workspace

CATEGORIES = ("Source", "Converted", "Results", "Confirmations", "Logs", "Debug")

_DEBUG_RE = re.compile(r"(_frame\d+\.html$)|(_try\d+.*\.(png|html)$)|(^LOGIN_)", re.I)


def classify(path: Path, market_dir: Path) -> str:
    rel = path.relative_to(market_dir).parts
    top = rel[0] if rel else ""
    name = path.name
    if top == "raw":
        return "Source"
    if top == "converted":
        return "Converted"
    if top == "archive":
        return "Source"
    if top == "runs":
        if name.startswith("place_orders_results_") and name.endswith(".xlsx"):
            return "Results"
        if name.endswith(".log"):
            return "Logs"
        if _DEBUG_RE.search(name):
            return "Debug"
        if "order_confirmation" in name:
            return "Confirmations"
        if name == "run.json":
            return "Logs"
        if name.endswith((".png", ".html")):
            return "Debug"
        if name.endswith((".txt",)):
            return "Confirmations"
    return "Logs"


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def list_files(ws: Workspace, market: str = "", category: str = "", query: str = "",
               limit: int = 400) -> list[dict]:
    markets = [market.upper()] if market else [p.name for p in sorted(ws.markets_dir.glob("*")) if p.is_dir()]
    q = query.strip().lower()
    rows: list[dict] = []
    for m in markets:
        base = ws.market_dir(m)
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.name.startswith(("~$", ".")) or p.name == "run.json":
                continue
            cat = classify(p, base)
            if category and cat != category:
                continue
            if q and q not in p.name.lower() and q not in m.lower():
                continue
            st = p.stat()
            rows.append({
                "path": str(p), "name": p.name, "market": m, "category": cat,
                "size": human_size(st.st_size), "bytes": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "mtime": st.st_mtime, "ext": p.suffix.lower().lstrip("."),
            })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


def latest(ws: Workspace, market: str, sub: str, pattern: str = "*.xlsx") -> Path | None:
    d = ws.sub(market, sub)
    if not d.exists():
        return None
    cands = [p for p in d.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def list_sub(ws: Workspace, market: str, sub: str, pattern: str = "*.xlsx", limit: int = 12) -> list[dict]:
    d = ws.sub(market, sub)
    if not d.exists():
        return []
    cands = [p for p in d.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"path": str(p), "name": p.name,
             "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %H:%M"),
             "size": human_size(p.stat().st_size)} for p in cands[:limit]]


def import_source(ws: Workspace, market: str, src: Path) -> dict:
    """Copy a user-chosen workbook into <market>/raw with a timestamp. The original is untouched."""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if src.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("Please choose an Excel workbook (.xlsx).")
    raw = ws.sub(market, "raw")
    raw.mkdir(parents=True, exist_ok=True)
    digest = sha256_of(src)
    for existing in raw.glob("*.xlsx"):             # identical content already imported? reuse it
        if existing.stat().st_size == src.stat().st_size and sha256_of(existing) == digest:
            return {"path": str(existing), "name": existing.name, "sha256": digest, "reused": True}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = raw / f"{safe_name(src.stem)}__{stamp}{src.suffix.lower()}"
    shutil.copy2(src, target)
    return {"path": str(target), "name": target.name, "sha256": digest, "reused": False}


def read_text_preview(path: Path, max_bytes: int = 60_000) -> str:
    with Path(path).open("rb") as fh:
        data = fh.read(max_bytes + 1)
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return text + ("\n\n... (preview truncated)" if len(data) > max_bytes else "")


def open_path(path: str | Path) -> bool:
    p = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
        return True
    except Exception:
        return False


def reveal_path(path: str | Path) -> bool:
    p = Path(path)
    try:
        if sys.platform == "win32":
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
        return True
    except Exception:
        return False


def purge_debug(ws: Workspace, older_than_days: int) -> tuple[int, int]:
    """Delete debug dumps (frame HTML, try-N screenshots) older than N days. Returns (files, bytes).
    Order confirmations, results and logs are business records and are never touched."""
    cutoff = time.time() - older_than_days * 86400
    count = freed = 0
    for m in [p for p in ws.markets_dir.glob("*") if p.is_dir()]:
        for f in list_files(ws, m.name, "Debug", limit=100_000):
            if f["mtime"] < cutoff:
                try:
                    Path(f["path"]).unlink()
                    count += 1
                    freed += f["bytes"]
                except OSError:
                    pass
    return count, freed
