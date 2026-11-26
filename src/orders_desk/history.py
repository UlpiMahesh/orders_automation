"""Run records. One folder per run, one run.json inside it (written atomically)."""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path

from .workspace import Workspace, atomic_write_json, read_json


def new_run_id(action: str) -> str:
    return f"{datetime.now():%Y%m%d_%H%M%S}_{action}_{uuid.uuid4().hex[:4]}"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class RunStore:
    def __init__(self, ws: Workspace):
        self.ws = ws

    def run_dir(self, market: str, run_id: str) -> Path:
        return self.ws.sub(market, "runs") / run_id

    def start(self, market: str, action: str, **details) -> dict:
        run_id = new_run_id(action)
        rd = self.run_dir(market, run_id)
        rd.mkdir(parents=True, exist_ok=True)
        rec = {
            "run_id": run_id, "market": market.upper(), "action": action,
            "status": "running", "started": datetime.now().isoformat(timespec="milliseconds"),
            "finished": None, "exit_code": None, "summary": "", "details": details,
            "outputs": [],
        }
        self.save(rec)
        return rec

    def save(self, rec: dict) -> None:
        atomic_write_json(self.run_dir(rec["market"], rec["run_id"]) / "run.json", rec)

    def finish(self, rec: dict, status: str, exit_code: int | None, summary: str,
               outputs: list[str] | None = None, extra: dict | None = None) -> dict:
        rec["status"] = status
        rec["finished"] = datetime.now().isoformat(timespec="milliseconds")
        rec["exit_code"] = exit_code
        rec["summary"] = summary
        if outputs is not None:
            rec["outputs"] = outputs
        if extra:
            rec["details"].update(extra)
        self.save(rec)
        return rec

    def all_runs(self, market: str | None = None, limit: int = 200) -> list[dict]:
        markets_dir = self.ws.markets_dir
        if not markets_dir.exists():
            return []
        dirs = [self.ws.market_dir(market)] if market else [p for p in markets_dir.iterdir() if p.is_dir()]
        out = []
        for d in dirs:
            runs = d / "runs"
            if not runs.exists():
                continue
            for rd in runs.iterdir():
                rec = read_json(rd / "run.json") if rd.is_dir() else None
                if rec:
                    out.append(rec)
        out.sort(key=lambda r: r.get("started", ""), reverse=True)
        return out[:limit]

    def mark_interrupted(self) -> int:
        """Runs left in 'running' by a crash / power cut are closed as 'interrupted'."""
        n = 0
        for rec in self.all_runs(limit=10_000):
            if rec.get("status") == "running":
                self.finish(rec, "interrupted", None, "The app closed before this run finished.")
                n += 1
        return n


_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str) -> str:
    return _SAFE.sub("_", name).strip(" .") or "file"
