"""
Convert Dallas workbook (DALLAS, PARIS, LUFKIN tabs) into standard orders format.

Usage:
    python convert_dallas_orders.py Dallas.xlsx
    python convert_dallas_orders.py Dallas.xlsx --date 2026-11-04

The output Market is always DALLAS. Rows are included only when Our 30% > 0.
PAC quantities use Devices.xlsx -> current devices -> Device per pac.
"""
import argparse
import re
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as L


def clean(v):
    return str(v).strip() if v is not None else ""


def lead_num(text):
    m = re.match(r"\s*(\d+)", clean(text))
    return m.group(1) if m else None


def load_pack_table(path):
    ws = openpyxl.load_workbook(path, data_only=True)["current devices"]
    pack = {}
    for sku, _name, per in ws.iter_rows(min_row=2, max_col=3, values_only=True):
        if sku is None or per is None:
            continue
        pack[clean(sku)] = int(round(float(per)))
    return pack


def load_all_stores(path):
    ws = openpyxl.load_workbook(path, data_only=True)["Sheet1"]
    stores = {}
    duplicates = set()
    for market, name, address, ref, *_ in ws.iter_rows(min_row=2, max_col=5, values_only=True):
        key = lead_num(address)
        if not key:
            continue
        if key in stores:
            duplicates.add(key)
        stores[key] = {
            "name": clean(name),
            "address": clean(address),
            "ident": clean(ref)[7:].upper(),  # same DDMMMYY stripping as convert_orders.py
        }
    # Only fail if a duplicate street number affects one of this workbook's stores;
    # the full MarketDetails workbook can contain duplicates in unrelated markets.
    return stores, duplicates


