"""
Convert a market "Phone Order Analysis" workbook into the standard flat orders file.

Usage:
    python convert_orders.py <order_file.xlsx> [--market TULSA] [--date 2026-10-13]
                             [--market-details MarketDetails.xlsx] [--devices Devices.xlsx]
                             [--out orders_standard.xlsx]

Output sheets:
    Orders  - one row per (store, shipping, SKU, PAC|EA)
    Checks  - everything that needs a human look (nothing is dropped silently)
"""
import argparse
import math
import re
import sys
import warnings
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as L

warnings.filterwarnings("ignore")

SHEET = "OVER VIEW"
FIRST_DATA_ROW = 3
ALLOC_HEADER = "allocation"


def clean(v):
    return str(v).strip() if v is not None else ""


def lead_num(text):
    m = re.match(r"\s*(\d+)", clean(text))
    return m.group(1) if m else None


def load_devices(path):
    ws = openpyxl.load_workbook(path, data_only=True)["current devices"]
    pack = {}
    for sku, _name, per in ws.iter_rows(min_row=2, max_col=3, values_only=True):
        if sku is None or per is None:
            continue
        pack[clean(sku)] = int(round(float(per)))  # 4.999999999 -> 5
    return pack


def load_market_stores(path, market):
    ws = openpyxl.load_workbook(path, data_only=True)["Sheet1"]
    stores = {}
    dup = set()
    for mk, name, addr, ref, *_ in ws.iter_rows(min_row=2, max_col=5, values_only=True):
        if clean(mk).upper() != market:
            continue
        key = lead_num(addr)
        if key in stores:
            dup.add(key)
        stores[key] = {
            "name": clean(name),
            "address": clean(addr),
            "ident": clean(ref)[7:].upper(),  # strip stale DDMMMYY prefix
        }
    if dup:
        sys.exit(f"MarketDetails has duplicate street numbers for {market}: {sorted(dup)}. "
                 "Add an explicit store mapping.")
    return stores


def find_columns(ws):
    """Find the Overnight/Ground columns.

    The shipping row is whichever of rows 1-4 has the most Overnight/Ground cells (row 2 in
    Tulsa/Corpus/Arizona, row 3 in Waco). Store label = nearest non-empty cell above the
    shipping row in that column, inherited from the left for the Ground column.
    Returns (cols, alloc_col, remaining_col, first_data_row).
    """
    def is_ship(v):
        t = clean(v).lower()
        return t.startswith("overnight") or t.startswith("ground")

    counts = {r: sum(is_ship(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)) for r in range(1, 5)}
    ship_row = max(counts, key=counts.get)
    if counts[ship_row] == 0:
        sys.exit("Could not find Overnight/Ground headers in rows 1-4.")

    cols, label = [], None
    for c in range(1, ws.max_column + 1):
        v = clean(ws.cell(ship_row, c).value).lower()
        if not is_ship(v):
            continue
        above = next((clean(ws.cell(r, c).value) for r in range(ship_row - 1, 0, -1)
                      if clean(ws.cell(r, c).value)), "")
        if above:
            label = above
        cols.append((c, "overnight" if v.startswith("overnight") else "ground", label))

    def find_hdr(text):
        return next((c for r in range(1, ship_row + 1) for c in range(1, ws.max_column + 1)
                     if clean(ws.cell(r, c).value).lower() == text), None)

    alloc_col = find_hdr(ALLOC_HEADER)
    if alloc_col is None:
        sys.exit("Could not find an 'Allocation' header above the data.")
    return cols, alloc_col, find_hdr("remaining allo"), ship_row + 1


