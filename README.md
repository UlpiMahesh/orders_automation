# Orders Desk

Desktop app (Windows) to **convert**, **check** and **place** dealer orders with one button per step.
Built with Python + PySide6 (Qt Quick) + Playwright. Your existing converters and the portal
automation (`place_orders.py`) are used unchanged, apart from two small patches (see "What changed").

## For teammates (no technical setup)
1. Unzip `OrdersDesk-Setup-x.y.z.zip`, run `OrdersDesk-Setup-x.y.z.exe` (installs for your user, no admin rights).
   Windows may say "protected your PC" because the installer is unsigned: **More info -> Run anyway**.
2. Open Orders Desk -> **Settings** -> choose your `marketlogins.xlsx` (it is never copied).
3. Convert -> Check -> Place.

All output goes to `Documents\OrdersDesk` (change it in Settings). Uninstalling does not delete it.

## Workspace layout (outside the program)
```
Documents\OrdersDesk\
  config\settings.json
  masters\Devices.xlsx, MarketDetails.xlsx      (editable; replaced versions kept in masters\previous)
  markets\<MARKET>\raw\          imported source workbooks (timestamped copies, deduplicated by content)
  markets\<MARKET>\converted\    orders_standard_<timestamp>.xlsx
  markets\<MARKET>\runs\<id>\    run.json, run.log, results workbook, confirmations (.txt/.png), debug dumps
  logs\app.log
```

## Build the installer
**Free, no Windows PC needed:** push this folder to GitHub, then tag a version (`git tag v1.0.0 && git push --tags`)
or run the *Build Windows installer* workflow by hand. Download the ZIPs from the run's Artifacts
(`OrdersDesk-Setup-*.zip`, `OrdersDesk-Portable-*.zip`). Share the ZIP - WhatsApp refuses raw `.exe` files.

**On a Windows PC:** install Python 3.11+ and Inno Setup 6, then `.\packaging\build_windows.ps1`.

## Run from source (developers)
```
py -3 -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m orders_desk            # app
python -m pytest                 # tests
```
Set `ORDERS_DESK_HOME` to use another workspace folder while developing.

## Architecture
- `orders_desk/backend.py` - everything the UI can do (slots); `qml/` - the interface only.
- Each task runs in a separate **worker process** (`worker.py`): a stuck browser can't freeze the window and Stop is real.
- The engine's terminal questions (`input()`) are intercepted and shown as dialogs (`promptparse.py`).
- `engine/` - original converters and `place_orders.py`.
- Every run gets its own folder + `run.json` (inputs, SHA-256 of the source file, status, outputs).

## What changed in the engine
1. `place_orders.py` writes logs/results/confirmations to the run folder (`ORDERS_AUTOMATION_LOG_DIR`).
2. Browser launch falls back to Edge, then Chrome, when Playwright's Chromium isn't installed.
Converters now write to `*.partial` and are renamed only on success.

## Known limits
- Windows installer and real-portal runs could not be exercised in the authoring environment.
- `marketlogins.xlsx` holds plain-text passwords; keep it off shared drives and out of git.
- HOUSTON, LAREDO, RGV, SA have no converter yet (shown as "soon").
