import sys
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from orders_desk.runner import TaskRunner


def test_prompt_roundtrip_and_result(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    r = TaskRunner()
    seen = {"prompts": [], "result": None, "done": None}
    r.prompt.connect(lambda p: (seen["prompts"].append(p["id"]), r.answer("k" if p["id"] == 1 else "y")))
    r.result.connect(lambda d: seen.update(result=d))
    r.finished.connect(lambda c, s: (seen.update(done=(c, s)), app.quit()))
    r.start(["selftest"], {}, tmp_path / "run", tmp_path / "run" / "run.log")
    QTimer.singleShot(30000, app.quit)
    app.exec()
    assert seen["done"] == (0, "success")
    assert seen["result"]["answers"] == ["k", "y"]
    assert "you answered 'k'" in (tmp_path / "run" / "run.log").read_text()


def test_stop_kills_worker(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    r = TaskRunner()
    done = {}
    r.prompt.connect(lambda p: QTimer.singleShot(200, r.stop))   # worker is blocked waiting for an answer
    r.finished.connect(lambda c, s: (done.update(s=s), app.quit()))
    r.start(["selftest"], {}, tmp_path / "run", tmp_path / "run" / "run.log")
    QTimer.singleShot(30000, app.quit)
    app.exec()
    assert done["s"] == "stopped"
