"""GUI bootstrap."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import APP_NAME


def _setup_logging(logs_dir) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def build(argv):
    """Create the app, backend and QML engine. Returned separately so tests can drive them."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    from .backend import Backend
    from .paths import qml_dir

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OrdersDesk")
    backend = Backend()
    _setup_logging(backend.ws.logs_dir)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.addImportPath(str(qml_dir()))
    engine.load(QUrl.fromLocalFile(str(qml_dir() / "Main.qml")))
    return app, engine, backend


def run_gui(argv: list[str]) -> int:
    app, engine, backend = build([sys.argv[0], *argv])
    if not engine.rootObjects():
        logging.getLogger("orders_desk").error("The interface failed to load.")
        return 1
    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()
