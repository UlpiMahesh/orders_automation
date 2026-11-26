"""Worker process: runs ONE task (convert / check / place) and talks to the GUI over stdio.

The GUI starts this as a separate process so a crash or a stuck browser can never freeze the
window, and so the Stop button can really stop it.

Protocol (stdout, one item per line; everything else is plain log text):
    @@RESULT {json}   structured result of the task
    @@PROMPT {json}   the engine wants an answer from the operator; the GUI replies on stdin
"""
from __future__ import annotations

import argparse
import builtins
import json
import os
import sys
import traceback
from pathlib import Path

RESULT = "@@RESULT "
PROMPT = "@@PROMPT "


def emit(tag: str, payload: dict) -> None:
    sys.stdout.write(tag + json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def install_gui_prompts() -> None:
    """Replace input() so the engine's terminal questions become dialogs in the GUI."""
    counter = [0]

    def gui_input(prompt: object = "") -> str:
        counter[0] += 1
        emit(PROMPT, {"id": counter[0], "prompt": str(prompt)})
        line = sys.stdin.readline()
        if line == "":
            raise EOFError("the Orders Desk window closed")
        return line.rstrip("\r\n")

    builtins.input = gui_input


# ------------------------------------------------------------------------------ convert
def _summarise_workbook(path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Orders"] if "Orders" in wb.sheetnames else wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        head = [str(c or "").strip().lower() for c in rows[0]] if rows else []
        ix = {h: i for i, h in enumerate(head)}
        body = [r for r in rows[1:] if any(c not in (None, "") for c in r)]
        refs = {r[ix["refname"]] for r in body if "refname" in ix}
        devices = 0
        if "devices" in ix:
            for r in body:
                try:
                    devices += int(float(r[ix["devices"]] or 0))
                except (TypeError, ValueError):
                    pass
        checks = []
        if "Checks" in wb.sheetnames:
            for r in list(wb["Checks"].iter_rows(values_only=True))[1:]:
                if r and r[0]:
                    checks.append({"type": str(r[0]), "detail": str(r[1] or "")})
        return {"lines": len(body), "orders": len(refs), "devices": devices, "checks": checks}
    finally:
        wb.close()


def task_convert(a: argparse.Namespace) -> int:
    if a.converter == "standard":
        from .engine.converters import standard_converter as conv
        argv = [a.source, "--market", a.market]
    elif a.converter == "dallas":
        from .engine.converters import dallas_converter as conv
        argv = [a.source]
    else:
        print(f"ERROR: market {a.market} has no converter configured.")
        return 2
    out = Path(a.out)
    staged = out.with_name(out.name + ".partial")      # never leave a half-written .xlsx behind
    argv += ["--market-details", a.details, "--devices", a.devices, "--date", a.date, "--out", str(staged)]
    print(f"Converting {Path(a.source).name}  ->  market {a.market}, order date {a.date}")
    sys.argv = ["convert", *argv]
    try:
        conv.main()
    except SystemExit as e:
        staged.unlink(missing_ok=True)
        if e.code not in (0, None):
            print(f"ERROR: {e.code}")
            return 2
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    if not staged.is_file():
        print("ERROR: the converter finished but no output workbook was written.")
        return 1
    os.replace(staged, out)
    summary = _summarise_workbook(out)
    summary["output"] = str(out)
    emit(RESULT, {"task": "convert", **summary})
    print(f"Done: {summary['orders']} order(s), {summary['lines']} line(s), "
          f"{len(summary['checks'])} item(s) to review.")
    return 0


# ------------------------------------------------------------------------------ check
def task_check(a: argparse.Namespace) -> int:
    from .engine.placement import place_orders as po
    print(f"Checking {Path(a.workbook).name} ...")
    try:
        groups, bad = po.load_plan(a.workbook, a.market or None, None)
    except SystemExit as e:
        print(f"ERROR: {e.code}")
        emit(RESULT, {"task": "check", "ok": False, "error": str(e.code), "orders": [], "rejected": []})
        return 2
    orders = []
    for g in groups.values():
        lines = [{"sku": l.sku, "name": l.name, "unit": l.unit, "qty": l.qty, "devices": l.devices}
                 for l in g.lines]
        orders.append({
            "ref": g.ref, "market": g.market, "store": g.store, "address": g.address,
            "shipping": g.shipping, "lineCount": len(lines),
            "units": sum(l["qty"] for l in lines),
            "devices": sum((l["devices"] or l["qty"]) for l in lines),
            "cpo": sum(1 for l in g.lines if " CPO" in f" {l.name.upper()} "),
            "lines": lines,
        })
    rejected = [{"ref": k, "reason": v} for k, v in bad.items()]
    extra = _summarise_workbook(Path(a.workbook))
    emit(RESULT, {"task": "check", "ok": not rejected, "orders": orders, "rejected": rejected,
                  "checks": extra["checks"], "workbook": a.workbook})
    print(f"{len(orders)} order(s) ready, {len(rejected)} rejected, "
          f"{len(extra['checks'])} conversion note(s).")
    return 0 if not rejected else 3


# ------------------------------------------------------------------------------ place
def task_place(a: argparse.Namespace) -> int:
    for var in ("ORDERS_AUTOMATION_RUNTIME_DIR", "ORDERS_AUTOMATION_LOG_DIR"):
        if not os.environ.get(var):          # never fall back to writing next to the program files
            print(f"ERROR: {var} is not set; refusing to run without an external output folder.")
            return 2
    install_gui_prompts()
    from .engine.placement import place_orders as po
    argv = [a.workbook, "--market", a.market, "--logins", a.logins, "--login-market", a.login_market]
    if a.mode == "verify":
        argv.append("--verify-only")
    if a.limit:
        argv += ["--limit", str(a.limit)]
    for r in a.ref or []:
        argv += ["--ref", r]
    sys.argv = ["place_orders", *argv]
    try:
        po.main()
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"ERROR: {e.code}")
            return 2
    return 0


# ------------------------------------------------------------------------------ selftest
def task_selftest(a: argparse.Namespace) -> int:
    """Exercises the prompt round-trip without touching any portal (used by tests / diagnostics)."""
    install_gui_prompts()
    print("selftest: started")
    ans = input("\n[SELF-1] Order built and validated.\n  Enter = Go To Checkout\n  K     = skip this order    S = stop the run\nYour choice [Enter/K/S]: ")
    print(f"selftest: you answered {ans!r}")
    ok = input("Confirm this Deliver-To address and continue? [y/N]: ")
    print(f"selftest: confirm {ok!r}")
    emit(RESULT, {"task": "selftest", "answers": [ans, ok]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="orders-worker")
    sub = ap.add_subparsers(dest="task", required=True)

    c = sub.add_parser("convert")
    c.add_argument("--market", required=True)
    c.add_argument("--converter", required=True, choices=["standard", "dallas"])
    c.add_argument("--source", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--date", required=True)
    c.add_argument("--details", required=True)
    c.add_argument("--devices", required=True)
    c.set_defaults(fn=task_convert)

    k = sub.add_parser("check")
    k.add_argument("--workbook", required=True)
    k.add_argument("--market", default="")
    k.set_defaults(fn=task_check)

    p = sub.add_parser("place")
    p.add_argument("--workbook", required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--mode", choices=["verify", "live"], required=True)
    p.add_argument("--logins", required=True)
    p.add_argument("--login-market", required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--ref", action="append")
    p.set_defaults(fn=task_place)

    s = sub.add_parser("selftest")
    s.set_defaults(fn=task_selftest)
    return ap


def run_worker(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except Exception as exc:   # last line of defence: never die silently
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print(traceback.format_exc())
        return 1
