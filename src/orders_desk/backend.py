"""Backend object exposed to the QML interface (properties, slots, signals)."""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Property, Signal, Slot

from . import APP_NAME, __version__
from . import files as fsx
from .history import RunStore, safe_name
from .logmodel import LogModel
from .markets import Market, load_markets
from .promptparse import parse_prompt
from .runner import TaskRunner
from .workspace import Workspace, remember_workspace_root, resolve_workspace_root

log = logging.getLogger("orders_desk")

ACTION_LABEL = {"convert": "Convert", "check": "Check", "verify": "Verify on portal", "live": "Place orders"}


def _to_path(value: str) -> str:
    if value.startswith("file:"):
        return QUrl(value).toLocalFile()
    return value


def _pretty_when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b  %H:%M")
    except ValueError:
        return iso


def _duration(rec: dict) -> str:
    try:
        a = datetime.fromisoformat(rec["started"])
        b = datetime.fromisoformat(rec["finished"])
        s = int((b - a).total_seconds())
        return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"
    except Exception:
        return ""


class Backend(QObject):
    busyChanged = Signal()
    marketChanged = Signal()
    marketsChanged = Signal()
    progressChanged = Signal()
    promptChanged = Signal()
    settingsChanged = Signal()
    resultChanged = Signal()
    toast = Signal(str, str)                # message, level (info | success | warning | error)
    taskFinished = Signal("QVariantMap")
    filesChanged = Signal()
    runsChanged = Signal()

    def __init__(self, workspace: Workspace | None = None, parent=None):
        super().__init__(parent)
        self._markets: dict[str, Market] = load_markets()
        self.ws = workspace or Workspace(resolve_workspace_root())
        self.ws.ensure([m for m in self._markets if self._markets[m].visible])
        self.settings = self.ws.load_settings()
        self.runs = RunStore(self.ws)
        self.runs.mark_interrupted()

        self._log = LogModel(self)
        self._runner = TaskRunner(self)
        self._runner.line.connect(self._on_line)
        self._runner.prompt.connect(self._on_prompt)
        self._runner.result.connect(self._on_result)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)

        self._busy = False
        self._task_label = ""
        self._task_market = ""
        self._task_action = ""
        self._progress = -1.0
        self._progress_text = ""
        self._prompt: dict = {}
        self._recent: list[str] = []
        self._last_error = ""
        self._current: dict | None = None
        self._result: dict = {}
        self._market = self.settings.last_market if self.settings.last_market in self._markets else self._first_market()
        self._overview: list[dict] = []
        self._rebuild_overview()

    # ================================================================= helpers
    def _first_market(self) -> str:
        for m in self._markets.values():
            if m.can_convert:
                return m.id
        return next(iter(self._markets), "")

    def _market_obj(self, name: str) -> Market:
        return self._markets[name.strip().upper()]

    def _save_settings(self) -> None:
        self.ws.save_settings(self.settings)
        self.settingsChanged.emit()

    # ================================================================= properties
    @Property(str, constant=True)
    def appName(self): return APP_NAME

    @Property(str, constant=True)
    def version(self): return __version__

    @Property(QObject, constant=True)
    def logModel(self): return self._log

    @Property(bool, notify=busyChanged)
    def busy(self): return self._busy

    @Property(str, notify=busyChanged)
    def taskLabel(self): return self._task_label

    @Property(str, notify=busyChanged)
    def taskMarket(self): return self._task_market

    @Property(str, notify=busyChanged)
    def taskAction(self): return self._task_action

    @Property(float, notify=progressChanged)
    def progress(self): return self._progress

    @Property(str, notify=progressChanged)
    def progressText(self): return self._progress_text

    @Property("QVariantMap", notify=promptChanged)
    def pendingPrompt(self): return self._prompt

    @Property("QVariantMap", notify=resultChanged)
    def lastResult(self): return self._result

    @Property(str, notify=marketChanged)
    def market(self): return self._market

    @Property("QVariantList", notify=marketsChanged)
    def markets(self): return self._overview

    @Property(str, notify=settingsChanged)
    def workspacePath(self): return str(self.ws.root)

    @Property(str, notify=settingsChanged)
    def credentialsPath(self): return self.settings.credentials_path

    @Property(bool, notify=settingsChanged)
    def credentialsOk(self):
        p = self.settings.credentials_path
        return bool(p) and Path(p).is_file()

    @Property(str, notify=settingsChanged)
    def browser(self): return self.settings.browser

    @Property(int, notify=settingsChanged)
    def debugKeepDays(self): return self.settings.debug_keep_days

    # ================================================================= market overview
    def _rebuild_overview(self) -> None:
        out = []
        for m in self._markets.values():
            if not m.visible:
                continue
            src = fsx.latest(self.ws, m.id, "raw")
            conv = fsx.latest(self.ws, m.id, "converted")
            runs = self.runs.all_runs(m.id, limit=60)
            last_conv = next((r for r in runs if r["action"] == "convert" and r["status"] == "success"), None)
            last_place = next((r for r in runs if r["action"] in ("live", "verify")), None)
            out.append({
                "id": m.id, "status": m.status, "canConvert": m.can_convert, "canPlace": m.can_place,
                "description": m.description,
                "sourceName": src.name if src else "", "sourcePath": str(src) if src else "",
                "convertedName": conv.name if conv else "", "convertedPath": str(conv) if conv else "",
                "convertedWhen": datetime.fromtimestamp(conv.stat().st_mtime).strftime("%d %b %H:%M") if conv else "",
                "orders": (last_conv or {}).get("details", {}).get("orders", 0),
                "devices": (last_conv or {}).get("details", {}).get("devices", 0),
                "lastPlaceStatus": (last_place or {}).get("status", ""),
                "lastPlaceAction": (last_place or {}).get("action", ""),
                "lastPlaceSummary": (last_place or {}).get("summary", ""),
                "lastPlaceWhen": _pretty_when((last_place or {}).get("started")),
            })
        self._overview = out
        self.marketsChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self._rebuild_overview()
        self.filesChanged.emit()
        self.runsChanged.emit()
        self.settingsChanged.emit()

    @Slot(str)
    def setMarket(self, market: str) -> None:
        market = market.strip().upper()
        if market in self._markets and market != self._market:
            self._market = market
            self.settings.last_market = market
            self.ws.save_settings(self.settings)
            self.marketChanged.emit()

    @Slot(result=str)
    def todayIso(self) -> str:
        return date.today().isoformat()

    # ================================================================= file pickers / lists
    @Slot(str, result="QVariantMap")
    def latestSource(self, market: str):
        p = fsx.latest(self.ws, market, "raw")
        return {"path": str(p), "name": p.name,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %H:%M")} if p else {}

    @Slot(str, result="QVariantList")
    def sourceList(self, market: str):
        return fsx.list_sub(self.ws, market, "raw")

    @Slot(str, result="QVariantList")
    def convertedList(self, market: str):
        return fsx.list_sub(self.ws, market, "converted", limit=15)

    @Slot(str, str, result="QVariantMap")
    def importSource(self, market: str, source: str):
        """Copy a picked / dropped workbook into the market's raw folder."""
        try:
            info = fsx.import_source(self.ws, market, Path(_to_path(source)))
            self._rebuild_overview()
            self.filesChanged.emit()
            return {"ok": True, **info}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ================================================================= task orchestration
    def _begin(self, market: str, action: str, label: str, args: list[str], details: dict,
               env_builder=None) -> bool:
        if self._busy:
            self.toast.emit("Another task is still running.", "warning")
            return False
        rec = self.runs.start(market, action, **details)
        run_dir = self.runs.run_dir(market, rec["run_id"])
        self._current = {"rec": rec, "run_dir": run_dir, "market": market, "action": action}
        self._log.clear()
        self._recent.clear()
        self._last_error = ""
        self._result = {}
        self.resultChanged.emit()
        self._set_progress(-1.0, "")
        self._prompt = {}
        self.promptChanged.emit()
        self._busy, self._task_label, self._task_market, self._task_action = True, label, market, action
        self.busyChanged.emit()
        self._log.append(f"{label}  ·  {market}", "head")
        self._log.append(f"Run folder: {run_dir}", "muted")
        try:
            env = env_builder(run_dir) if env_builder else {}
            self._runner.start(args, env, run_dir, run_dir / "run.log")
        except Exception as exc:
            self._log.append(f"Could not start the task: {exc}", "error")
            self._finish_run("failed", -1, f"Could not start: {exc}")
            return False
        return True

    def _set_progress(self, value: float, text: str) -> None:
        self._progress, self._progress_text = value, text
        self.progressChanged.emit()

    # ---- convert
    @Slot(str, str, str)
    def convertOrders(self, market: str, source: str, order_date: str) -> None:
        market = market.strip().upper()
        try:
            m = self._market_obj(market)
        except KeyError:
            self.toast.emit(f"Unknown market: {market}", "error"); return
        if not m.can_convert:
            self.toast.emit(f"{market} is not set up for conversion yet.", "warning"); return
        src = Path(_to_path(source)) if source else None
        if not src or not src.is_file():
            self.toast.emit("Choose or drop the market's source workbook first.", "warning"); return
        try:
            datetime.strptime(order_date, "%Y-%m-%d")
        except ValueError:
            self.toast.emit("Order date must look like 2026-11-24.", "warning"); return
        for need in (self.ws.devices_path, self.ws.market_details_path):
            if not need.is_file():
                self.toast.emit(f"Missing master file: {need.name}. Open Settings → Master data.", "error"); return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.ws.sub(market, "converted") / f"orders_standard_{stamp}.xlsx"
        out.parent.mkdir(parents=True, exist_ok=True)
        from .history import sha256_of
        details = {"source": str(src), "source_sha256": sha256_of(src), "order_date": order_date, "output": str(out)}
        args = ["convert", "--market", market, "--converter", m.converter or "", "--source", str(src),
                "--out", str(out), "--date", order_date,
                "--details", str(self.ws.market_details_path), "--devices", str(self.ws.devices_path)]
        self._begin(market, "convert", "Converting orders", args, details)

    # ---- check
    @Slot(str, str)
    def checkOrders(self, market: str, workbook: str) -> None:
        market = market.strip().upper()
        wb = Path(_to_path(workbook)) if workbook else None
        if not wb or not wb.is_file():
            self.toast.emit("There is no converted workbook to check yet. Convert orders first.", "warning"); return
        self._begin(market, "check", "Checking orders", ["check", "--workbook", str(wb), "--market", market],
                    {"workbook": str(wb)})

    # ---- place
    @Slot(str, str, str, int, str, str)
    def placeOrders(self, market: str, workbook: str, mode: str, limit: int, refs: str, confirm: str) -> None:
        market = market.strip().upper()
        mode = "live" if mode == "live" else "verify"
        try:
            m = self._market_obj(market)
        except KeyError:
            self.toast.emit(f"Unknown market: {market}", "error"); return
        if not m.can_place:
            self.toast.emit(f"{market} is not set up for placing orders.", "warning"); return
        wb = Path(_to_path(workbook)) if workbook else None
        if not wb or not wb.is_file():
            self.toast.emit("Choose a converted workbook first.", "warning"); return
        if not self.credentialsOk:
            self.toast.emit("Set the login file (marketlogins.xlsx) in Settings first.", "warning"); return
        if mode == "live" and confirm.strip().upper() != market:
            self.toast.emit("Live placement needs the market name typed to confirm.", "error"); return
        ref_list = [r.strip() for r in refs.replace(",", " ").split() if r.strip()]
        args = ["place", "--workbook", str(wb), "--market", market, "--mode", mode,
                "--logins", self.settings.credentials_path, "--login-market", m.login_market]
        if limit and limit > 0:
            args += ["--limit", str(limit)]
        for r in ref_list:
            args += ["--ref", r]
        label = "Placing orders (LIVE)" if mode == "live" else "Verifying orders on the portal"
        details = {"workbook": str(wb), "limit": limit, "refs": ref_list, "mode": mode}

        def engine_env(run_dir: Path) -> dict:
            # the engine writes its log, results workbook and confirmations into this run's folder
            return {
                "ORDERS_AUTOMATION_RUNTIME_DIR": str(run_dir),
                "ORDERS_AUTOMATION_LOG_DIR": str(run_dir),
                "ORDERS_AUTOMATION_LOGINS": self.settings.credentials_path,
                "ORDERS_AUTOMATION_BROWSER": self.settings.browser,
            }

        self._begin(market, mode, label, args, details, env_builder=engine_env)

    # ---- operator prompts
    def _on_line(self, text: str, level: str) -> None:
        self._log.append(text, level)
        if level in ("error", "critical") or text.startswith("ERROR"):
            self._last_error = text.split("|")[-1].strip()[:200]
        self._recent.append(text)
        if len(self._recent) > 60:
            del self._recent[:20]

    def _on_prompt(self, payload: dict) -> None:
        parsed = parse_prompt(str(payload.get("prompt", "")), list(self._recent))
        parsed["id"] = int(payload.get("id", 0))
        parsed["live"] = self._task_action == "live"
        parsed["market"] = self._task_market
        self._prompt = parsed
        self.promptChanged.emit()
        self._set_progress(self._progress, "Waiting for your decision")

    @Slot(str)
    def answerPrompt(self, text: str) -> None:
        shown = text if text else "Enter"
        self._log.append(f"▸ You chose: {shown}", "you")
        self._recent.clear()
        self._prompt = {}
        self.promptChanged.emit()
        self._runner.answer(text)
        if text.lower() == "s":
            self._runner.mark_stop_requested()

    @Slot()
    def stopTask(self) -> None:
        if self._busy:
            self._log.append("Stopping…", "warning")
            self._runner.stop()

    def _on_progress(self, cur: int, total: int) -> None:
        if total:
            self._set_progress(max(0.0, (cur - 1) / total), f"Order {cur} of {total}")

    def _on_result(self, data: dict) -> None:
        self._result = data
        self.resultChanged.emit()

    # ---- completion
    def _on_finished(self, code: int, status: str) -> None:
        action = self._task_action
        summary, outputs = "", []
        run_dir = self._current["run_dir"] if self._current else None
        res = self._result or {}
        if action == "convert":
            if status == "success" and res.get("output"):
                outputs = [res["output"]]
                summary = f"{res.get('orders', 0)} orders · {res.get('lines', 0)} lines · {res.get('devices', 0)} devices"
            else:
                summary = "Conversion did not complete" if status != "stopped" else "Stopped"
        elif action == "check":
            summary = (f"{len(res.get('orders', []))} ready · {len(res.get('rejected', []))} rejected"
                       if res else "Check did not complete")
        elif action in ("verify", "live"):
            summary, outputs = self._summarise_place(run_dir)
            if status == "stopped" and not summary:
                summary = "Stopped"
        if status == "failed" and (not summary or summary.endswith("did not complete")) and self._last_error:
            summary = self._last_error
        extra = {k: res.get(k) for k in ("orders", "lines", "devices", "checks") if k in res} if action == "convert" else None
        self._finish_run(status, code, summary, outputs, extra)

    def _summarise_place(self, run_dir: Path | None) -> tuple[str, list[str]]:
        if not run_dir:
            return "", []
        import openpyxl
        from collections import Counter
        outputs, counts = [], Counter()
        for f in sorted(run_dir.glob("place_orders_results_*.xlsx")):
            outputs.append(str(f))
            try:
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                for row in list(wb.active.iter_rows(min_row=2, values_only=True)):
                    if row and row[2]:
                        counts[str(row[2])] += 1
                wb.close()
            except Exception:
                pass
        outputs += [str(f) for f in sorted(run_dir.glob("*.log"))]
        text = " · ".join(f"{v} {k.title()}" for k, v in counts.most_common())
        return text, outputs

    def _finish_run(self, status: str, code: int, summary: str, outputs: list[str] | None = None,
                    extra: dict | None = None) -> None:
        cur = self._current
        if cur:
            self.runs.finish(cur["rec"], status, code, summary, outputs, extra)
        self._busy = False
        self._set_progress(-1.0, "")
        self._prompt = {}
        self.promptChanged.emit()
        self.busyChanged.emit()
        level = {"success": "success", "stopped": "warning"}.get(status, "error")
        label = {"success": "Finished", "stopped": "Stopped", "failed": "Failed"}.get(status, status)
        self._log.append(f"{label}. {summary}".strip(), level)
        self.toast.emit(f"{self._task_label}: {label.lower()}" + (f" — {summary}" if summary else ""), level)
        self._rebuild_overview()
        self.filesChanged.emit()
        self.runsChanged.emit()
        self.taskFinished.emit({"status": status, "action": self._task_action, "market": self._task_market,
                                "summary": summary, "result": self._result})
        self._current = None

    # ================================================================= files screen
    @Slot(str, str, str, result="QVariantList")
    def listFiles(self, market: str, category: str, query: str):
        return fsx.list_files(self.ws, market, category, query)

    @Slot(str, result="QVariantMap")
    def previewFile(self, path: str):
        p = Path(path)
        if not p.is_file():
            return {"kind": "none"}
        ext = p.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg"):
            return {"kind": "image", "url": QUrl.fromLocalFile(str(p)).toString()}
        if ext in (".txt", ".log", ".json", ".csv", ".html", ".md"):
            return {"kind": "text", "text": fsx.read_text_preview(p)}
        return {"kind": "binary", "text": "This file type opens in its own app (for example Excel)."}

    @Slot(str, result=bool)
    def openPath(self, path: str): return fsx.open_path(_to_path(path))

    @Slot(str, result=bool)
    def revealPath(self, path: str): return fsx.reveal_path(_to_path(path))

    @Slot()
    def openWorkspace(self) -> None:
        fsx.reveal_path(self.ws.root)

    @Slot(str)
    def openMarketFolder(self, market: str) -> None:
        fsx.reveal_path(self.ws.market_dir(market))

    @Slot(str, result="QVariantList")
    def listRuns(self, market: str):
        out = []
        for r in self.runs.all_runs(market or None, limit=150):
            action = r.get("action", "")
            out.append({
                "runId": r["run_id"], "market": r["market"], "action": action,
                "actionLabel": ACTION_LABEL.get(action, action.title()),
                "status": r.get("status", ""), "when": _pretty_when(r.get("started")),
                "duration": _duration(r), "summary": r.get("summary", ""),
                "dir": str(self.runs.run_dir(r["market"], r["run_id"])),
            })
        return out

    @Slot(str, str, result=str)
    def readRunLog(self, market: str, run_id: str) -> str:
        p = self.runs.run_dir(market, run_id) / "run.log"
        return fsx.read_text_preview(p, 200_000) if p.is_file() else "(no log was written)"

    # ================================================================= settings
    @Slot(str)
    def setCredentials(self, path: str) -> None:
        p = Path(_to_path(path))
        if not p.is_file() or p.suffix.lower() not in (".xlsx", ".xlsm"):
            self.toast.emit("Please choose the marketlogins.xlsx workbook.", "warning"); return
        self.settings.credentials_path = str(p)
        self._save_settings()
        self.toast.emit("Login file saved. It stays where it is — it is never copied.", "success")

    @Slot(str)
    def setBrowser(self, browser: str) -> None:
        if browser in ("auto", "chromium", "msedge", "chrome"):
            self.settings.browser = browser
            self._save_settings()

    @Slot(int)
    def setDebugKeepDays(self, days: int) -> None:
        self.settings.debug_keep_days = max(1, min(365, days))
        self._save_settings()

    @Slot(str)
    def setWorkspace(self, path: str) -> None:
        if self._busy:
            self.toast.emit("Wait for the running task to finish first.", "warning"); return
        new_root = Path(_to_path(path))
        ws = Workspace(new_root)
        if not ws.is_writable():
            self.toast.emit("That folder is not writable. Choose another one.", "error"); return
        ws.ensure([m for m in self._markets if self._markets[m].visible])
        remember_workspace_root(new_root)
        self.ws = ws
        self.settings = ws.load_settings()
        self.runs = RunStore(ws)
        self._rebuild_overview()
        self.settingsChanged.emit(); self.filesChanged.emit(); self.runsChanged.emit()
        self.toast.emit(f"Workspace is now {new_root}. Existing files were not moved.", "success")

    @Slot(result=str)
    def purgeDebug(self) -> str:
        n, freed = fsx.purge_debug(self.ws, self.settings.debug_keep_days)
        self.filesChanged.emit()
        msg = f"Removed {n} debug file(s), freed {fsx.human_size(freed)}."
        self.toast.emit(msg, "success")
        return msg

    @Slot(str)
    def openMaster(self, which: str) -> None:
        path = self.ws.devices_path if which == "devices" else self.ws.market_details_path
        fsx.open_path(path)

    @Slot(str, str)
    def replaceMaster(self, which: str, source: str) -> None:
        import shutil
        src = Path(_to_path(source))
        target = self.ws.devices_path if which == "devices" else self.ws.market_details_path
        if not src.is_file() or src.suffix.lower() != ".xlsx":
            self.toast.emit("Choose an Excel (.xlsx) file.", "warning"); return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if target.exists():                       # keep the previous version, never overwrite blindly
            backup = self.ws.masters_dir / "previous"
            backup.mkdir(exist_ok=True)
            shutil.copy2(target, backup / f"{target.stem}__{stamp}{target.suffix}")
        shutil.copy2(src, target)
        self.toast.emit(f"{target.name} updated (previous version kept in masters/previous).", "success")

    @Slot()
    def shutdown(self) -> None:
        if self._busy:
            self._runner.stop()
