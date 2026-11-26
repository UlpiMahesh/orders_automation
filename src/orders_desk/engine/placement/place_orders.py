"""
place_orders.py - Build, validate, check out and submit each order.
After the final order page matches the workbook, capture the portal receipt details
into one consolidated Excel worksheet covering all processed markets.

Input : orders_standard.xlsx (sheet "Orders") from convert_orders.py
Per RefName (= one store + one shipping method = one order):
    1. open the shopping cart (no catalog) and clear anything already in it
    2. reopen the cart, choose "25 New Items" and click Update -> blank item rows
    3. type SKU / Unit Qty / Unit (PAC or EA) of every sheet line into its own cart row,
       click Update, then verify every row against the sheet
    4. header: Your Reference Number = RefName, Description = backoffice,
               Deliver To = store address, Shipping Method = Ground/Overnight
    5. Go through checkout, verify the final page, then click Order
    6. Extract receipt details and write all markets to one consolidated worksheet
After every click the script waits until the page and all frames are completely loaded.

Usage:
    python place_orders.py orders_standard.xlsx --dry-run
    python place_orders.py orders_standard.xlsx --market CORPUS --limit 1
    python place_orders.py orders_standard.xlsx --ref 13OCT261446AIRG
"""
import argparse
import logging
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import openpyxl

# Runtime files (logs/results/screenshots) are directed to the selected market's logs folder.
try:
    _DEFAULT_RUNTIME = Path(__file__).resolve().parents[3]
except IndexError:  # script sitting in a shallow folder
    _DEFAULT_RUNTIME = Path(__file__).resolve().parent
BASE_DIR = Path(os.environ.get('ORDERS_AUTOMATION_RUNTIME_DIR', _DEFAULT_RUNTIME)).resolve()


def default_logins():
    configured = os.environ.get('ORDERS_AUTOMATION_LOGINS')
    if configured:
        return Path(configured).expanduser().resolve()
    # Fallback: marketlogins.xlsx in the parent directory of the project.
    return BASE_DIR.parent / 'marketlogins.xlsx'


PORTAL_URL = "https://www.t-mobiledealerordering.com"
HEADER_DESCRIPTION = "backoffice"
SHIP_COND = {"GROUND": "03", "OVERNIGHT": "04"}  # values of #shipCond
TIMEOUT = 30  # seconds for any single wait

COLUMNS = ["market", "sku", "device name", "unit", "unit qty",
           "store name", "store address", "shipping", "refname"]
OPTIONAL_COLUMNS = ["devices"]  # used only to recognise PAC lines the portal shows in EACHes

log = logging.getLogger("place_orders")