def round_row(vals, alloc):
    """vals: {col: qty}. Round fractions up while total <= allocation, else down."""
    notes = []
    out = {}
    frac_cols = [c for c, q in vals.items() if abs(q - round(q)) > 1e-9]
    for c, q in vals.items():
        out[c] = int(round(q)) if c not in frac_cols else None
    base = sum(v for v in out.values() if v is not None)
    # try rounding each fractional cell up, largest fraction first, while it still fits
    for c in sorted(frac_cols, key=lambda c: -(vals[c] - math.floor(vals[c]))):
        up, down = math.ceil(vals[c]), math.floor(vals[c])
        if alloc is not None and base + up <= alloc:
            out[c], base = up, base + up
            notes.append((c, vals[c], up, "rounded UP (fits allocation)"))
        else:
            out[c], base = down, base + down
            notes.append((c, vals[c], down, "rounded DOWN (up would exceed allocation)"))
    return out, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("order_file")
    ap.add_argument("--market")
    ap.add_argument("--date")
    ap.add_argument("--market-details", default="MarketDetails.xlsx")
    ap.add_argument("--devices", default="Devices.xlsx")
    ap.add_argument("--out", default="orders_standard.xlsx")
    a = ap.parse_args()

    market = (a.market or "").upper()
    if not market:
        known = {clean(r[0]).upper() for r in openpyxl.load_workbook(
            a.market_details, data_only=True)["Sheet1"].iter_rows(min_row=2, max_col=1, values_only=True) if r[0]}
        hits = [m for m in known if m in Path(a.order_file).name.upper()]
        if len(hits) != 1:
            sys.exit(f"Could not infer market from filename (candidates: {hits}); pass --market.")
        market = hits[0]

    order_date = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else date.today()
    date_tag = order_date.strftime("%d%b%y").upper()  # 13OCT26

    pack = load_devices(a.devices)
    stores = load_market_stores(a.market_details, market)

    ws = openpyxl.load_workbook(a.order_file, data_only=True)[SHEET]
    cols, alloc_col, rem_col, first_row = find_columns(ws)

    checks = []

    def chk(kind, detail):
        checks.append((kind, detail))

    # Map columns -> store
    col_store = {}
    labels_seen = set()
    for c, ship, label in cols:
        key = lead_num(label)
        if key not in stores:
            chk("STORE NOT MATCHED", f"col {L(c)} label '{label}' (street no. {key}) not in MarketDetails/{market}")
            continue
        st = dict(stores[key])
        st["name"] = st["name"] or label.strip()
        col_store[c] = (st, ship)
        labels_seen.add(key)
    missing = set(stores) - labels_seen
    if missing:
        chk("STORE NOT IN ORDER SHEET", f"MarketDetails stores with no columns in order sheet: {sorted(missing)}")
    for s in stores.values():
        if "," not in s["address"]:
            chk("ADDRESS INCOMPLETE", f"{s['name']}: '{s['address']}' (no city/state/zip)")

    last_ship = max(c for c, _, _ in cols)
    stray = defaultdict(list)

    # Collect qtys per row
    lines = defaultdict(list)  # (store_ident, ship) -> [(sku, name, qty)]
    seen_sku = {}
    for r in range(first_row, ws.max_row + 1):
        sku = clean(ws.cell(r, 1).value)
        if not sku:
            continue
        vals = {}
        for c in col_store:
            v = ws.cell(r, c).value
            if v in (None, "", 0, "0"):
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                chk("NON-NUMERIC QTY", f"row {r} col {L(c)}: {v!r}")
                continue
            if v > 0:
                vals[c] = v
        for c in range(last_ship + 1, last_ship + 4):
            v = ws.cell(r, c).value
            if isinstance(v, (int, float)) and v:
                stray[L(c)].append((r, sku, v))
        if not vals:
            continue
        if sku in seen_sku:
            chk("DUPLICATE SKU ROW", f"{sku} in rows {seen_sku[sku]} and {r}; both held")
            lines[("__HOLD__", sku)].append(r)
            continue
        seen_sku[sku] = r
        name = clean(ws.cell(r, 2).value)
        alloc = ws.cell(r, alloc_col).value
        alloc = float(alloc) if isinstance(alloc, (int, float)) else None
        if not alloc or alloc <= 0:
            chk("NO ALLOCATION - NOT ORDERED",
                f"row {r} {sku} {name}: allocation={alloc}, but sheet has qty {sum(vals.values())} "
                f"({'hidden' if ws.row_dimensions[r].hidden else 'visible'} row). Skipped.")
            continue

        rounded, notes = round_row(vals, alloc)
        for c, orig, new, why in notes:
            st, ship = col_store[c]
            chk("FRACTION", f"row {r} {sku} {name} | {st['name']} {ship}: {orig} -> {new} ({why}; allocation {alloc})")
        total = sum(rounded.values())
        if rem_col is not None:
            rem = ws.cell(r, rem_col).value
            if isinstance(rem, (int, float)) and rem < -1e-9:
                chk("SHEET'S OWN 'Remaining Allo' IS NEGATIVE",
                    f"row {r} {sku} {name}: {rem:.2f} (allocation {alloc}, ordering {total})")
        if alloc is not None and total > alloc:
            chk("OVER ALLOCATION", f"row {r} {sku} {name}: ordering {total} > allocation {alloc}")
        for c, q in rounded.items():
            if q <= 0:
                continue
            st, ship = col_store[c]
            lines[(st["ident"], ship)].append((sku, name, q, st))

    for col, items in stray.items():
        vals_set = {v for _, _, v in items}
        if vals_set == {1}:
            chk("COLUMN OUTSIDE STORE BLOCK (ignored)",
                f"col {col} has no store header and holds only 1s on {len(items)} rows - looks like a helper flag")
        else:
            chk("VALUES OUTSIDE STORE COLUMNS (ignored)",
                f"col {col}, no store header: " + "; ".join(f"row {r} {k}={v}" for r, k, v in items[:20]))

    # Build rows; hold whole group on missing pack info
    rows = []
    held = set()
    for (ident, ship), items in sorted(lines.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if ident == "__HOLD__":
            continue
        bad = [i for i in items if i[0] not in pack]
        if bad:
            held.add((ident, ship))
            for sku, name, *_ in bad:
                chk("SKU NOT IN PACK TABLE", f"{sku} {name}: order group {ident}/{ship} held entirely")
            continue
        suffix = "O" if ship == "overnight" else "G"
        ref = f"{date_tag}{ident}{suffix}"
        for sku, name, q, st in sorted(items, key=lambda i: i[0]):
            per = pack[sku]
            if per <= 1:
                pac, ea = 0, q  # EA-only device
            else:
                pac, ea = divmod(q, per)
            if pac:
                rows.append((market, sku, name, pac * per, "PAC", pac, st["name"], st["address"], ship.title(), ref))
            if ea:
                rows.append((market, sku, name, ea, "EA", ea, st["name"], st["address"], ship.title(), ref))

    # Reconciliation: device count in output vs. rounded demand
    out_total = sum(r[3] for r in rows)

    wb = openpyxl.Workbook()
    wo = wb.active
    wo.title = "Orders"
    hdr = ["Market", "SKU", "Device Name", "Devices", "Unit", "Unit Qty", "Store Name",
           "Store Address", "Shipping", "RefName"]
    wo.append(hdr)
    for row in rows:
        wo.append(row)
    for c in wo[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="305496")
    for r in range(2, wo.max_row + 1):
        wo.cell(r, 2).number_format = "@"
    wo.freeze_panes = "A2"
    wo.auto_filter.ref = wo.dimensions
    for i, w in enumerate([9, 15, 38, 9, 7, 9, 18, 46, 10, 20], 1):
        wo.column_dimensions[L(i)].width = w

    wc = wb.create_sheet("Checks")
    wc.append(["Type", "Detail"])
    for k, d in checks:
        wc.append([k, d])
    wc.append(["SUMMARY", f"{len(rows)} order lines | {len({r[9] for r in rows})} refnames | "
                          f"{out_total} devices | held groups: {sorted(held) or 'none'}"])
    for c in wc[1]:
        c.font = Font(bold=True)
    wc.column_dimensions["A"].width = 26
    wc.column_dimensions["B"].width = 120
    wb.save(a.out)

    print(f"{len(rows)} lines, {len({r[9] for r in rows})} refnames, {out_total} devices -> {a.out}")
    for k, d in checks:
        print(f"  [{k}] {d}")


if __name__ == "__main__":
    main()
