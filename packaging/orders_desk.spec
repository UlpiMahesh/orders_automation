# PyInstaller spec: one folder containing the windowed app and its console worker.
# Build:  pyinstaller packaging/orders_desk.spec --noconfirm --clean
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
pkg_datas = [
    (str(SRC / "orders_desk" / "qml"), "orders_desk/qml"),
    (str(SRC / "orders_desk" / "resources"), "orders_desk/resources"),
]
pw_datas, pw_bins, pw_hidden = collect_all("playwright")      # ships the Playwright driver
hidden = pw_hidden + [
    "orders_desk.engine.converters.standard_converter",
    "orders_desk.engine.converters.dallas_converter",
    "orders_desk.engine.placement.place_orders",
    "openpyxl",
]
common = dict(pathex=[str(SRC)], datas=pkg_datas + pw_datas, binaries=pw_bins, hiddenimports=hidden,
              excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"], noarchive=False)

gui = Analysis([str(ROOT / "packaging" / "launch_gui.py")], **common)
worker = Analysis([str(ROOT / "packaging" / "launch_worker.py")], **common)
MERGE((gui, "launch_gui", "OrdersDesk"), (worker, "launch_worker", "OrdersDeskWorker"))

icon = str(ROOT / "packaging" / "app.ico")
icon = icon if Path(icon).exists() else None

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="OrdersDesk",
              console=False, icon=icon)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True, name="OrdersDeskWorker",
                 console=True, icon=icon)
COLLECT(gui_exe, gui.binaries, gui.datas, worker_exe, worker.binaries, worker.datas,
        strip=False, upx=False, name="OrdersDesk")