def setup_logging():
    """Create timestamped file + console logging and return (log directory, run stamp)."""
    logdir = Path(os.environ.get("ORDERS_AUTOMATION_LOG_DIR") or (BASE_DIR / "logs"))
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Avoid duplicate handlers if main() is called more than once in an interactive session.
    for handler in list(log.handlers):
        log.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(logdir / f"place_orders_{stamp}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    log.addHandler(console_handler)
    log.propagate = False
    log.info("Logging initialized. Log file: %s", logdir / f"place_orders_{stamp}.log")
    return logdir, stamp


def launch_browser(p):
    """Open a visible, maximised browser.

    ORDERS_AUTOMATION_BROWSER = auto | chromium | msedge | chrome.
    'auto' tries Playwright's own Chromium first (what this script was written against),
    then the Edge and Chrome that are already installed on the PC, so no download is needed.
    """
    pref = (os.environ.get("ORDERS_AUTOMATION_BROWSER") or "auto").strip().lower()
    orders = {
        "auto": [None, "msedge", "chrome"],
        "chromium": [None, "msedge", "chrome"],
        "msedge": ["msedge", "chrome", None],
        "chrome": ["chrome", "msedge", None],
    }
    last = None
    for channel in orders.get(pref, orders["auto"]):
        try:
            kwargs = {"headless": False, "args": ["--start-maximized"]}
            if channel:
                kwargs["channel"] = channel
            browser = p.chromium.launch(**kwargs)
            log.info("browser started: %s", channel or "Playwright Chromium")
            return browser
        except Exception as exc:
            last = exc
            log.warning("browser %s not available (%s)", channel or "Playwright Chromium", str(exc).splitlines()[0][:160])
    raise RuntimeError(f"No usable browser found (tried Chromium, Edge, Chrome): {last}")


class SkipOrder(Exception):
    """Operator chose to skip the current order."""


class RestartOrder(Exception):
    """Operator chose to process the current order again from the beginning."""


class StopRun(Exception):
    """Operator chose to stop the run (or the browser was closed)."""


NO_PAUSE = False   # set from --no-pause; when True nothing may wait for the operator
VERIFY_ONLY = False  # set from --verify-only: check the final order page but never click Order
ALLOW_SEND_ORDER = False  # True only while the script clicks Order on a verified final page
ORDER_CLICKED = set()  # RefNames whose Order button was clicked (never click twice / never restart)
LOGDIR = None      # set by main()
STAMP = ""
EVENTS = {}        # RefName -> list of "what went wrong / what the operator did" notes
ORDER_CTX = {}     # RefName -> {"value": Deliver-To option value, "text": Deliver-To label}


class GroupError(Exception):
    """Expected, per-order failure: log one line, skip this RefName, carry on."""


# --------------------------------------------------------------------------- plan
@dataclass
class Line:
    sku: str
    name: str
    unit: str  # PAC | EA
    qty: int
    devices: int = 0  # "Devices" column (EA equivalent); 0 when the sheet has no such column


@dataclass
class Group:
    ref: str
    market: str
    store: str
    address: str
    shipping: str  # GROUND | OVERNIGHT
    lines: list = field(default_factory=list)

    def skus(self):
        seen = []
        for l in self.lines:
            if l.sku not in seen:
                seen.append(l.sku)
        return seen

    def lines_for(self, sku):
        # PAC first, then EA - fixed order so cart rows can be assigned deterministically
        return sorted((l for l in self.lines if l.sku == sku), key=lambda l: l.unit != "PAC")


def clean(v):
    return str(v).strip() if v is not None else ""


def load_plan(path, market=None, refs=None):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Orders"] if "Orders" in wb.sheetnames else wb.worksheets[0]
    header = [clean(c.value).lower() for c in ws[1]]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        sys.exit(f"{path}: missing columns {missing}. Found: {header}")
    ix = {c: header.index(c) for c in COLUMNS}
    opt = {c: header.index(c) for c in OPTIONAL_COLUMNS if c in header}

    raw = defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        ref = clean(row[ix["refname"]])
        raw[ref].append({**{c: row[ix[c]] for c in COLUMNS}, **{c: row[i] for c, i in opt.items()}})

    ok, bad = {}, {}
    for ref, rows in raw.items():
        mk = clean(rows[0]["market"]).upper()
        if market and mk != market.upper():
            continue
        if refs and ref not in refs:
            continue
        try:
            ok[ref] = build_group(ref, rows)
        except GroupError as e:
            bad[ref] = str(e)
    return ok, bad


def build_group(ref, rows):
    if not re.fullmatch(r"[A-Za-z0-9]{1,30}", ref):
        raise GroupError(f"RefName '{ref}' must be 1-30 letters/digits only")
    one = lambda key: {clean(r[key]).upper() for r in rows}
    for key in ("market", "store address", "shipping"):
        if len(one(key)) != 1:
            raise GroupError(f"{ref}: rows disagree on {key}: {sorted(one(key))}")
    shipping = one("shipping").pop()
    if shipping not in SHIP_COND:
        raise GroupError(f"{ref}: unknown shipping '{shipping}'")
    g = Group(ref, one("market").pop(), clean(rows[0]["store name"]),
              clean(rows[0]["store address"]), shipping)
    seen = set()
    for r in rows:
        sku = clean(r["sku"]).split(".")[0]
        unit = clean(r["unit"]).upper()
        try:
            qty = int(r["unit qty"])
        except (TypeError, ValueError):
            raise GroupError(f"{ref}: bad Unit Qty '{r['unit qty']}' for {sku}")
        if unit not in ("PAC", "EA") or qty <= 0:
            raise GroupError(f"{ref}: bad unit/qty for {sku}: {unit} {qty}")
        if (sku, unit) in seen:
            raise GroupError(f"{ref}: duplicate row for {sku} {unit} - order stopped")
        seen.add((sku, unit))
        try:
            devices = int(float(r.get("devices") or 0))
        except (TypeError, ValueError):
            devices = 0
        g.lines.append(Line(sku, clean(r["device name"]), unit, qty, devices))
    return g


def print_plan(g):
    print(f"\n{g.ref}  [{g.market}] {g.store} | {g.shipping} | {g.address}")
    for i, l in enumerate(g.lines, start=1):
        kind = "CPO" if re.search(r"\bCPO\b", l.name.upper()) else "   "
        print(f"   row {i:<2} {l.sku}  {l.name:<38} {l.qty:>3} {l.unit} {kind}")


# ------------------------------------------------------------------ address match
def norm(s):
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def lead_num(s):
    m = re.match(r"\s*(\d+)", s)
    return m.group(1) if m else None


def pick_ship_to(options, address, read_current=None, select_current=None):
    """Resolve the Deliver-To option for the sheet address.

    options are (value, visible_text) pairs from #headerShipTo. Matching tiers, first hit wins:
      1. exact address (normalised)
      2. the option starts with the sheet address (sheet has only the street, no city)
      3. same street number + same city
      4. every word of the sheet address appears in the option
    A single exact / street-prefix match is used directly. Anything less certain, or several
    candidates, is shown to the operator to confirm. If nothing matches, the operator may type
    an option number, or pick it by hand in the browser and press Enter (read_current is then
    used to read what they selected) - the order is NOT failed.
    """
    n = norm(address)
    exact = [o for o in options if norm(o[1]) == n]
    if len(exact) == 1:
        log.info("Deliver-To has one exact match: '%s' (value=%r)", exact[0][1], exact[0][0])
        return exact[0]

    pool, match_kind = exact, "exact address"
    if not pool and n:
        pool = [o for o in options if (norm(o[1]) + " ").startswith(n + " ")]
        match_kind = "option starts with the sheet address"
        if len(pool) == 1:
            log.info("Deliver-To matched by street address (sheet has no city): '%s' (value=%r)",
                     pool[0][1], pool[0][0])
            return pool[0]
    if not pool:
        parts = [x.strip() for x in address.split(",")]
        city = norm(parts[1]) if len(parts) > 1 else ""
        num = lead_num(address)
        pool = [o for o in options if num and lead_num(o[1]) == num and city and city in norm(o[1])]
        match_kind = "street number + city"
    if not pool:
        words = norm(address).split()
        pool = [o for o in options if words and all(w in set(norm(o[1]).split()) for w in words)]
        match_kind = "all words of the address appear"

    if not pool:
        return _ask_ship_to_manually(options, address, read_current, select_current)

    # A fallback / ambiguous match is shown for operator confirmation.
    print("\nDeliver-To address needs your confirmation:")
    print(f"Requested address: {address}")
    print(f"Matching options ({match_kind}):")
    for i, (value, label) in enumerate(pool, start=1):
        print(f"  {i}. {label}  [option value={value!r}]")

    while True:
        try:
            answer = input(f"Select address [1-{len(pool)}] (Enter = 1, or type Q to stop): ").strip()
        except (EOFError, KeyboardInterrupt):
            raise GroupError("Deliver-To selection cancelled by user; order stopped before header update")
        if answer.lower() == "q":
            raise GroupError("Deliver-To selection cancelled by user; order stopped before header update")
        if answer == "":
            index = 0
            break
        if answer.isdigit() and 1 <= int(answer) <= len(pool):
            index = int(answer) - 1
            break
        print(f"Enter a number from 1 to {len(pool)}, press Enter for the first option, or Q to stop.")

    selected = pool[index]
    print(f"\nSelected Deliver-To: {selected[1]} [option value={selected[0]!r}]")
    while True:
        try:
            confirmed = input("Confirm this Deliver-To address and continue? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise GroupError("Deliver-To confirmation cancelled by user; order stopped before header update")
        if confirmed in ("y", "yes"):
            log.info("Deliver-To confirmed by user: '%s' (value=%r)", selected[1], selected[0])
            return selected
        if confirmed in ("", "n", "no", "q"):
            raise GroupError("Deliver-To address was not confirmed; order stopped before header update")
        print("Please enter Y to confirm or N to stop this order.")


def _ask_ship_to_manually(options, address, read_current, select_current):
    """Nothing matched: let the operator choose (number) or set it by hand in the browser."""
    msg = (f"Deliver-To not matched for '{address}'. Available options: "
           f"{[(o[0], o[1]) for o in options]}")
    if NO_PAUSE or read_current is None:
        raise GroupError(msg)
    log.warning("%s - asking the operator", msg)
    print(f"\nNo Deliver-To option matches the sheet address: {address}")
    print("Portal options:")
    for i, (value, label) in enumerate(options, start=1):
        print(f"  {i}. {label}")
    while True:
        try:
            ans = input("Type the option NUMBER to use, M = I will select it myself in the browser "
                        "(then press Enter), K = skip this order, S = stop the run: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise StopRun("input closed while choosing Deliver-To")
        if ans == "k":
            raise SkipOrder(f"operator skipped the order: no Deliver-To for '{address}'")
        if ans == "s":
            raise StopRun("operator stopped the run at Deliver-To selection")
        if ans == "m":
            try:
                input("Select the right Deliver-To in the portal's dropdown now, wait for the page to "
                      "finish reloading, then press Enter here... ")
            except (EOFError, KeyboardInterrupt):
                raise StopRun("input closed while waiting for manual Deliver-To")
            value, label = read_current()
            log.info("Deliver-To set manually by the operator: '%s' (value=%r)", label, value)
            return (value, label)
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            chosen = options[int(ans) - 1]
            log.info("Deliver-To chosen by the operator from the list: '%s' (value=%r)", chosen[1], chosen[0])
            return chosen
        print(f"Type a number from 1 to {len(options)}, or M, K or S.")


# ---------------------------------------------------------------- browser helpers
def find_frame(page, selector, timeout=TIMEOUT):
    """The portal is frame-based in places, so look for the selector in every frame."""
    end = time.time() + timeout
    while time.time() < end:
        for f in page.frames:
            try:
                if f.locator(selector).count():
                    return f
            except Exception:
                pass
        page.wait_for_timeout(300)
    raise GroupError(f"Timed out waiting for '{selector}'")


def mark_frames(page):
    for f in page.frames:
        try:
            f.evaluate("window.__pw = 1")
        except Exception:
            pass


def wait_reloaded(page, selector, timeout=TIMEOUT, what=""):
    """Wait for a frame holding `selector` that is a fresh load (our marker is gone)."""
    end = time.time() + timeout
    while time.time() < end:
        for f in page.frames:
            try:
                if f.locator(selector).count() and not f.evaluate("!!window.__pw"):
                    return f
            except Exception:
                pass
        page.wait_for_timeout(300)
    raise GroupError(f"[{what or 'wait'}] page did not reload / '{selector}' did not appear")


def basket_text(page):
    f = find_frame(page, "#basketlinktext")
    return f.locator("#basketlinktext").inner_text().strip()


FORM = 'form[name="order_positions"]'
BASKET_LINK = 'a[onclick="show_basket()"]'


def settle(page, extra_ms=1500):
    """Let the page finish loading after an add (portal reloads the catalog)."""
    try:
        page.wait_for_load_state("load", timeout=TIMEOUT * 1000)
    except Exception:
        pass
    page.wait_for_timeout(extra_ms)


def wait_fully_loaded(page, what="", timeout=TIMEOUT, quiet_ms=1200):
    """Block until the page AND every frame report readyState 'complete' and stay that way
    for quiet_ms. Called after every button click so nothing is touched mid-load."""
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass  # legacy portal may keep a connection open; the readyState check below still runs
    deadline = time.time() + timeout
    quiet_since = None
    while time.time() < deadline:
        ready = True
        for f in list(page.frames):
            try:
                if f.evaluate("document.readyState") != "complete":
                    ready = False
                    break
            except Exception:
                ready = False
                break
        now = time.time()
        if ready:
            quiet_since = quiet_since or now
            if (now - quiet_since) * 1000 >= quiet_ms:
                return
        else:
            quiet_since = None
        page.wait_for_timeout(250)
    log.warning("[%s] page did not report fully loaded within %ss; continuing", what or "wait", timeout)




def cart_is_empty(text):
    """Empty cart shows just 'Shopping Cart'; a filled one shows '<n> Item(s) to the value of ...'."""
    m = re.search(r"(\d+)\s*Item", text, re.I)
    return (not m) or int(m.group(1)) == 0


def form_frame_now(page):
    for f in page.frames:
        try:
            if f.locator(FORM).count():
                return f
        except Exception:
            pass
    return None


def call_portal_js(page, fn):
    """Call a global portal JS function (e.g. show_basket) in whichever frame defines it."""
    for f in page.frames:
        try:
            if f.evaluate(f"typeof {fn} === 'function'"):
                f.evaluate(f"() => setTimeout(() => {fn}(), 0)")  # async: the page is about to navigate
                return f
        except Exception:
            pass
    return None


def describe_basket(page):
    """Diagnostics for when the cart cannot be opened."""
    try:
        f = find_frame(page, "#basketlinktext", 3)
        html = f.locator("#basketlinktext").evaluate("e => (e.closest('a') || e.parentElement).outerHTML")
        log.info("basket link markup: %s", " ".join(html.split())[:500])
    except Exception as e:
        log.info("basket link markup unavailable: %s", e)
    log.info("frames: %s", [f.url for f in page.frames])


# ----------------------------------------------------------------------------
# ROOT-CAUSE FIX for the "silent" failures (Update / Deliver To / Go To Checkout do nothing).
#
# The cart page is only usable after its <body onload="miRegisterObjects()"> hook has run.
# When that hook has not run, miAllObjs stays null, so the portal's own
# miSetStatusUpdateRunning(true) throws "Cannot read properties of null (reading 'length')".
# It has already set its lock (miUpdateStarted = true) by then, so EVERY later
# submit_refresh() (Update, Deliver To -> changeHeaderDeliverTo, Go To Checkout) returns
# immediately and the page just sits there. Run the hook ourselves and clear the lock
# before each action, then insist on positive proof that the page really reloaded.
# ----------------------------------------------------------------------------
PRIME_JS = """() => {
  const st = {
    hasFn: (typeof miRegisterObjects === 'function'),
    hadObjs: (typeof miAllObjs !== 'undefined' && miAllObjs !== null),
    wasLocked: (typeof miUpdateStarted !== 'undefined' && miUpdateStarted === true)
  };
  if (st.hasFn) { try { miRegisterObjects(); } catch (e) { st.err = String(e); } }
  if (typeof miUpdateStarted !== 'undefined') { miUpdateStarted = false; }
  st.hasObjs = (typeof miAllObjs !== 'undefined' && miAllObjs !== null);
  return st;
}"""

DIALOG_LOG = []
# The Cancel confirmation text depends on the state of the order: "...cancel the shopping basket?"
# for a plain cart, "Do you really want to cancel the order?" once the order has been to checkout.
CANCEL_DIALOG_RE = r"cancel the (shopping basket|order)"
PAGE_ERRORS = []


def on_dialog(d):
    """Accept the SIM PAC validation and basket-cancel prompts only.

    Never accept the final order-send prompt: this script must stop before
    placing/submitting the order. Unknown dialogs are dismissed and logged.
    """
    message = d.message or ""
    DIALOG_LOG.append(message)
    log.info("portal dialog (%s): %s", d.type, message)
    try:
        if re.search(CANCEL_DIALOG_RE, message, re.I):
            d.accept()
            log.info("accepted the cancel-order/basket confirmation")
        elif (re.search(r"SIMs are only available to order in PACs", message, re.I)
              and re.search(r"Do you want to Continue\?", message, re.I)):
            d.accept()
            log.info("accepted SIM PAC validation prompt; portal may continue")
        elif re.search(r"Do you really want to send the order", message, re.I):
            if ALLOW_SEND_ORDER:
                d.accept()
                log.warning("ACCEPTED the order-send confirmation (final order page was verified against the sheet)")
            else:
                d.dismiss()
                log.warning("dismissed the order-send prompt; order was NOT submitted (not at the verified final step)")
        else:
            d.dismiss()
            log.warning("dismissed unrecognized portal dialog for safety: %s", message)
    except Exception as exc:  # another listener already handled it
        log.debug("dialog already handled: %s", exc)


def operator_checkpoint(prompt, no_pause=False):
    """Require an explicit operator decision; return False to stop the remaining run."""
    if no_pause:
        return True
    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            log.warning("No operator approval received; stopping the remaining run.")
            return False
        if answer in ("", "y", "yes", "c", "continue"):
            return True
        if answer in ("s", "stop", "q", "quit"):
            return False
        print("Press Enter to continue, or type S to stop the remaining run.")


def on_page_error(exc):
    PAGE_ERRORS.append(str(exc))
    log.error("browser page error: %s", exc)


def recent_signals():
    """Last portal dialogs / JS errors - appended to error messages so a stop explains itself."""
    return f"dialogs={DIALOG_LOG[-3:]} js_errors={PAGE_ERRORS[-3:]}"


def prime_cart_page(f, what):
    """Wait for the cart document/scripts to finish loading, then initialise them."""
    deadline = time.time() + TIMEOUT
    last_state = None
    while time.time() < deadline:
        try:
            last_state = f.evaluate("""() => ({
                ready: document.readyState,
                hasForm: !!document.querySelector('form[name=\"order_positions\"]'),
                hasRegisterFn: typeof miRegisterObjects === 'function'
            })""")
            # A freshly navigated cart frame can expose the form before its legacy
            # JavaScript has loaded. Do not treat that intermediate state as ready.
            if (last_state.get("ready") == "complete"
                    and last_state.get("hasForm")
                    and last_state.get("hasRegisterFn")):
                break
        except Exception:
            # The frame may be navigating/detached; retry until the wait expires.
            pass
        f.wait_for_timeout(300)
    else:
        raise GroupError(
            f"[{what}] cart page did not finish loading within {TIMEOUT}s; "
            f"last state={last_state!r}"
        )

    try:
        st = f.evaluate(PRIME_JS)
    except Exception as exc:
        raise GroupError(f"[{what}] could not prepare the portal page scripts after load: {exc}")
    if not st.get("hasFn"):
        raise GroupError(f"[{what}] cart page loaded but miRegisterObjects() is missing")
    if not st.get("hadObjs") or st.get("wasLocked"):
        log.warning("%s: portal page was NOT ready (onload hook ran=%s, update lock stuck=%s) - primed it",
                    what, st.get("hadObjs"), st.get("wasLocked"))
    if not st.get("hasObjs"):
        raise GroupError(f"[{what}] portal page scripts could not be initialised after waiting: {st}")
    return st


def open_cart(page, what="open shopping cart", timeout=TIMEOUT):
    """Open basket; tolerate asynchronous updates without assuming a missing form means empty."""
    try:
        f = find_frame(page, "#basketlinktext", min(timeout, 10))
        f.locator("#basketlinktext").first.click()
        try:
            return wait_for_cart_form(page, timeout)
        except GroupError as e:
            log.debug("%s: click did not expose cart form: %s", what, e)
    except GroupError as e:
        log.debug("%s: basket link not immediately available: %s", what, e)
    if call_portal_js(page, "show_basket"):
        try:
            return wait_for_cart_form(page, timeout)
        except GroupError as e:
            log.debug("%s: show_basket() did not expose cart form: %s", what, e)
    f = form_frame_now(page)
    if f:
        log.info("[%s] cart form is already visible", what)
        return f
    describe_basket(page)
    raise GroupError(f"[{what}] could not open/verify shopping cart; refusing to assume it is empty")

def read_unit_value(f, idx):
    """Read PAC/EA from the cart row, preferring the selected option's visible label."""
    select = f.locator(f'select[name="units[{idx}]"]')
    if select.count():
        try:
            label = " ".join(select.locator("option:checked").inner_text(timeout=1000).split()).upper()
            match = re.search(r"\b(PAC|EA)\b", label)
            if match:
                return match.group(1)
        except Exception:
            pass
        value = select.input_value().strip().upper()
        match = re.search(r"\b(PAC|EA)\b", value)
        return match.group(1) if match else value
    text_input = f.locator(f'input[name="units[{idx}]"]')
    if text_input.count():
        value = text_input.input_value().strip().upper()
        match = re.search(r"\b(PAC|EA)\b", value)
        return match.group(1) if match else value
    return ""


def _normal_qty(value):
    """Normalize quantities like '2', '02', or '2.0' for comparisons."""
    raw = str(value).strip()
    try:
        number = float(raw)
        if number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return raw


def verify_cart_matches_group(f, g, stage):
    """Require every expected SKU/unit/qty line to exist before checkout."""
    expected = Counter((line.sku.strip(), _normal_qty(line.qty), line.unit.upper()) for line in g.lines)
    actual_rows = read_cart_rows(f)
    actual = Counter((row["sku"].strip(), _normal_qty(row["qty"]), row["unit"].upper()) for row in actual_rows)
    if expected != actual:
        missing = list((expected - actual).elements())
        unexpected = list((actual - expected).elements())
        log.error("%s: cart verification FAILED at %s; expected=%s; actual=%s", g.ref, stage, list(expected.elements()), list(actual.elements()))
        raise GroupError(
            f"{g.ref}: cart contents do not match the workbook at {stage}. "
            f"Missing expected line(s)={missing}; unexpected line(s)={unexpected}. "
            "Order left open for manual inspection; checkout was not clicked."
        )
    log.info("%s: cart verified at %s: %d line(s), SKU/unit/qty all match workbook", g.ref, stage, len(actual_rows))
    return actual_rows


def read_cart_rows(f):
    rows = []
    pos = f.locator('input[name^="pos_no["]')  # only filled rows have pos_no
    for i in range(pos.count()):
        idx = re.search(r"\[(\d+)\]", pos.nth(i).get_attribute("name")).group(1)
        rows.append({
            "idx": idx,
            "sku": f.locator(f'input[name="product[{idx}]"]').input_value().strip(),
            "qty": f.locator(f'input[name="quantity[{idx}]"]').input_value().strip(),
            "unit": read_unit_value(f, idx),
        })
    return rows


def _find_update_button(f):
    loc = f.locator('.orderItems-contrls a[onclick*="submit_refresh"]')
    if not loc.count():
        loc = f.locator('a[onclick*="submit_refresh"]').filter(
            has_text=re.compile(r"^\s*Update\s*$", re.I)
        )
    for i in range(loc.count()):
        try:
            if loc.nth(i).is_visible() and loc.nth(i).is_enabled():
                return loc.nth(i)
        except Exception:
            continue
    return None


def press_update(page, f, what, timeout=TIMEOUT):
    """Click the cart's bottom Update button and PROVE the portal reloaded the page.

    Quantities and units are set on the catalog cards before adding items; cart Update is
    only used to make the portal recalculate/validate the basket. Before each click the
    page scripts are primed (see prime_cart_page); if the click does not reload the page we
    re-prime and click once more, then stop instead of pretending it worked.
    """
    log.info("%s: clicking bottom Update; waiting up to %ss for portal response", what, timeout)
    reloaded = None
    for attempt in (1, 2):
        btn = _find_update_button(f)
        if btn is None:
            raise GroupError(f"[{what}] visible bottom Update button not found")
        prime_cart_page(f, what)
        mark_frames(page)
        btn.scroll_into_view_if_needed(timeout=5000)
        btn.click(timeout=10000)
        try:
            reloaded = wait_reloaded(page, FORM, timeout=15, what=f"{what} (attempt {attempt})")
            break
        except GroupError:
            log.warning("%s: Update click #%d did not reload the page (%s)", what, attempt, recent_signals())
            f = form_frame_now(page) or f
    if reloaded is None:
        raise GroupError(f"[{what}] clicking Update never reloaded the cart page - the portal blocked it silently. "
                         f"{recent_signals()}")
    prime_cart_page(reloaded, what + " (after reload)")  # new document: ready it for the next action

    deadline = time.time() + timeout
    last_signature = None
    stable_since = None
    last_error_text = ""
    while time.time() < deadline:
        current = form_frame_now(page)
        if current is None:
            stable_since = None
            page.wait_for_timeout(250)
            continue
        try:
            if not current.locator(FORM).is_visible():
                stable_since = None
                page.wait_for_timeout(250)
                continue

            body_text = " ".join(current.locator("body").inner_text(timeout=1500).split())
            error_match = re.search(
                r"Order quantity exceeded allocated quantity\.?|allocation[^.]{0,100}|quantity[^.]{0,100}exceed[^.]{0,100}",
                body_text, re.I
            )
            error_text = error_match.group(0) if error_match else ""
            last_error_text = error_text

            signature = (body_text[-1800:], error_text, current.url)
            now = time.time()
            if signature != last_signature:
                last_signature = signature
                stable_since = now
            stable_for = now - (stable_since or now)

            if stable_for >= 3.0:
                if error_text:
                    log.warning(
                        "%s: Update response settled with portal validation: %s. "
                        "Leaving order open for manual review.", what, error_text
                    )
                else:
                    log.info("%s: page reloaded and stable for %.1fs after Update; no allocation banner detected",
                             what, stable_for)
                wait_fully_loaded(page, what)
                prime_cart_page(current, what + " (settled)")
                return current
        except GroupError:
            raise
        except Exception as exc:
            log.debug("%s: waiting for cart Update response: %s", what, exc)
            stable_since = None
        page.wait_for_timeout(300)

    raise GroupError(
        f"[{what}] cart did not settle within {timeout}s after clicking Update; "
        f"last validation={last_error_text!r}"
    )


def clear_cart(page):
    """Clear a non-empty basket with the portal's Cancel button + confirmation.

    Cancel navigates away from the basket back to the catalog/home area, so do
    NOT wait for form[name="order_positions"] after confirming cancellation.
    Verify emptiness from the header basket summary after the page settles.
    """
    wait_home_ready(page, timeout=45, need_credit_hold=False)
    initial_text = basket_text(page)
    log.info("checking cart before order; basket text=%r", initial_text)

    f = open_cart(page, "check cart", timeout=30)
    wait_fully_loaded(page, "cart opened")
    rows = read_cart_rows(f)
    if not rows:
        log.info("cart verified empty (no populated order-position rows)")
        return f

    log.warning("cart has %d leftover line(s); cancelling entire basket: %s",
                len(rows), [(r["sku"], r["qty"], r["unit"]) for r in rows])

    # Portal markup: <a ... onclick="cancel_confirm();">Cancel</a>
    cancel = f.locator('a[onclick*="cancel_confirm"]')
    if cancel.count() == 0:
        cancel = f.get_by_role("link", name=re.compile(r"^\s*Cancel\s*$", re.I))
    if cancel.count() == 0:
        raise GroupError("Cart contains items but the portal Cancel button was not found; refusing to add a new order")

    dialog_seen = {"value": False, "message": ""}
    def handle_dialog(dialog):
        dialog_seen["value"] = True
        dialog_seen["message"] = dialog.message
        log.info("portal confirmation dialog: %s", dialog.message)
        # The legacy portal may already have a dialog listener attached. Avoid
        # trying to accept a dialog that Playwright reports as already handled.
        try:
            if re.search(CANCEL_DIALOG_RE, dialog.message, re.I):
                dialog.accept()
            else:
                log.error("Unexpected confirmation dialog; dismissing: %s", dialog.message)
                dialog.dismiss()
        except Exception as exc:
            log.warning("Dialog was already handled by another listener: %s", exc)

    try:
        prime_cart_page(f, "Cancel basket")
    except GroupError as exc:
        log.warning("could not prime the cart page before Cancel (continuing): %s", exc)

    page.on("dialog", handle_dialog)
    try:
        mark_frames(page)
        cancel.first.click(timeout=10000)
        # The confirmation is usually synchronous, but allow the portal to handle it.
        deadline = time.time() + 8
        while time.time() < deadline and not dialog_seen["value"]:
            page.wait_for_timeout(100)
    finally:
        try:
            page.remove_listener("dialog", handle_dialog)
        except Exception:
            pass

    if not dialog_seen["value"]:
        raise GroupError("Clicked Cancel but the expected 'Do you really want to cancel the shopping basket?' confirmation did not appear")
    if not re.search(CANCEL_DIALOG_RE, dialog_seen["message"], re.I):
        raise GroupError(f"Unexpected Cancel confirmation text: {dialog_seen['message']!r}")

    # Cancel returns to the catalog/home view, not the cart form. Wait for the page
    # to load and then check the header basket summary repeatedly.
    wait_home_ready(page, timeout=45, need_credit_hold=False)
    deadline = time.time() + 25
    last_text = ""
    while time.time() < deadline:
        try:
            last_text = basket_text(page)
            if cart_is_empty(last_text):
                # Confirm the summary remains empty after a short settle interval.
                page.wait_for_timeout(1200)
                last_text = basket_text(page)
                if cart_is_empty(last_text):
                    log.info("cart cleared and verified empty via basket summary: %r", last_text)
                    return
        except Exception as exc:
            log.debug("waiting for post-cancel basket summary: %s", exc)
        page.wait_for_timeout(400)

    # If the summary is inconclusive, reopen the cart and inspect actual rows.
    log.warning("basket summary did not confirm empty after Cancel (last=%r); reopening cart for verification", last_text)
    f = open_cart(page, "verify cancelled cart", timeout=25)
    left = read_cart_rows(f)
    if left:
        raise GroupError(f"Cancel was confirmed but cart still contains {len(left)} line(s): "
                         f"{[(r['sku'], r['qty'], r['unit']) for r in left]}")
    log.info("cart cleared and verified empty by reopening cart")
    # Leave the portal at the home page; the caller reopens the cart.
    wait_home_ready(page, timeout=45, need_credit_hold=False)

def update_cart(page, f):
    return press_update(page, f, "Update cart")


# -------------------------------------------------------------------- one order
NEWPOS_CHOICES = (5, 10, 15, 20, 25, 30, 40, 50)  # options of the "New Items" dropdown


def blank_item_rows(f):
    """Indexes of cart rows whose Product box is still empty, in page order."""
    rows = f.locator('input[name^="product["]').evaluate_all(
        "els => els.map(e => [e.name, e.value])")
    out = []
    for name, value in rows:
        if not value.strip():
            out.append(int(re.search(r"\[(\d+)\]", name).group(1)))
    return sorted(out)


def prepare_item_rows(page, f, g):
    """Choose '25 New Items' (more only if the order needs it) and click Update."""
    need = len(g.lines)
    if need > NEWPOS_CHOICES[-1]:
        raise GroupError(f"{g.ref}: {need} lines is more than the portal's maximum of "
                         f"{NEWPOS_CHOICES[-1]} new items per update")
    choice = 25 if need <= 25 else next(n for n in NEWPOS_CHOICES if n >= need)
    if not f.locator("#newposcount").count():
        raise GroupError(f"{g.ref}: 'New Items' dropdown (#newposcount) not found on the cart page")
    prime_cart_page(f, "New Items")
    f.select_option("#newposcount", value=str(choice))
    log.info("%s: selected %d New Items for %d sheet line(s); clicking Update", g.ref, choice, need)
    f = press_update(page, f, f"Update ({choice} new items)")
    blanks = blank_item_rows(f)
    if len(blanks) < need:
        raise GroupError(f"{g.ref}: after Update the cart shows only {len(blanks)} blank item row(s); "
                         f"{need} needed")
    log.info("%s: cart now has %d blank item rows", g.ref, len(blanks))
    return f


def fill_item_rows(page, f, g):
    """Type SKU / quantity / unit of every sheet line into its own cart row, then Update."""
    blanks = blank_item_rows(f)
    if len(blanks) < len(g.lines):
        raise GroupError(f"{g.ref}: only {len(blanks)} blank cart rows for {len(g.lines)} lines")
    targets = list(zip(blanks, g.lines))
    for idx, line in targets:
        f.fill(f'input[name="product[{idx}]"]', line.sku, timeout=10000)
        f.fill(f'input[name="quantity[{idx}]"]', str(line.qty), timeout=10000)
        f.fill(f'input[name="units[{idx}]"]', line.unit, timeout=10000)
        log.info("%s: row %s <- SKU %s  qty %s  unit %s", g.ref, idx, line.sku, line.qty, line.unit)
    # read every box back before touching Update
    bad = []
    for idx, line in targets:
        got = (f.input_value(f'input[name="product[{idx}]"]').strip(),
               _normal_qty(f.input_value(f'input[name="quantity[{idx}]"]')),
               f.input_value(f'input[name="units[{idx}]"]').strip().upper())
        want = (line.sku, _normal_qty(line.qty), line.unit)
        if got != want:
            bad.append((idx, want, got))
    if bad:
        raise GroupError(f"{g.ref}: typed values did not stick in the cart rows (row, wanted, got): {bad}")
    f = press_update(page, f, "Update cart (items entered)")
    return f


def cart_page_messages(f):
    out = []
    for line in f.locator("body").inner_text(timeout=3000).splitlines():
        line = line.strip()
        if line and re.search(r"exceeded|allocat|error|invalid|must|cannot|unable|not available|please", line, re.I):
            out.append(line[:200])
    return out[:6]


def change_deliver_to(page, f, g, value):
    """Select Deliver To and PROVE the portal refreshed the order form.

    The select's onchange runs changeHeaderDeliverTo() -> submit_refresh(). Previously, when
    that did nothing, the script waited 35s, saw the (unchanged) form still showing the chosen
    value and declared READY - a silent failure. Now: prime the page, select, require a real
    reload; if none, call the portal handler directly once; if still none, stop.
    """
    for attempt in (1, 2):
        prime_cart_page(f, "Deliver To")
        mark_frames(page)
        if attempt == 1:
            f.select_option("#headerShipTo", value=value)
        else:
            # selecting the same value again would not fire 'change', so call the handler itself
            f.evaluate("() => setTimeout(() => changeHeaderDeliverTo(), 0)")
        try:
            new_f = wait_reloaded(page, FORM, timeout=25, what=f"Deliver To refresh (attempt {attempt})")
            wait_fully_loaded(page, "Deliver To refresh")
            prime_cart_page(new_f, "after Deliver To refresh")
            return new_f
        except GroupError:
            log.warning("%s: Deliver To attempt %d: the page did not reload (%s)", g.ref, attempt, recent_signals())
            f = form_frame_now(page) or f
    raise GroupError("Deliver To was selected but the portal never refreshed the order form "
                     f"(order is NOT ready). {recent_signals()}")


def _match_rows_to_lines(rows, lines):
    """Pair cart rows with sheet lines. Returns (pairs, missing_lines, extra_rows).
    Pass 1 pairs identical SKU+unit; pass 2 pairs leftovers of the same SKU (wrong unit)."""
    rows, lines, pairs = list(rows), list(lines), []
    for line in list(lines):
        for r in rows:
            if r["sku"] == line.sku and r["unit"].upper() == line.unit:
                pairs.append((r, line))
                rows.remove(r)
                lines.remove(line)
                break
    for line in list(lines):
        for r in rows:
            if r["sku"] == line.sku:
                pairs.append((r, line))
                rows.remove(r)
                lines.remove(line)
                break
    return pairs, lines, rows


def _describe_diff(wrong, missing, extra):
    parts = []
    for r, line in wrong:
        parts.append(f"SKU {line.sku}: cart has {r['qty']} {r['unit']}, sheet says {line.qty} {line.unit}")
    for line in missing:
        parts.append(f"SKU {line.sku}: missing from cart (sheet: {line.qty} {line.unit})")
    for r in extra:
        parts.append(f"SKU {r['sku']}: in cart ({r['qty']} {r['unit']}) but not in the sheet")
    return "; ".join(parts)


def reconcile_cart(page, f, g, stage, max_rounds=3):
    """Compare the live cart with the sheet. Fix anything wrong (unit, quantity, missing or extra
    lines), click Update, and compare again - up to max_rounds correction rounds, then stop.
    Returns (cart frame, True if any correction was made)."""
    corrected = False
    for rnd in range(1, max_rounds + 2):
        f = form_frame_now(page) or f
        pairs, missing, extra = _match_rows_to_lines(read_cart_rows(f), g.lines)
        wrong = [(r, line) for r, line in pairs
                 if _normal_qty(r["qty"]) != _normal_qty(line.qty) or r["unit"].upper() != line.unit]
        if not (wrong or missing or extra):
            log.info("%s: %s: cart matches the sheet (%d line(s))%s", g.ref, stage, len(pairs),
                     f" after {rnd - 1} correction round(s)" if corrected else "")
            return f, corrected
        diff = _describe_diff(wrong, missing, extra)
        if rnd > max_rounds:
            raise GroupError(f"{g.ref}: {stage}: cart still differs from the sheet after {max_rounds} "
                             f"correction rounds - the portal keeps changing it (check allocation / pack "
                             f"rules). Differences: {diff}. {recent_signals()}")
        log.warning("%s: %s: cart differs from the sheet (round %d) - correcting: %s", g.ref, stage, rnd, diff)
        prime_cart_page(f, f"{stage} correction")
        for r, line in wrong:
            f.fill(f'input[name="units[{r["idx"]}]"]', line.unit, timeout=10000)
            f.fill(f'input[name="quantity[{r["idx"]}]"]', str(line.qty), timeout=10000)
        if missing:
            blanks = blank_item_rows(f)
            if len(blanks) < len(missing):
                log.info("%s: not enough blank rows for %d missing line(s); asking for 25 more", g.ref, len(missing))
                f.select_option("#newposcount", value="25")
                f = press_update(page, f, "Update (more new items)")
                blanks = blank_item_rows(f)
                if len(blanks) < len(missing):
                    raise GroupError(f"{g.ref}: {stage}: no blank rows left for missing line(s): {diff}")
            for idx, line in zip(blanks, missing):
                f.fill(f'input[name="product[{idx}]"]', line.sku, timeout=10000)
                f.fill(f'input[name="quantity[{idx}]"]', str(line.qty), timeout=10000)
                f.fill(f'input[name="units[{idx}]"]', line.unit, timeout=10000)
        for r in extra:
            box = f.locator(f'#row_{r["idx"]} td.delete input[type="checkbox"]')
            if box.count() != 1:
                raise GroupError(f"{g.ref}: {stage}: SKU {r['sku']} is in the cart but not in the sheet and its "
                                 f"delete checkbox was not found - remove it by hand. Differences: {diff}")
            box.check(timeout=5000)
        f = press_update(page, f, f"Update ({stage}, correction round {rnd})")
        corrected = True
    raise GroupError(f"{g.ref}: {stage}: reconcile loop ended unexpectedly")


def ensure_header(page, f, g, ship_value):
    """After a correction Update, make sure the header fields are still what the sheet says."""
    f = form_frame_now(page) or f
    if f.input_value("#headerShipTo") != ship_value:
        raise GroupError(f"{g.ref}: Deliver-To changed after the correction Update "
                         f"(expected option {ship_value!r}, got {f.input_value('#headerShipTo')!r})")
    if f.input_value("#poNumber") != g.ref:
        log.warning("%s: reference number was cleared by the correction Update; restoring", g.ref)
        f.fill("#poNumber", g.ref)
    if f.input_value("#headerDescription") != HEADER_DESCRIPTION:
        log.warning("%s: description was cleared by the correction Update; restoring", g.ref)
        f.fill("#headerDescription", HEADER_DESCRIPTION)
    if f.input_value("#shipCond") != SHIP_COND[g.shipping]:
        log.warning("%s: shipping method was cleared by the correction Update; restoring", g.ref)
        f.select_option("#shipCond", value=SHIP_COND[g.shipping])
    return f


# ------------------------------------------------------- operator-assisted recovery
def snapshot(page, ref, label, attempt):
    """Screenshot + frame HTML dump for one failure; never raises."""
    logdir = LOGDIR or (BASE_DIR / "logs")
    try:
        logdir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    slug = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")[:30]
    tag = f"{ref}_{slug}_try{attempt}_{STAMP}"
    shot = logdir / f"{tag}.png"
    try:
        page.screenshot(path=str(shot), full_page=True, timeout=10000)
        log.info("%s: screenshot saved: %s", ref, shot)
    except Exception as exc:
        log.warning("%s: screenshot failed (%s: %s)", ref, type(exc).__name__, exc)
        shot = None
    try:
        dump_frames(page, logdir, tag)
    except Exception as exc:
        log.warning("%s: frame dump failed (%s: %s)", ref, type(exc).__name__, exc)
    return shot


def ask_operator_recovery(ref, step, err, shot):
    """Show the problem and ask what to do. Returns 'recheck', 'redo', 'skip' or 'stop'."""
    if NO_PAUSE:
        log.warning("%s: --no-pause is set, cannot ask the operator; skipping this order", ref)
        return "skip"
    text = f"{type(err).__name__}: {err}"
    print("\n" + "=" * 78)
    print(f"[{ref}] PROBLEM in step: {step}")
    print(text[:900] + (" ..." if len(text) > 900 else ""))
    if shot:
        print(f"Screenshot: {shot}")
    print("-" * 78)
    print("What now?  The browser is left open exactly as it is.")
    print("  Enter = I fixed it / entered it by hand in the browser -> re-check and continue from here")
    print("  R     = redo this step automatically")
    print("  O     = process this whole order again from the beginning (clears the cart first)")
    print("  K     = skip this order and go to the next one")
    print("  S     = stop the whole run")
    print("=" * 78)
    while True:
        try:
            ans = input("Your choice [Enter/R/O/K/S]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            log.warning("%s: no operator input available; stopping the run", ref)
            return "stop"
        if ans in ("", "c", "y", "continue", "fixed"):
            return "recheck"
        if ans in ("r", "redo", "retry"):
            return "redo"
        if ans in ("o", "again", "restart"):
            return "restart"
        if ans in ("k", "skip"):
            return "skip"
        if ans in ("s", "stop", "q", "quit"):
            return "stop"
        print("Please type Enter, R, O, K or S.")


def run_stage(page, g, step, fn, resume_fn=None):
    """Run one step of an order. If it fails, keep the browser as it is, log the details,
    ask the operator what to do, and carry on from this step (never abort the whole order
    on the first problem). fn runs first; after the operator says 'fixed' resume_fn (a
    re-check that does not redo finished work) runs, or fn again if there is none."""
    attempt, use_resume = 0, False
    while True:
        attempt += 1
        log.info("%s: >>> %s%s", g.ref, step, f" (attempt {attempt})" if attempt > 1 else "")
        try:
            result = (resume_fn if (use_resume and resume_fn) else fn)()
            if attempt > 1:
                log.info("%s: step '%s' completed after operator help", g.ref, step)
                EVENTS.setdefault(g.ref, []).append(f"'{step}' fixed with operator help")
            return result
        except (SkipOrder, StopRun, RestartOrder):
            raise
        except Exception as exc:
            try:
                closed = page.is_closed()
            except Exception:
                closed = True
            if closed or "has been closed" in str(exc):
                log.critical("%s: browser window/page was closed during '%s'", g.ref, step)
                raise StopRun("the browser window was closed")
            log.error("%s: PROBLEM in step '%s' (attempt %d): %s: %s",
                      g.ref, step, attempt, type(exc).__name__, exc)
            log.debug("%s: traceback for step '%s'", g.ref, step, exc_info=True)
            shot = snapshot(page, g.ref, step, attempt)
            EVENTS.setdefault(g.ref, []).append(f"'{step}' problem: {str(exc)[:200]}")
            choice = ask_operator_recovery(g.ref, step, exc, shot)
            log.info("%s: operator chose '%s' for step '%s'", g.ref, choice, step)
            if choice == "restart":
                raise RestartOrder(f"operator asked to process the order again after a problem in '{step}'")
            if choice == "skip":
                raise SkipOrder(f"skipped by operator at step '{step}': {str(exc)[:300]}")
            if choice == "stop":
                raise StopRun(f"stopped by operator at step '{step}'")
            use_resume = (choice == "recheck")


def _cart_frame(page):
    f = form_frame_now(page)
    if f is None:
        f = open_cart(page, "open cart", timeout=30)
    return f


def stage_open_cart(page):
    f = clear_cart(page)  # returns the open cart frame if the cart was already empty
    if f is None:
        f = open_cart(page, "open cart after clearing", timeout=30)
    wait_fully_loaded(page, "cart opened")
    return form_frame_now(page) or f


def stage_enter_items(page, g):
    f = _cart_frame(page)
    f = prepare_item_rows(page, f, g)
    f = fill_item_rows(page, f, g)
    f, _ = reconcile_cart(page, f, g, "after first Update")
    log.info("%s: cart rows entered, Update done and verified; proceeding to order header", g.ref)
    return f


def recheck_items(page, g):
    """After the operator touched the cart by hand: compare with the sheet and fix leftovers."""
    f = _cart_frame(page)
    f, _ = reconcile_cart(page, f, g, "re-check after manual fix")
    return f


def stage_header(page, g):
    """Fill the header and verify it. Safe to run again: it only changes what is not right yet.
    Returns (Deliver-To label, Deliver-To option value)."""
    f = _cart_frame(page)
    # IMPORTANT: changing Deliver To fires the portal's changeHeaderDeliverTo(), which calls
    # submit_refresh() and reloads the order form. Set the other fields first, then change
    # Deliver To last and wait for the refreshed form.
    f.fill("#poNumber", g.ref)
    f.fill("#headerDescription", HEADER_DESCRIPTION)
    f.select_option("#shipCond", value=SHIP_COND[g.shipping])

    opts = [(o.get_attribute("value"), " ".join(o.inner_text().split()))
            for o in f.locator("#headerShipTo option").all()]

    def read_current():
        cf = form_frame_now(page) or f
        val = cf.input_value("#headerShipTo")
        lab = " ".join(cf.locator("#headerShipTo option:checked").inner_text().split())
        return val, lab

    value, text = pick_ship_to(opts, g.address, read_current=read_current)
    f = form_frame_now(page) or f
    if f.input_value("#headerShipTo") == value:
        log.info("%s: Deliver To already set to '%s'; no refresh needed", g.ref, text)
    else:
        log.info("%s: selecting Deliver To '%s'; portal refresh is expected", g.ref, text)
        f = change_deliver_to(page, f, g, value)

    # Verify the server-rendered values after the refresh. Never report READY based only on
    # the requested Excel values.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if f.input_value("#headerShipTo") == value:
                break
        except Exception:
            pass
        page.wait_for_timeout(250)
        f = wait_for_cart_form(page, timeout=5)
    actual_address_value = f.input_value("#headerShipTo")
    if actual_address_value != value:
        raise GroupError(f"Deliver-To did not persist after refresh: expected {value!r}, got {actual_address_value!r}")

    if f.input_value("#poNumber") != g.ref:
        log.warning("%s: reference number did not persist after address refresh; restoring it", g.ref)
        f.fill("#poNumber", g.ref)
    if f.input_value("#headerDescription") != HEADER_DESCRIPTION:
        log.warning("%s: description did not persist after address refresh; restoring it", g.ref)
        f.fill("#headerDescription", HEADER_DESCRIPTION)
    if f.input_value("#shipCond") != SHIP_COND[g.shipping]:
        log.warning("%s: shipping method did not persist after address refresh; restoring it", g.ref)
        f.select_option("#shipCond", value=SHIP_COND[g.shipping])

    if f.locator("#enableDisableShipTo").count() and f.locator("#enableDisableShipTo").is_checked():
        log.warning("%s: 'Enable line item Deliver To' is ticked - line items may override the header address", g.ref)

    actual_ref = f.input_value("#poNumber")
    actual_description = f.input_value("#headerDescription")
    actual_ship_value = f.input_value("#shipCond")
    actual_ship_label = (f.locator(f'#shipCond option[value="{actual_ship_value}"]').inner_text().strip()
                         if actual_ship_value else "(not selected)")
    if actual_ref != g.ref:
        raise GroupError(f"Reference number mismatch after refresh: expected {g.ref!r}, got {actual_ref!r}")
    if actual_description != HEADER_DESCRIPTION:
        raise GroupError(f"Description mismatch after refresh: expected {HEADER_DESCRIPTION!r}, got {actual_description!r}")
    if actual_ship_value != SHIP_COND[g.shipping]:
        raise GroupError(f"Shipping method mismatch after refresh: expected {g.shipping} ({SHIP_COND[g.shipping]}), "
                         f"got {actual_ship_value!r} ({actual_ship_label})")
    log.info("%s: verified live header values after refresh: ref=%s, deliver-to='%s' (%s), shipping='%s' (%s)",
             g.ref, actual_ref, text, actual_address_value, actual_ship_label, actual_ship_value)
    ORDER_CTX[g.ref] = {"value": value, "text": text}
    return text, value


def stage_final_check(page, g):
    """Cart vs sheet one last time (correcting and re-Updating if needed), header still intact."""
    ctx = ORDER_CTX.get(g.ref) or {}
    f = _cart_frame(page)
    f, corrected = reconcile_cart(page, f, g, "final check before checkout")
    if corrected and ctx.get("value"):
        f = ensure_header(page, f, g, ctx["value"])
        verify_cart_matches_group(f, g, "after final correction")
    totals = " | ".join(" ".join(t.split()) for t in f.locator(".priceInfo tr").all_inner_texts() if t.strip())
    log.info("%s: READY  deliver-to '%s'  %s  %s", g.ref, ctx.get("text", "?"), g.shipping, totals)
    return f


def build_order(page, g):
    """Build one order. Every step is wrapped so a problem pauses for the operator instead of
    failing the order; returns the Deliver-To label."""
    run_stage(page, g, "open cart / clear old items", lambda: stage_open_cart(page))
    run_stage(page, g, "enter items in cart",
              lambda: stage_enter_items(page, g), lambda: recheck_items(page, g))
    text, _value = run_stage(page, g, "order header (reference, address, shipping)",
                             lambda: stage_header(page, g))
    run_stage(page, g, "final check before checkout", lambda: stage_final_check(page, g))
    return text


def click_go_to_checkout(page, g):
    """Click the cart's Go To Checkout link once; never submit the final order.

    The legacy portal uses inline JavaScript: if(packcheck(this))
    zsubmit_simulate('order','ZMSS','0202049767'). Playwright's normal click
    triggers that same handler. We deliberately do not bypass packcheck or call
    zsubmit_simulate directly, because pack validation must run first.
    """
    selector = '.orderItems-contrls a[onclick*="zsubmit_simulate"]'
    checkout = None
    owner_frame = None
    for frame in list(page.frames):
        try:
            links = frame.locator(selector)
            for i in range(links.count()):
                link = links.nth(i)
                if not link.is_visible():
                    continue
                label = " ".join(link.inner_text(timeout=1000).split()).casefold()
                if label == "go to checkout":
                    checkout = link
                    owner_frame = frame
                    break
            if checkout is not None:
                break
        except Exception:
            continue

    if checkout is None:
        raise GroupError(f"{g.ref}: visible 'Go To Checkout' link was not found; order left on cart page")

    def left_cart_page():
        try:
            if owner_frame.is_detached():
                return "cart frame replaced"
            if not owner_frame.evaluate("!!window.__pw"):
                return "cart frame reloaded"
            if not owner_frame.locator(FORM).count():
                return "cart form gone"
        except Exception:
            return "cart frame navigated"
        return None

    def still_on_cart_page():
        """After a reload: is the basket (with its Go To Checkout link) showing again?"""
        for fr in list(page.frames):
            try:
                if fr.locator(FORM).count() and fr.locator('a[onclick*="zsubmit_simulate"]').count():
                    return fr
            except Exception:
                continue
        return None

    how = None
    for attempt in (1, 2):
        prime_cart_page(owner_frame, "Go To Checkout")
        mark_frames(page)
        log.info("%s: clicking Go To Checkout (attempt %d; final order will NOT be submitted by this script)",
                 g.ref, attempt)
        checkout.scroll_into_view_if_needed(timeout=5000)
        checkout.click(timeout=10000)
        end = time.time() + 25
        while time.time() < end:
            how = left_cart_page()
            if how:
                break
            page.wait_for_timeout(300)
        if how:
            break
        log.warning("%s: Go To Checkout attempt %d: the page did not move (%s)", g.ref, attempt, recent_signals())

    if not how:
        raise GroupError("Go To Checkout was clicked twice but the portal never left the cart page "
                         f"(blocked silently or by validation). {recent_signals()}")

    wait_fully_loaded(page, "after Go To Checkout")
    back = still_on_cart_page()
    if back is not None:
        try:
            msgs = cart_page_messages(back)
        except Exception:
            msgs = []
        raise GroupError("Go To Checkout reloaded the basket instead of moving on. "
                         f"Portal messages: {msgs or 'none found'}. {recent_signals()}")

    texts = []
    for frame in list(page.frames):
        try:
            body = " ".join(frame.locator("body").inner_text(timeout=1200).split())
            if body:
                texts.append(body[:300])
        except Exception:
            continue
    log.info("%s: Go To Checkout moved the page (%s). frames=%s", g.ref, how, [fr.url for fr in page.frames])
    log.info("%s: page text after checkout click: %s", g.ref, " | ".join(texts)[-900:])
    return f"checkout page reached ({how})"


# ------------------------------------------------------------------------ login
# Stable internal market IDs should not change when a market is renamed in the
# login workbook. Keep ARIZONA as the project/config/folder ID, while allowing
# PHOENIX as the current display/login name.
MARKET_LOGIN_ALIASES = {
    "ARIZONA": ("PHOENIX", "ARIZONA"),  # preferred login name, then legacy name
    "PHOENIX": ("PHOENIX", "ARIZONA"),
}


def get_creds(path, market):
    """Find credentials by login-workbook name without changing the internal market ID.

    For the ARIZONA -> PHOENIX rename, PHOENIX is preferred. ARIZONA is accepted
    as a backward-compatible fallback. If the preferred name appears more than
    once, fail rather than selecting an arbitrary credentials row.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.worksheets[0]
        head = [clean(c.value).lower() for c in ws[1]]

        def col(*keys):
            for i, h in enumerate(head):
                if any(k in h for k in keys):
                    return i
            sys.exit(f"{path}: no column matching {keys}. Headers: {head}")

        mi, ui, pi = col("market"), col("user", "login", "id"), col("pass")
        requested = clean(market).upper()
        accepted_names = MARKET_LOGIN_ALIASES.get(requested, (requested,))

        rows_by_name = {name: [] for name in accepted_names}
        for row in ws.iter_rows(min_row=2, values_only=True):
            row_market = clean(row[mi]).upper()
            if row_market in rows_by_name:
                rows_by_name[row_market].append(row)

        # Use the first listed name as the preferred login-workbook name.
        for login_name in accepted_names:
            matches = rows_by_name[login_name]
            if len(matches) > 1:
                sys.exit(
                    f"{path}: found {len(matches)} login rows for market "
                    f"{login_name}; keep exactly one row to avoid using the wrong account"
                )
            if len(matches) == 1:
                if login_name != requested:
                    log.info(
                        "market login alias: internal market %s uses login-workbook name %s",
                        requested, login_name
                    )
                return clean(matches[0][ui]), clean(matches[0][pi])

        sys.exit(
            f"{path}: no login row for market {requested}. "
            f"Accepted login names: {', '.join(accepted_names)}"
        )
    finally:
        wb.close()


def accept_terms(f):
    """Login page refuses to submit until the Terms & Conditions box is ticked."""
    boxes = f.locator('input[type="checkbox"]')
    n = boxes.count()
    if n == 0:
        return
    pick = None
    for i in range(n):
        b = boxes.nth(i)
        ident = " ".join(filter(None, [b.get_attribute("id"), b.get_attribute("name")]))
        if re.search(r"term|agree|accept|condition|tnc", ident, re.I):
            pick = b
            break
    if pick is None and n == 1:
        pick = boxes.first
    if pick is None:
        found = [(boxes.nth(i).get_attribute("id"), boxes.nth(i).get_attribute("name")) for i in range(n)]
        raise RuntimeError(f"login page has {n} checkboxes, none looks like Terms & Conditions: {found}")
    if not pick.is_checked():
        pick.check(force=True)
    log.info("Terms & Conditions box ticked")


def wait_home_ready(page, timeout=90, need_credit_hold=True):
    """Wait until the portal page is completely loaded.

    At login (need_credit_hold=True) the loaded-proof is the Credit Hold Notification box
    (#credithold-tab-content) having content - what it says does not matter, it only proves
    the home page finished loading. The shopping-cart link must also be there. Between orders
    (need_credit_hold=False) only the cart link is required, because the portal may not be on
    the home page any more.
    """
    deadline = time.time() + timeout
    last_state = "not detected"
    while time.time() < deadline:
        basket_ok = credit_ok = False
        credit_text = ""
        for f in list(page.frames):
            try:
                if f.locator("#basketlinktext").count() and f.locator("#basketlinktext").first.is_visible():
                    basket_ok = True
                if need_credit_hold:
                    box = f.locator("#credithold-tab-content")
                    if box.count():
                        txt = " ".join((box.first.text_content(timeout=1000) or "").split())
                        if txt:
                            credit_ok = True
                            credit_text = txt
            except Exception:
                continue
        last_state = f"basket={basket_ok}, credit_hold={credit_ok if need_credit_hold else 'not required'}"
        if basket_ok and (credit_ok or not need_credit_hold):
            wait_fully_loaded(page, "home page")
            if need_credit_hold:
                log.info("home page fully loaded (Credit Hold tab loaded: %r)", credit_text[:80])
            else:
                log.info("portal page loaded (shopping cart link visible)")
            return
        page.wait_for_timeout(400)
    raise GroupError(f"Timed out waiting for the portal page to finish loading ({last_state})")


def wait_for_cart_form(page, timeout=25):
    """AJAX/frame-safe wait; the cart can load inside an existing frame."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        f = form_frame_now(page)
        if f is not None:
            try:
                if f.locator(FORM).is_visible():
                    return f
            except Exception:
                pass
        page.wait_for_timeout(250)
    raise GroupError(f"shopping-cart form {FORM!r} did not become visible within {timeout}s")


def login(page, user, pw):
    page.goto(PORTAL_URL)
    f = find_frame(page, "#userid")
    f.fill("#userid", user)
    f.fill("#password", pw)
    accept_terms(f)
    f.press("#password", "Enter")
    find_frame(page, "#credithold-tab-content", timeout=90)  # home page landing frame
    wait_home_ready(page, timeout=90)


def dump_frames(page, logdir, tag):
    """Save every accessible frame independently; one detached frame must not stop the dump."""
    for i, f in enumerate(list(page.frames)):
        try:
            log.info("frame %d: %s", i, f.url)
        except Exception:
            log.warning("frame %d: URL unavailable (frame detached)", i)
        try:
            content = f.content()
            (logdir / f"{tag}_frame{i}.html").write_text(content, encoding="utf-8")
        except Exception:
            log.debug("frame %d HTML dump failed", i, exc_info=True)



def login_with_recovery(page, user, pw, market):
    """Log in; if that fails, let the operator log in by hand (or retry) instead of giving up."""
    attempt, manual = 0, False
    while True:
        attempt += 1
        try:
            if manual:
                log.info("%s: checking that the portal home page is loaded after manual login", market)
                wait_home_ready(page, timeout=90)
            else:
                login(page, user, pw)
            return
        except Exception as exc:
            try:
                closed = page.is_closed()
            except Exception:
                closed = True
            if closed or "has been closed" in str(exc):
                raise StopRun("the browser window was closed")
            log.error("%s: login problem (attempt %d): %s: %s", market, attempt, type(exc).__name__, exc)
            log.debug("%s: login traceback", market, exc_info=True)
            shot = snapshot(page, f"LOGIN_{market}", "login", attempt)
            if NO_PAUSE:
                raise StopRun(f"login failed for {market}: {exc}")
            print("\n" + "=" * 78)
            print(f"[{market}] LOGIN PROBLEM: {type(exc).__name__}: {str(exc)[:600]}")
            if shot:
                print(f"Screenshot: {shot}")
            print("  Enter = I logged in myself in the browser -> re-check the home page and continue")
            print("  R     = retry the automatic login")
            print("  S     = skip this market")
            print("=" * 78)
            while True:
                try:
                    ans = input("Your choice [Enter/R/S]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    raise StopRun("input closed during login recovery")
                if ans in ("", "c", "y"):
                    manual = True
                    break
                if ans in ("r", "redo", "retry"):
                    manual = False
                    break
                if ans in ("s", "stop", "k", "skip"):
                    raise StopRun(f"operator skipped market {market} after a login problem")
                print("Please type Enter, R or S.")


def cancel_current_order_cart(page, g):
    """Cancel the current order's cart and verify it is empty before continuing.

    This is used only when the operator chooses Skip at the pre-checkout gate.
    It does not click Go To Checkout or any final-submit control.
    """
    cart_frame = None
    for frame in list(page.frames):
        try:
            if frame.locator('form[name="order_positions"]').count() or frame.locator('input[name^="product["]').count():
                cart_frame = frame
                break
        except Exception:
            continue

    if cart_frame is None:
        raise GroupError(f"{g.ref}: cannot find the current cart; refusing to skip without clearing it")

    rows = read_cart_rows(cart_frame)
    if not rows:
        log.info("%s: cart already empty while skipping", g.ref)
        wait_home_ready(page, timeout=45, need_credit_hold=False)
        return

    cancel = cart_frame.locator('a[onclick*="cancel_confirm"]')
    if cancel.count() == 0:
        cancel = cart_frame.get_by_role("link", name=re.compile(r"^\s*Cancel\s*$", re.I))
    if cancel.count() == 0:
        raise GroupError(f"{g.ref}: cart contains items but the portal Cancel button was not found")

    dialog_seen = {"value": False, "message": ""}

    def handle_skip_dialog(dialog):
        dialog_seen["value"] = True
        dialog_seen["message"] = dialog.message or ""
        try:
            if re.search(CANCEL_DIALOG_RE, dialog_seen["message"], re.I):
                dialog.accept()
            else:
                dialog.dismiss()
        except Exception as exc:  # the global dialog handler may already have answered it
            log.debug("skip-cancel dialog already handled: %s", exc)

    page.on("dialog", handle_skip_dialog)
    try:
        try:
            prime_cart_page(cart_frame, f"Skip order {g.ref}")
        except GroupError as exc:
            log.warning("%s: could not prime cart before skip cancellation: %s", g.ref, exc)
        mark_frames(page)
        cancel.first.click(timeout=10000)
        deadline = time.time() + 8
        while time.time() < deadline and not dialog_seen["value"]:
            page.wait_for_timeout(100)
    finally:
        try:
            page.remove_listener("dialog", handle_skip_dialog)
        except Exception:
            pass

    if not dialog_seen["value"] or not re.search(CANCEL_DIALOG_RE, dialog_seen["message"], re.I):
        raise GroupError(
            f"{g.ref}: expected basket-cancellation confirmation was not received; "
            "stopping to avoid carrying this order into the next one"
        )

    wait_home_ready(page, timeout=45, need_credit_hold=False)
    deadline = time.time() + 25
    last_text = ""
    while time.time() < deadline:
        try:
            last_text = basket_text(page)
            if cart_is_empty(last_text):
                page.wait_for_timeout(1000)
                last_text = basket_text(page)
                if cart_is_empty(last_text):
                    log.info("%s: skipped order; cart cancellation verified (%r)", g.ref, last_text)
                    return
        except Exception as exc:
            log.debug("%s: waiting for empty basket after skip: %s", g.ref, exc)
        page.wait_for_timeout(400)

    raise GroupError(
        f"{g.ref}: Cancel was clicked but an empty basket could not be verified "
        f"(basket summary: {last_text!r}); stopping before the next order"
    )


def pre_checkout_prompt(page, g):
    """Human gate before Go To Checkout. Returns 'go', 'skip' or 'stop'.
    R re-checks the cart/header against the sheet (useful after you edited something by hand)."""
    if NO_PAUSE:
        return "go"
    while True:
        try:
            ans = input(
                f"\n[{g.ref}] Order built and validated. Review the browser/cart.\n"
                + ("  Enter = Go To Checkout, check the final order page (--verify-only: no order is placed)\n"
                   if VERIFY_ONLY else
                   "  Enter = Go To Checkout, check the final order page and PLACE THE ORDER if it matches\n") +
                "  R     = re-check cart and header against the sheet first (after you changed something)\n"
                "  O     = process this whole order again from the beginning\n"
                "  K     = skip this order (Cancels the cart, then continues)    S = stop the run\n"
                "Your choice [Enter/R/O/K/S]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "stop"
        if ans in ("", "g", "go"):
            return "go"
        if ans in ("o", "again", "restart"):
            return "restart"
        if ans in ("k", "skip"):
            return "skip"
        if ans in ("s", "stop", "q"):
            return "stop"
        if ans in ("r", "recheck", "check"):
            run_stage(page, g, "re-check before checkout", lambda: stage_final_check(page, g))
            continue
        print("Please type Enter, R, O, K or S.")


def ask_unexpected_error(g, err):
    """For an error outside the normal steps: process this order again, next order, or stop."""
    if NO_PAUSE:
        log.warning("%s: --no-pause is set; moving on to the next order", g.ref)
        return "next"
    print("\n" + "=" * 78)
    print(f"[{g.ref}] UNEXPECTED ERROR: {type(err).__name__}: {str(err)[:700]}")
    print("Details and traceback are in the log file. The browser is left as it is.")
    print("  O     = process this order again from the beginning")
    print("  Enter = continue with the NEXT order")
    print("  S     = stop the run")
    print("=" * 78)
    while True:
        try:
            ans = input("Your choice [O/Enter/S]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "stop"
        if ans in ("o", "again", "restart", "r"):
            return "again"
        if ans in ("", "n", "next", "k"):
            return "next"
        if ans in ("s", "stop", "q"):
            return "stop"
        print("Please type O, Enter or S.")


# ------------------------------------------- checkout -> payment -> final order page -> Order
FINAL_PAGE_JS = r"""
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const out = {ref: null, description: null, delivery: null, shipping: null, payment: null, rows: [], totals: {}};
  const idCells = Array.from(document.querySelectorAll('td.identifier'));
  const after = label => {
    const c = idCells.find(c => clean(c.textContent).toLowerCase().startsWith(label));
    return c && c.nextElementSibling ? clean(c.nextElementSibling.textContent) : null;
  };
  out.ref = after('your reference number');
  out.description = after('your description');
  const boldCell = label => idCells.find(c => c.querySelector('b') &&
      clean(c.querySelector('b').textContent).toLowerCase().startsWith(label));
  const strip = (cell, label) => cell ? clean(cell.textContent).replace(new RegExp('^' + label, 'i'), '').trim() : null;
  out.delivery = strip(boldCell('delivery address'), 'delivery address:');
  out.shipping = strip(boldCell('shipping method'), 'shipping method:');
  const pay = document.querySelector('.header-payment td.value');
  out.payment = pay ? clean(pay.textContent) : null;
  for (const tr of document.querySelectorAll('tr[id^="row_"]')) {
    const id = tr.id.slice(4);
    const cell = sel => clean((tr.querySelector(sel) || {}).textContent);
    const m = cell('td.qty').match(/^(\d+)\s*([A-Za-z]+)?/);
    const det = document.getElementById('rowdetail_' + id);
    const dv = det ? det.querySelector('td.value') : null;
    out.rows.push({item: cell('td.item'), sku: cell('td.product'),
                   qty: m ? parseInt(m[1], 10) : null, unit: m && m[2] ? m[2].toUpperCase() : null,
                   desc: cell('td.desc'), price: cell('td.price'), delivery: dv ? clean(dv.textContent) : null});
  }
  for (const tr of document.querySelectorAll('.priceInfo tr')) {
    const tds = tr.querySelectorAll('td');
    if (tds.length >= 2) out.totals[clean(tds[0].textContent).replace(/:$/, '')] = clean(tds[1].textContent);
  }
  return out;
}
"""


def detect_checkout_page(page):
    """Which portal page is showing? Returns (kind, frame): final | payment | cart | other."""
    frames = list(page.frames)
    probes = (("final", 'a[onclick*="sendPressed"]'),
              ("payment", '#buttonPaySave, input[name="paytype"]'),
              ("cart", None))
    for kind, selector in probes:
        for fr in frames:
            try:
                if kind == "cart":
                    if fr.locator(FORM).count() and fr.locator('input[name^="product["]').count():
                        return kind, fr
                elif fr.locator(selector).count():
                    return kind, fr
            except Exception:
                continue
    return "other", None


def wait_for_checkout_page(page, timeout=45):
    """Wait for any recognised page to finish loading; returns (kind, frame) or ("other", None)."""
    end = time.time() + timeout
    while time.time() < end:
        kind, fr = detect_checkout_page(page)
        if kind != "other":
            wait_fully_loaded(page, f"{kind} page")
            kind, fr = detect_checkout_page(page)  # frames can be replaced while loading
            if kind != "other":
                return kind, fr
        page.wait_for_timeout(400)
    return "other", None


def payment_checkout(page, g, fr):
    """Page 2: confirm payment = Terms (never Credit Card: 2.5% surcharge), click Checkout."""
    terms, card = fr.locator("#paytype_1"), fr.locator("#paytype_3")
    if not terms.count():
        raise GroupError(f"{g.ref}: payment page: the 'Terms' payment option was not found")
    if card.count() and card.is_checked():
        raise GroupError(f"{g.ref}: payment page: Credit Card is selected (2.5% surcharge). "
                         "Select 'Terms' and continue")
    if not terms.is_checked():
        log.warning("%s: payment page: 'Terms' was not selected; selecting it", g.ref)
        terms.check(timeout=5000)
    if not terms.is_checked() or (card.count() and card.is_checked()):
        raise GroupError(f"{g.ref}: payment page: could not select the 'Terms' payment option")
    log.info("%s: payment page: 'Terms' (invoice) is selected; clicking Checkout", g.ref)

    moved = False
    for attempt in (1, 2):
        kind, fr = detect_checkout_page(page)
        if kind != "payment":
            moved = True
            break
        mark_frames(page)
        fr.locator("#buttonPaySave").first.click(timeout=10000)
        end = time.time() + (45 if attempt == 1 else 60)
        while time.time() < end:
            if detect_checkout_page(page)[0] != "payment":
                moved = True
                break
            page.wait_for_timeout(400)
        if moved:
            break
        try:
            msgs = " ".join(fr.locator(".header-msg-area").inner_text(timeout=2000).split())
        except Exception:
            msgs = ""
        log.warning("%s: payment page: Checkout attempt %d did not move the page. messages=%r %s",
                    g.ref, attempt, msgs, recent_signals())
    if not moved:
        raise GroupError(f"{g.ref}: payment page: Checkout was clicked twice but the page never moved. "
                         f"{recent_signals()}")
    wait_fully_loaded(page, "after payment Checkout")


def read_final_order_page(fr):
    return fr.evaluate(FINAL_PAGE_JS)


def _money(text):
    m = re.search(r"-?[\d,]+\.\d+|-?\d+", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def verify_final_order(g, d, ctx):
    """Compare the final order page with the sheet. Returns (problems, notes)."""
    problems, notes = [], []
    if norm(d.get("ref") or "") != norm(g.ref):
        problems.append(f"Reference number: page shows {d.get('ref')!r}, sheet says {g.ref!r}")
    if norm(d.get("description") or "") != norm(HEADER_DESCRIPTION):
        problems.append(f"Description: page shows {d.get('description')!r}, expected {HEADER_DESCRIPTION!r}")

    delivery = d.get("delivery") or ""
    want_addr = (ctx or {}).get("text") or g.address
    street_only = (norm(delivery) + " ").startswith(norm(g.address) + " ")
    if norm(delivery) != norm(want_addr) and not street_only:
        problems.append(f"Delivery address: page shows {delivery!r}, expected {want_addr!r}")

    expected_ship = {"GROUND": "ground", "OVERNIGHT": "overnight"}.get(g.shipping, g.shipping.lower())
    if not (d.get("shipping") or "").lower().startswith(expected_ship):
        problems.append(f"Shipping method: page shows {d.get('shipping')!r}, sheet says {g.shipping}")

    for r in d.get("rows", []):
        if r.get("delivery") and norm(r["delivery"]) != norm(delivery):
            problems.append(f"Item {r.get('item')} ({r.get('sku')}): delivery address {r['delivery']!r} "
                            f"differs from the order's {delivery!r}")

    pay = (d.get("payment") or "").lower()
    if "credit" in pay:
        problems.append(f"Payment method is {d.get('payment')!r}; expected Terms/Invoice")
    elif pay and "invoice" not in pay and "terms" not in pay:
        notes.append(f"payment method text not recognised: {d.get('payment')!r}")
    surcharge = _money((d.get("totals") or {}).get("Credit Card Surcharge"))
    if surcharge:
        problems.append(f"Credit card surcharge is {surcharge:.2f} USD (should be 0.00)")
    total = _money((d.get("totals") or {}).get("Order Total"))
    if not total or total <= 0:
        problems.append(f"Order total looks wrong: {(d.get('totals') or {}).get('Order Total')!r}")

    rows = list(d.get("rows", []))
    for line in g.lines:
        hit = next((r for r in rows if r["sku"] == line.sku and r["unit"] == line.unit and r["qty"] == line.qty), None)
        if hit is None and line.unit == "PAC" and line.devices:
            hit = next((r for r in rows if r["sku"] == line.sku and r["unit"] == "EA" and r["qty"] == line.devices), None)
            if hit:
                notes.append(f"SKU {line.sku}: portal shows {line.qty} PAC as {hit['qty']} EA "
                             f"(equals the sheet's Devices column)")
        if hit is not None:
            rows.remove(hit)
            continue
        same_sku = [r for r in rows if r["sku"] == line.sku]
        if same_sku:
            r = same_sku[0]
            problems.append(f"SKU {line.sku}: page shows {r['qty']} {r['unit']}, sheet says {line.qty} {line.unit}")
            rows.remove(r)
        else:
            problems.append(f"SKU {line.sku}: missing on the page (sheet: {line.qty} {line.unit})")
    for r in rows:
        problems.append(f"SKU {r['sku']}: on the page ({r['qty']} {r['unit']}) but not in the sheet")
    return problems, notes


def pause_for_operator(prompt):
    """Wait for Enter (never when --no-pause); a closed input just carries on."""
    if NO_PAUSE:
        return
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt):
        pass


def _verify_only_cleanup(page, g):
    kind, fr = detect_checkout_page(page)
    if kind == "final":
        continue_shopping(page, g, fr)
    cancel_current_order_cart(page, g)


def continue_shopping(page, g, fr):
    """Final page -> Continue Shopping -> back to the shopping cart (page 1)."""
    link = fr.locator('a[onclick*="backPressed"]')
    if not link.count():
        raise GroupError(f"{g.ref}: 'Continue Shopping' button not found on the final order page")
    mark_frames(page)
    log.info("%s: clicking Continue Shopping to return to the cart", g.ref)
    link.first.click(timeout=10000)
    end = time.time() + 45
    while time.time() < end:
        if detect_checkout_page(page)[0] == "cart":
            wait_fully_loaded(page, "cart after Continue Shopping")
            return
        page.wait_for_timeout(400)
    raise GroupError(f"{g.ref}: Continue Shopping was clicked but the shopping cart did not appear")


def capture_confirmation(page, g):
    """Extract required fields from the portal's receipt page after Order is submitted."""
    logdir = LOGDIR or (BASE_DIR / "logs")
    tag = f"{g.market}_{g.ref}_order_confirmation_{STAMP}"
    try:
        logdir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(logdir / f"{tag}.png"), full_page=True, timeout=10000)
    except Exception as exc:
        log.warning("%s: could not save the confirmation screenshot (%s)", g.ref, exc)

    extracted = None
    page_parts = []
    for fr in list(page.frames):
        try:
            body = fr.locator("body").inner_text(timeout=2000)
            if body.strip():
                page_parts.append(f"--- {fr.url}\n{body}")
            data = fr.evaluate(r"""() => {
                const clean = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
                const cells = Array.from(document.querySelectorAll('td.identifier'));
                const valueAfter = wanted => {
                    const cell = cells.find(c =>
                        clean(c.textContent).replace(/:$/, '').toLowerCase() === wanted.toLowerCase());
                    if (!cell) return '';
                    const row = cell.closest('tr');
                    const value = row ? row.querySelector('td.value') : cell.nextElementSibling;
                    return clean(value ? value.textContent : '');
                };
                let total = '';
                for (const row of document.querySelectorAll('.priceInfo tr')) {
                    const tds = row.querySelectorAll('td');
                    if (tds.length >= 2 &&
                        clean(tds[0].textContent).replace(/:$/, '').toLowerCase() === 'order total') {
                        total = clean(tds[1].textContent);
                        break;
                    }
                }
                const bodyText = clean(document.body ? document.body.innerText : '');
                return {
                    is_confirmation: /confirmation of receipt/i.test(bodyText) &&
                        /your order was received and is being processed/i.test(bodyText),
                    order_number: valueAfter('Order'),
                    reference_number: valueAfter('Your Reference Number'),
                    shipping_method: valueAfter('Shipping Method'),
                    order_total: total,
                    page_text: bodyText.slice(0, 500)
                };
            }""")
            if data.get("is_confirmation"):
                extracted = data
                break
        except Exception:
            continue

    try:
        (logdir / f"{tag}.txt").write_text("\n\n".join(page_parts), encoding="utf-8")
    except Exception as exc:
        log.warning("%s: could not save the confirmation text (%s)", g.ref, exc)

    required = ("order_number", "reference_number", "shipping_method", "order_total")
    if not extracted or any(not extracted.get(k) for k in required):
        raise GroupError(
            f"{g.ref}: Order was clicked and the portal moved, but a valid receipt page with "
            "Order, Reference Number, Shipping Method and Order Total was not verified. "
            "Check order history before retrying; the script will not click Order again."
        )
    log.info("%s: receipt captured: order=%s ref=%s shipping=%s total=%s",
             g.ref, extracted["order_number"], extracted["reference_number"],
             extracted["shipping_method"], extracted["order_total"])
    return {k: extracted[k] for k in required}


def place_order(page, g, fr):
    """Click Order on the VERIFIED final page and wait for the portal to move on."""
    global ALLOW_SEND_ORDER
    link = None
    cands = fr.locator('a[onclick*="sendPressed"]')
    for i in range(cands.count()):
        item = cands.nth(i)
        if item.is_visible() and " ".join(item.inner_text(timeout=1000).split()).casefold() == "order":
            link = item
            break
    if link is None:
        raise GroupError(f"{g.ref}: the visible 'Order' button was not found on the final order page")
    ORDER_CLICKED.add(g.ref)
    mark_frames(page)
    moved = False
    ALLOW_SEND_ORDER = True
    try:
        log.warning("%s: CLICKING ORDER (final order page verified against the sheet)", g.ref)
        link.scroll_into_view_if_needed(timeout=5000)
        link.click(timeout=10000)
        end = time.time() + 90
        while time.time() < end:
            if detect_checkout_page(page)[0] != "final":
                moved = True
                break
            page.wait_for_timeout(500)
    finally:
        ALLOW_SEND_ORDER = False
    if not moved:
        raise GroupError(f"{g.ref}: Order was clicked but the page did not change within 90s. The order MAY or MAY "
                         "NOT have been placed - check the portal's order history before doing anything. "
                         f"I will not click Order again by myself. {recent_signals()}")
    wait_fully_loaded(page, "after Order")
    return capture_confirmation(page, g)


def advance_to_final_page(page, g, recheck_cart=False):
    """From whatever page the portal is on (cart / payment / final) move to the final order page."""
    for _ in range(8):
        kind, fr = wait_for_checkout_page(page, timeout=45)
        log.info("%s: the portal is on the %s page", g.ref, kind)
        if kind == "final":
            return fr
        if kind == "cart":
            if recheck_cart:  # after the operator touched things: re-verify header and cart first
                stage_header(page, g)
                stage_final_check(page, g)
                recheck_cart = False
            click_go_to_checkout(page, g)
        elif kind == "payment":
            payment_checkout(page, g, fr)
        else:
            return None
    raise GroupError(f"{g.ref}: did not reach the final order page after several steps")


def checkout_and_order(page, g, recheck_cart=False):
    """Go To Checkout -> payment page -> final order page -> verify -> Order.
    A mismatch on the final page clicks Continue Shopping (back to the cart) and asks the operator."""
    ctx = ORDER_CTX.get(g.ref)
    fr = advance_to_final_page(page, g, recheck_cart)
    if fr is None:
        if g.ref in ORDER_CLICKED:
            details = capture_confirmation(page, g)
            return {"status": "ORDER PLACED", "detail": "Order was clicked earlier; receipt page re-verified.", **details}
        raise GroupError(f"{g.ref}: the portal is on a page I do not recognise (not cart, payment or final order page)")

    data = read_final_order_page(fr)
    problems, notes = verify_final_order(g, data, ctx)
    log.info("%s: FINAL ORDER PAGE: ref=%s | deliver-to=%s | shipping=%s | payment=%s | items=%s | totals=%s",
             g.ref, data.get("ref"), data.get("delivery"), data.get("shipping"), data.get("payment"),
             [(r["sku"], r["qty"], r["unit"]) for r in data.get("rows", [])], data.get("totals"))
    for n in notes:
        log.info("%s: note: %s", g.ref, n)
    if problems:
        log.error("%s: FINAL ORDER PAGE DOES NOT MATCH THE SHEET:", g.ref)
        for pb in problems:
            log.error("%s:   - %s", g.ref, pb)
        EVENTS.setdefault(g.ref, []).append("final page mismatch: " + "; ".join(problems)[:250])
        shot = snapshot(page, g.ref, "final page mismatch", 1)
        log.error("%s: screenshot of the final order page that did not match: %s", g.ref, shot)
        continue_shopping(page, g, fr)
        raise GroupError(f"{g.ref}: the final order page does not match the sheet, so the order was NOT placed. "
                         "I clicked Continue Shopping and I am back on the shopping cart. Problems: "
                         + "; ".join(problems))
    log.info("%s: final order page matches the sheet", g.ref)

    if g.ref in ORDER_CLICKED:
        raise GroupError(f"{g.ref}: Order was already clicked for this order. Not clicking it again - check the "
                         "portal's order history first. K = skip is the safe choice")
    total = (data.get("totals") or {}).get("Order Total", "?")
    if VERIFY_ONLY:
        shot = snapshot(page, g.ref, "final order page verified", 1)
        log.info("%s: --verify-only: the final order page is open and matches the sheet (screenshot: %s)", g.ref, shot)
        pause_for_operator(f"\n[{g.ref}] VERIFY-ONLY: the final order page is open in the browser and matches the sheet "
                           f"(total {total}). Look at it now.\nPress Enter to click Continue Shopping and cancel this "
                           "cart (Order is NOT clicked): ")
        run_stage(page, g, "cancel the cart (verify-only)",
                  lambda: _verify_only_cleanup(page, g),
                  lambda: clear_cart(page))
        return {"status": "VERIFIED (not ordered)", "detail": f"--verify-only: final page matched the sheet (total {total}); cart cancelled"}
    details = place_order(page, g, fr)
    return {"status": "ORDER PLACED", "detail": f"final page matched the sheet (pre-submit total {total}); receipt page verified.", **details}


def process_one_order(page, g):
    """Build the order, review gate, checkout, final-page check, Order. Returns (result row, stop)."""
    text = build_order(page, g)
    action = pre_checkout_prompt(page, g)
    if action == "skip":
        run_stage(page, g, "cancel cart of the skipped order",
                  lambda: cancel_current_order_cart(page, g),
                  lambda: clear_cart(page))
        raise SkipOrder("operator skipped this order; portal Cancel clicked and empty cart verified")
    if action == "stop":
        raise StopRun("stopped at the pre-checkout review; no checkout action taken")
    if action == "restart":
        raise RestartOrder("operator asked to process the order again at the pre-checkout review")

    outcome = run_stage(page, g, "checkout, final order check and order",
                        lambda: checkout_and_order(page, g),
                        lambda: checkout_and_order(page, g, recheck_cart=True))
    notes = "; ".join(EVENTS.get(g.ref, []))
    status = outcome["status"] + (" (operator assisted)" if notes else "")
    log.info("%s: %s", g.ref, status)
    return ({
        "market": g.market, "refname": g.ref, "status": status,
        "order_number": outcome.get("order_number", ""),
        "reference_number": outcome.get("reference_number", ""),
        "shipping_method": outcome.get("shipping_method", ""),
        "order_total": outcome.get("order_total", ""),
        "detail": f"{text}; {outcome['detail']}", "operator_notes": notes,
    }), False


def handle_order(page, g, results):
    """Run one order and never let an error end the run. Returns True if the run must stop.
    Repeats the whole order only when the operator asks for that."""
    EVENTS.setdefault(g.ref, [])
    while True:
        try:
            result, stop_now = process_one_order(page, g)
            results.append(result)
            return stop_now
        except RestartOrder as e:
            if g.ref in ORDER_CLICKED:
                log.error("%s: NOT restarting - the Order button was already clicked, so restarting could create a "
                          "duplicate order. Check the portal's order history.", g.ref)
                results.append({"market": g.market, "refname": g.ref,
                                "status": "ORDER MAY HAVE BEEN PLACED - CHECK PORTAL",
                                "order_number": "", "reference_number": "", "shipping_method": "",
                                "order_total": "", "detail": "restart refused because Order was already clicked",
                                "operator_notes": "; ".join(EVENTS.get(g.ref, []))})
                return False
            log.warning("%s: processing this order again from the beginning - %s", g.ref, e)
            EVENTS[g.ref].append("order restarted from the beginning")
            continue
        except SkipOrder as e:
            log.warning("%s: SKIPPED - %s", g.ref, e)
            results.append({"market": g.market, "refname": g.ref, "status": "SKIPPED BY USER",
                            "order_number": "", "reference_number": "", "shipping_method": "",
                            "order_total": "", "detail": str(e),
                            "operator_notes": "; ".join(EVENTS.get(g.ref, []))})
            return False
        except StopRun as e:
            log.warning("%s: run stopped - %s", g.ref, e)
            results.append({"market": g.market, "refname": g.ref, "status": "STOPPED",
                            "order_number": "", "reference_number": "", "shipping_method": "",
                            "order_total": "", "detail": str(e),
                            "operator_notes": "; ".join(EVENTS.get(g.ref, []))})
            return True
        except Exception as e:
            # Safety net for anything outside the recoverable steps.
            log.exception("%s: unexpected error", g.ref)
            try:
                snapshot(page, g.ref, "unexpected", 1)
            except Exception:
                log.warning("%s: could not take a snapshot after the unexpected error", g.ref, exc_info=True)
            choice = ask_unexpected_error(g, e)
            if choice == "again":
                EVENTS[g.ref].append(f"order restarted after unexpected {type(e).__name__}")
                continue
            results.append({"market": g.market, "refname": g.ref, "status": "ERROR",
                            "order_number": "", "reference_number": "", "shipping_method": "",
                            "order_total": "", "detail": f"{type(e).__name__}: {e}"[:500],
                            "operator_notes": "; ".join(EVENTS.get(g.ref, []))})
            return choice == "stop"


def main():
    global NO_PAUSE, VERIFY_ONLY, LOGDIR, STAMP
    ap = argparse.ArgumentParser()
    ap.add_argument("orders_file")
    ap.add_argument("--market")
    ap.add_argument("--ref", action="append", help="only this RefName (repeatable)")
    ap.add_argument("--limit", type=int, help="only the first N orders")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, no browser")
    ap.add_argument("--verify-only", action="store_true", help="go through checkout and check the final order page but do NOT click Order (cart is cancelled afterwards)")
    ap.add_argument("--no-pause", action="store_true", help="disable review prompts; problems skip the order instead of asking (not recommended)")
    ap.add_argument("--logins", default=str(default_logins()), help="default: marketlogins.xlsx in the parent folder")
    ap.add_argument(
        "--login-market",
        help="Market name used only for credentials lookup; defaults to --market"
    )
    a = ap.parse_args()
    NO_PAUSE = a.no_pause
    VERIFY_ONLY = a.verify_only

    logdir, stamp = setup_logging()
    LOGDIR, STAMP = logdir, stamp
    if VERIFY_ONLY:
        log.warning("--verify-only: orders will be checked on the final page but NOT placed")
    elif not a.dry_run:
        log.warning("Orders WILL BE PLACED when the final order page matches the sheet")
    sys.excepthook = lambda t, v, tb: log.critical("Unhandled exception - the run crashed", exc_info=(t, v, tb))

    groups, bad = load_plan(a.orders_file, a.market, set(a.ref) if a.ref else None)
    for ref, why in bad.items():
        log.error("SKIPPED at planning: %s", why)
    todo = list(groups.values())[: a.limit] if a.limit else list(groups.values())
    log.info("%d order(s) planned, %d rejected at planning", len(todo), len(bad))

    if a.dry_run:
        for g in todo:
            print_plan(g)
        return

    from playwright.sync_api import sync_playwright

    results = [{"market": "", "refname": ref, "status": "SKIPPED AT PLANNING",
                "order_number": "", "reference_number": "", "shipping_method": "",
                "order_total": "", "detail": why, "operator_notes": ""} for ref, why in bad.items()]
    run_stopped = False
    with sync_playwright() as p:
        for market in sorted({g.market for g in todo}):
            if run_stopped:
                break
            market_orders = [g for g in todo if g.market == market]
            try:
                login_market = a.login_market or market
                user, pw = get_creds(a.logins, login_market)
            except Exception as exc:
                log.error("%s: could not read the login for this market: %s", market, exc)
                log.debug("login lookup traceback", exc_info=True)
                results.extend({"market": g.market, "refname": g.ref, "status": "NOT STARTED",
                                "order_number": "", "reference_number": "", "shipping_method": "",
                                "order_total": "", "detail": f"no login for {market}: {exc}",
                                "operator_notes": ""} for g in market_orders)
                continue
            # Open maximized and let the page use the real window size (no fixed 1280x720
            # emulated viewport, which gets cut off on smaller or scaled screens).
            browser = launch_browser(p)
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            page.set_default_timeout(TIMEOUT * 1000)
            page.on("dialog", on_dialog)
            page.on("pageerror", on_page_error)
            page.on("console", lambda msg: log.warning("browser console error: %s", msg.text)
                    if msg.type == "error" else None)
            try:
                login_with_recovery(page, user, pw, market)
                log.info("logged in and home page ready: %s", market)
                for i, g in enumerate(market_orders, start=1):
                    log.info("===== %s: order %d of %d for %s (%d line(s)) =====",
                             g.ref, i, len(market_orders), market, len(g.lines))
                    if handle_order(page, g, results):
                        run_stopped = True
                        break
                if run_stopped:
                    log.warning("Run stopped by the operator; no further orders will be started")
                if not a.no_pause:
                    input(f"\nAll {market} orders processed. Browser remains open. Review it, then press Enter here to close... ")
                else:
                    log.warning("--no-pause supplied: browser will close automatically after processing")
            except StopRun as e:
                log.warning("%s: market skipped/stopped - %s", market, e)
                results.extend({"market": g.market, "refname": g.ref, "status": "NOT STARTED",
                                "order_number": "", "reference_number": "", "shipping_method": "",
                                "order_total": "", "detail": str(e), "operator_notes": ""}
                               for g in market_orders
                               if g.ref not in {r["refname"] for r in results})
            except KeyboardInterrupt:
                log.warning("Interrupted by user; waiting for explicit Enter before closing browser.")
                run_stopped = True
                try:
                    input("Press Enter to close the browser... ")
                except EOFError:
                    pass
            except Exception:
                log.exception("Market %s failed before/during login", market)
                results.append({"market": market, "refname": "", "status": "LOGIN/SESSION ERROR",
                                "order_number": "", "reference_number": "", "shipping_method": "",
                                "order_total": "", "detail": traceback.format_exc()[-1500:],
                                "operator_notes": ""})
                if not a.no_pause:
                    try:
                        input("Session failed. Browser remains open; inspect it, then press Enter to close... ")
                    except EOFError:
                        pass
            finally:
                try:
                    context.close()
                except Exception:
                    log.warning("Could not close browser context cleanly", exc_info=True)
                try:
                    browser.close()
                except Exception:
                    log.warning("Could not close browser cleanly", exc_info=True)

    # ---- one consolidated worksheet for every market and every order outcome
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All Orders"
    headers = ["Market", "RefName", "Status", "Order Number", "Reference Number",
               "Shipping Method", "Order Total", "Detail", "Operator help / problems"]
    ws.append(headers)
    for r in results:
        ws.append([r.get("market", ""), r.get("refname", ""), r.get("status", ""),
                   r.get("order_number", ""), r.get("reference_number", ""),
                   r.get("shipping_method", ""), r.get("order_total", ""),
                   r.get("detail", ""), r.get("operator_notes", "")])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col_cells in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col_cells), default=0)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(max_len + 2, 12), 55)
    out = logdir / f"place_orders_results_{stamp}.xlsx"
    try:
        wb.save(out)
        log.info("consolidated all-markets results -> %s", out)
    except Exception:
        log.exception("could not save the results workbook %s (is it open in Excel?)", out)
    counts = Counter(r.get("status", "") for r in results)
    log.info("SUMMARY: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no orders processed")
    for r in results:
        log.info("  %-18s %-28s %s", r.get("market", ""), r.get("status", ""),
                 (r.get("operator_notes", "") or "")[:140])



if __name__ == "__main__":
    main()