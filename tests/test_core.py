import json, time
from pathlib import Path
import openpyxl
import pytest

from orders_desk.workspace import Workspace, atomic_write_json, Settings
from orders_desk.history import RunStore, safe_name
from orders_desk import files as fsx
from orders_desk.promptparse import parse_prompt
from orders_desk.markets import load_markets


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.ensure(["WACO", "DALLAS"])
    return w


def test_workspace_seeds_masters_and_never_overwrites(ws):
    assert ws.devices_path.is_file() and ws.market_details_path.is_file()
    ws.devices_path.write_bytes(b"edited")
    ws.ensure(["WACO"])
    assert ws.devices_path.read_bytes() == b"edited"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "a" / "x.json"
    atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_settings_roundtrip_keeps_unknown_keys(ws):
    ws.settings_path.write_text(json.dumps({"browser": "chrome", "future_key": 5}))
    s = ws.load_settings()
    assert s.browser == "chrome"
    ws.save_settings(s)
    assert json.loads(ws.settings_path.read_text())["future_key"] == 5


def test_run_lifecycle_and_interrupted_cleanup(ws):
    store = RunStore(ws)
    rec = store.start("WACO", "convert", x=1)
    assert store.all_runs("WACO")[0]["status"] == "running"
    assert store.mark_interrupted() == 1
    assert store.all_runs("WACO")[0]["status"] == "interrupted"
    rec2 = store.start("WACO", "check")
    store.finish(rec2, "success", 0, "ok")
    assert store.all_runs()[0]["status"] == "success"


def _xlsx(path):
    wb = openpyxl.Workbook(); wb.active.append(["a"]); wb.save(path)


def test_import_source_copies_dedupes_and_rejects(ws, tmp_path):
    src = tmp_path / "Phone Order (17-NOV).xlsx"
    _xlsx(src)
    a = fsx.import_source(ws, "WACO", src)
    assert Path(a["path"]).parent == ws.sub("WACO", "raw") and src.exists()
    b = fsx.import_source(ws, "WACO", src)
    assert b["reused"] and b["path"] == a["path"]
    with pytest.raises(ValueError):
        bad = tmp_path / "x.txt"; bad.write_text("x"); fsx.import_source(ws, "WACO", bad)


def test_file_classification_and_debug_purge(ws):
    rd = ws.sub("WACO", "runs") / "r1"; rd.mkdir(parents=True)
    names = {"place_orders_results_1.xlsx": "Results", "WACO_X_order_confirmation_1.png": "Confirmations",
             "place_orders_1.log": "Logs", "SHER_re_check_try1_frame3.html": "Debug"}
    for n in names:
        (rd / n).write_text("x")
    got = {f["name"]: f["category"] for f in fsx.list_files(ws, "WACO")}
    assert got == names
    old = time.time() - 90 * 86400
    import os
    for f in rd.iterdir():
        os.utime(f, (old, old))
    n, _ = fsx.purge_debug(ws, 30)
    assert n == 1 and (rd / "place_orders_results_1.xlsx").exists()


def test_safe_name():
    assert "/" not in safe_name("a/b:c*d.xlsx")


def test_markets_catalogue():
    m = load_markets()
    assert m["DALLAS"].can_convert and not m["SA"].can_convert and not m["LUFKIN"].visible


def _keys(r): return [o["key"] for o in r["options"]]


def test_prompt_menu_buttons():
    r = parse_prompt("Your choice [Enter/R/O/K/S]: ", [
        "  Enter = I fixed it", "  R     = redo this step", "  O     = process again",
        "  K     = skip this order    S = stop the run"])
    assert set(_keys(r)) == {"", "r", "o", "k", "s"}
    assert r["options"][0]["key"] == "" and r["options"][-1]["key"] == "s"


def test_prompt_yes_no_and_numbered():
    assert _keys(parse_prompt("Confirm? [y/N]: ", [])) == ["y", "n"]
    r = parse_prompt("Select address [1-2] (Enter = 1, or type Q to stop): ",
                     ["  1. 12 MAIN ST  [option value='a']", "  2. 14 MAIN ST  [option value='b']"])
    assert _keys(r) == ["1", "2", "q"]


def test_prompt_unknown_falls_back_to_continue():
    assert _keys(parse_prompt("Press Enter to close the browser... ", [])) == [""]