# Explicit source layouts: (quantity column, store header, shipping type)
BLOCKS = [
    {
        "sheet": "DALLAS ", "our30": "AB", "first_row": 4,
        "columns": [
            ("AE", "738 SHERMAN", "overnight"), ("AF", "738 SHERMAN", "ground"),
            ("AG", "2011 BONHAM", "overnight"), ("AH", "2011 BONHAM", "ground"),
            ("AI", "1418 WEATHER FORD", "overnight"), ("AJ", "1418 WEATHER FORD", "ground"),
            ("AK", "2801 MINERAL WELLS", "overnight"), ("AL", "2801 MINERAL WELLS", "ground"),
            ("AM", "593 MANSFIELD", "overnight"), ("AN", "593 MANSFIELD", "ground"),
            ("AO", "7701 CROWLEY", "overnight"), ("AP", "7701 CROWLEY", "ground"),
        ],
    },
    {
        "sheet": "PARIS", "our30": "P", "first_row": 4,
        "columns": [
            ("S", "1404 CLARKSVILLE", "overnight"), ("T", "1404 CLARKSVILLE", "ground"),
            ("U", "3912 Lamar", "overnight"), ("V", "3912 Lamar", "ground"),
        ],
    },
    {
        "sheet": "LUFKIN", "our30": "V", "first_row": 3,
        "columns": [
            ("Y", "3007 LUF -JOHN", "overnight"), ("Z", "3007 LUF -JOHN", "ground"),
            ("AA", "103N -CHESTNUT", "overnight"), ("AB", "103N -CHESTNUT", "ground"),
            ("AC", "1019-SOUTH", "overnight"), ("AD", "1019-SOUTH", "ground"),
            ("AE", "2415 -NORTH", "overnight"), ("AF", "2415 -NORTH", "ground"),
        ],
    },
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("order_file", nargs="?", default="Dallas.xlsx")
    ap.add_argument("--market-details", default="MarketDetails.xlsx")
    ap.add_argument("--devices", default="Devices.xlsx")
    ap.add_argument("--date", help="Order date YYYY-MM-DD (defaults to today's date, same as convert_orders.py)")
    ap.add_argument("--out", default="orders_standard_Dallas.xlsx")
    args = ap.parse_args()

    order_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    date_tag = order_date.strftime("%d%b%y").upper()

    pack = load_pack_table(args.devices)
    stores, duplicate_keys = load_all_stores(args.market_details)
    wb_in = openpyxl.load_workbook(args.order_file, data_only=True)

    checks = []
    def chk(kind, detail):
        checks.append((kind, detail))

    grouped = defaultdict(list)
    matched_keys = set()
    seen_skus = defaultdict(dict)
    included_cells = 0
    included_devices = 0
    excluded_devices = 0

    # Allocation!A = SKU, Allocation!C = total allocation shared by
    # DALLAS + PARIS + LUFKIN. Never treat it as a per-market allowance.
    allocation_by_sku = {}
    if "Allocation" not in wb_in.sheetnames:
        raise ValueError("Dallas workbook is missing the required 'Allocation' sheet")
    alloc_ws = wb_in["Allocation"]
    for alloc_row in range(3, alloc_ws.max_row + 1):
        alloc_sku = clean(alloc_ws.cell(alloc_row, 1).value)
        alloc_value = alloc_ws.cell(alloc_row, 3).value
        if not alloc_sku:
            continue
        if alloc_value in (None, ""):
            continue
        try:
            allocation_by_sku[alloc_sku] = float(alloc_value)
        except (TypeError, ValueError):
            chk("INVALID ALLOCATION",
                f"Allocation row {alloc_row} SKU {alloc_sku}: column C={alloc_value!r}")

    # First collect all eligible market/store quantities. This is necessary
    # because the allocation is shared across all three market tabs.
    candidates = []
    fractional_by_sku = defaultdict(list)
    total_by_sku = defaultdict(float)
    rounded_total_by_sku = defaultdict(int)
    integer_total_by_sku = defaultdict(int)

    for block in BLOCKS:
        ws = wb_in[block["sheet"]]
        for r in range(block["first_row"], ws.max_row + 1):
            sku = clean(ws.cell(r, 1).value)
            if not sku:
                continue
            name = clean(ws.cell(r, 2).value)
            our30 = ws[f'{block["our30"]}{r}'].value
            try:
                our30_value = float(our30 or 0)
            except (TypeError, ValueError):
                chk("INVALID OUR 30%", f'{block["sheet"]} row {r} {sku}: {our30!r}; row skipped')
                continue

            quantities = []
            for col, label, shipping in block["columns"]:
                value = ws[f"{col}{r}"].value
                if value in (None, "", 0, "0"):
                    continue
                try:
                    qty = float(value)
                except (TypeError, ValueError):
                    chk("NON-NUMERIC QTY", f'{block["sheet"]} row {r} {sku} col {col}: {value!r}')
                    continue
                if qty > 0:
                    quantities.append((qty, col, label, shipping))

            if not quantities:
                continue

            if our30_value <= 0:
                excluded_devices += sum(q for q, *_ in quantities)
                chk("OUR 30% NOT POSITIVE - SKIPPED",
                    f'{block["sheet"]} row {r} {sku} {name}: Our 30%={our30}; '
                    f'order qty {sum(q for q, *_ in quantities)} excluded')
                continue

            if sku in seen_skus[block["sheet"]]:
                chk("DUPLICATE SKU ROW",
                    f'{block["sheet"]} SKU {sku} in rows {seen_skus[block["sheet"]][sku]} and {r}; review both')
                continue
            seen_skus[block["sheet"]][sku] = r

            for qty, col, label, shipping in quantities:
                candidate = {
                    "block": block, "row": r, "sku": sku, "name": name,
                    "qty": qty, "col": col, "label": label, "shipping": shipping,
                }
                candidates.append(candidate)
                total_by_sku[sku] += qty
                if abs(qty - round(qty)) > 1e-9:
                    fractional_by_sku[sku].append(candidate)
                    rounded_total_by_sku[sku] += math.ceil(qty - 1e-9)
                else:
                    integer_total_by_sku[sku] += int(round(qty))
                    rounded_total_by_sku[sku] += int(round(qty))

    # Decide rounding once per SKU across ALL three market tabs.
    # Fractional lines are rounded UP only if the resulting SKU total fits
    # within Allocation!C. If not, fractional lines are held for review.
    approved_qty = {}
    for sku, fractional_lines in fractional_by_sku.items():
        allocation = allocation_by_sku.get(sku)
        proposed_total = rounded_total_by_sku[sku]
        integer_total = integer_total_by_sku[sku]
        if allocation is None:
            chk("ALLOCATION MISSING - FRACTIONAL QTY HELD",
                f"SKU {sku}: fractional quantities across Dallas/Paris/Lufkin need rounding, "
                "but Allocation!C is blank or SKU is missing")
            continue
        if integer_total > allocation + 1e-9:
            chk("ALLOCATION EXCEEDED - SKU HELD",
                f"SKU {sku}: existing whole quantities total {integer_total}, "
                f"which already exceeds shared allocation {allocation}; all lines held")
            continue
        if proposed_total > allocation + 1e-9:
            chk("ALLOCATION LIMIT - FRACTIONAL QTY HELD",
                f"SKU {sku}: rounding fractional lines up would make combined total "
                f"{proposed_total}, above shared allocation {allocation}; fractional lines held")
            continue
        for item in fractional_lines:
            approved_qty[id(item)] = math.ceil(item["qty"] - 1e-9)
        chk("FRACTIONAL QTY ROUNDED UP",
            f"SKU {sku}: combined Dallas/Paris/Lufkin quantity {total_by_sku[sku]} "
            f"rounded to {proposed_total}; shared allocation {allocation}")

    # Convert approved candidates into the standard order rows.
    hold_fractional_skus = set()
    hold_all_skus = set()
    for sku in fractional_by_sku:
        allocation = allocation_by_sku.get(sku)
        if allocation is None or rounded_total_by_sku[sku] > allocation + 1e-9:
            hold_fractional_skus.add(sku)
        if allocation is not None and integer_total_by_sku[sku] > allocation + 1e-9:
            hold_all_skus.add(sku)

    for item in candidates:
        qty = item["qty"]
        sku = item["sku"]
        is_fractional = abs(qty - round(qty)) > 1e-9
        if sku in hold_all_skus or (is_fractional and sku in hold_fractional_skus):
            continue
        if abs(qty - round(qty)) > 1e-9:
            if id(item) not in approved_qty:
                continue
            final_qty = approved_qty[id(item)]
        else:
            final_qty = int(round(qty))

        key = lead_num(item["label"])
        if key in duplicate_keys:
            chk("AMBIGUOUS STORE STREET NUMBER",
                f'{item["block"]["sheet"]} row {item["row"]} {item["label"]}: '
                f'street number {key} is duplicated in MarketDetails')
            continue
        store = stores.get(key)
        if not store:
            chk("STORE NOT MATCHED",
                f'{item["block"]["sheet"]} row {item["row"]} col {item["col"]} '
                f'label {item["label"]!r} (street no. {key}) not in MarketDetails')
            continue
        matched_keys.add(key)
        grouped[(store["ident"], item["shipping"])].append(
            (sku, item["name"], final_qty, store))
        included_cells += 1
        included_devices += final_qty

    rows = []
    held_groups = set()
    for (ident, shipping), items in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        missing = [item for item in items if item[0] not in pack]
        if missing:
            held_groups.add((ident, shipping))
            for sku, name, *_ in missing:
                chk("SKU NOT IN PACK TABLE", f"{sku} {name}: order group {ident}/{shipping} held entirely")
            continue

        ref = f'{date_tag}{ident}{"O" if shipping == "overnight" else "G"}'
        for sku, name, qty, store in sorted(items, key=lambda item: item[0]):
            per_pack = pack[sku]
            if per_pack <= 1:
                pac, ea = 0, qty
            else:
                pac, ea = divmod(qty, per_pack)
            if pac:
                rows.append(("DALLAS", sku, name, pac * per_pack, "PAC", pac,
                             store["name"], store["address"], shipping.title(), ref))
            if ea:
                rows.append(("DALLAS", sku, name, ea, "EA", ea,
                             store["name"], store["address"], shipping.title(), ref))

    output_total = sum(row[3] for row in rows)
    out = openpyxl.Workbook()
    wo = out.active
    wo.title = "Orders"
    headers = ["Market", "SKU", "Device Name", "Devices", "Unit", "Unit Qty",
               "Store Name", "Store Address", "Shipping", "RefName"]
    wo.append(headers)
    for row in rows:
        wo.append(row)
    for cell in wo[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
    for r in range(2, wo.max_row + 1):
        wo.cell(r, 2).number_format = "@"
    wo.freeze_panes = "A2"
    wo.auto_filter.ref = wo.dimensions
    for i, width in enumerate([9, 15, 38, 9, 7, 9, 22, 52, 12, 20], 1):
        wo.column_dimensions[L(i)].width = width

    wc = out.create_sheet("Checks")
    wc.append(["Type", "Detail"])
    for kind, detail in checks:
        wc.append([kind, detail])
    wc.append(["SUMMARY",
               f'{len(rows)} order lines | {len({row[9] for row in rows})} refnames | '
               f'{output_total} devices | source order cells: {included_cells} | '
               f'Our 30% excluded devices: {excluded_devices} | held groups: {sorted(held_groups) or "none"}'])
    for cell in wc[1]:
        cell.font = Font(bold=True)
    wc.column_dimensions["A"].width = 34
    wc.column_dimensions["B"].width = 125
    out.save(args.out)

    print(f'{len(rows)} order lines, {len({row[9] for row in rows})} refnames, '
          f'{output_total} devices -> {args.out}')
    print(f'Included source cells: {included_cells}; Our 30% excluded devices: {excluded_devices}')
    for kind, detail in checks:
        print(f'[{kind}] {detail}')


if __name__ == "__main__":
    main()
