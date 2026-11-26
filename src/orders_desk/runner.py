"""Runs one worker process at a time and streams its output to the GUI.

Uses plain subprocess + a reader thread (rather than QProcess) so behaviour is identical on
every OS, stdin answers are simple writes, and a console-less window is a single flag.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .paths import is_frozen, package_root
from .worker import PROMPT, RESULT

_LEVEL = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|")
_PROGRESS = re.compile(r"order (\d+) of (\d+) for")


def worker_command() -> list[str]:
    if is_frozen():
        name = "OrdersDeskWorker.exe" if sys.platform == "win32" else "OrdersDeskWorker"
        return [str(Path(sys.executable).with_name(name))]
    return [sys.executable, "-u", "-m", "orders_desk", "--worker"]


def bundled_browser_env() -> dict[str, str]:
    """If the installer shipped Playwright's Chromium (inside the app folder), point Playwright at it."""
    if not is_frozen():
        return {}
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for cand in (base / "playwright" / "driver" / "package" / ".local-browsers",):
        if cand.is_dir() and any(cand.glob("chromium*")):
            return {"PLAYWRIGHT_BROWSERS_PATH": "0"}
    return {}


def classify(text: str) -> str:
    m = _LEVEL.search(text)
    if m:
        return m.group(1).lower()
    up = text.lstrip().upper()
    if up.startswith(("ERROR", "TRACEBACK", "CRITICAL")):
        return "error"
    if up.startswith(("WARNING", "[FRACTION", "[NO ALLOC")):
        return "warning"
    if up.startswith(("DONE", "SUCCESS")):
        return "success"
    return "info"


class TaskRunner(QObject):
    line = Signal(str, str)            # text, level
    prompt = Signal("QVariantMap")     # {"id", "prompt"}
    result = Signal("QVariantMap")
    progress = Signal(int, int)        # current, total
    finished = Signal(int, str)        # exit code, status: success | failed | stopped

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._log = None
        self._stop_requested = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------ control
    def start(self, args: list[str], env_extra: dict[str, str], cwd: Path, log_path: Path) -> None:
        if self.running:
            raise RuntimeError("A task is already running.")
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        env.update(bundled_browser_env())
        env.update(env_extra)
        if not is_frozen():
            env["PYTHONPATH"] = str(package_root().parent) + os.pathsep + env.get("PYTHONPATH", "")
        flags = 0
        kwargs: dict = {}
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        cwd.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("a", encoding="utf-8", newline="\n")
        self._stop_requested = False
        self._proc = subprocess.Popen(
            worker_command() + args, cwd=str(cwd), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, creationflags=flags, **kwargs,
        )
        self._thread = threading.Thread(target=self._pump, args=(self._proc,), daemon=True)
        self._thread.start()

    def answer(self, text: str) -> None:
        proc = self._proc
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write((text + "\n").encode("utf-8"))
                proc.stdin.flush()
            except OSError:
                pass

    def stop(self) -> None:
        """Hard stop: closes the worker and everything it started (browser included)."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        self._stop_requested = True
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def mark_stop_requested(self) -> None:
        self._stop_requested = True

    # ------------------------------------------------------------------ reader thread
    def _write_log(self, text: str) -> None:
        if self._log:
            try:
                self._log.write(text + "\n")
                self._log.flush()
            except Exception:
                pass

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if text.startswith(PROMPT):
                    try:
                        payload = json.loads(text[len(PROMPT):])
                    except ValueError:
                        payload = {"id": 0, "prompt": ""}
                    self._write_log(f"[prompt] {payload.get('prompt', '').strip()}")
                    self.prompt.emit(payload)
                    continue
                if text.startswith(RESULT):
                    try:
                        self.result.emit(json.loads(text[len(RESULT):]))
                    except ValueError:
                        pass
                    continue
                self._write_log(text)
                m = _PROGRESS.search(text)
                if m:
                    self.progress.emit(int(m.group(1)), int(m.group(2)))
                self.line.emit(text, classify(text))
        finally:
            code = proc.wait()
            if self._log:
                try:
                    self._log.close()
                except Exception:
                    pass
                self._log = None
            status = "stopped" if self._stop_requested else ("success" if code == 0 else "failed")
            self.finished.emit(code, status)
