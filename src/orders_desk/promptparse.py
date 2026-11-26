"""Turn the engine's terminal questions (input() prompts) into button choices for the GUI.

The engine prints a menu and then calls input("Your choice [Enter/R/O/K/S]: ").  The GUI
receives the recent output lines plus the prompt text and builds buttons from them.  If the
parser cannot understand a prompt it still returns a usable dialog: free-text field + Continue.
"""
from __future__ import annotations

import re

_BRACKET = re.compile(r"\[([^\[\]]*)\]\s*:?\s*$")
_LEGEND = re.compile(r"(?:^|\s{2,}|\s)(Enter|[A-Z])\s*=\s*(.+?)(?=\s{2,}(?:Enter|[A-Z])\s*=|$)", re.M)
_NUMBERED = re.compile(r"^\s{1,4}(\d{1,3})\.\s+(.+?)\s*(?:\[option value=.*\])?\s*$")
_RANGE = re.compile(r"\[(\d+)-(\d+)\]")

_STYLE = {"s": "danger", "q": "danger", "k": "warn", "n": "secondary", "no": "secondary"}


def _clean(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip(" .:-")
    return label[:96]


def parse_prompt(prompt: str, context: list[str]) -> dict:
    """Return {"title", "body": [lines], "options": [{"key","label","style"}], "freeText": bool}."""
    prompt_lines = [ln for ln in prompt.strip("\n").splitlines() if ln.strip()]
    last = prompt_lines[-1].strip() if prompt_lines else ""
    body_src = [ln.rstrip() for ln in (context + prompt_lines[:-1])]
    body = [ln for ln in body_src if ln.strip()][-16:]
    legend_text = "\n".join(body_src + [last])

    options: list[dict] = []
    free_text = False

    def add(key: str, label: str, style: str | None = None):
        if any(o["key"] == key for o in options):
            return
        options.append({"key": key, "label": label, "style": style or _STYLE.get(key.lower(), "secondary")})

    low = last.lower()
    m_range = _RANGE.search(last)
    numbered = []
    for ln in body_src:
        m = _NUMBERED.match(ln)
        if m:
            numbered.append((m.group(1), _clean(m.group(2))))
    # keep only the final contiguous run of numbered options (latest menu)
    if numbered:
        seq, expect = [], 1
        for k, lab in numbered:
            if int(k) == 1:
                seq, expect = [], 1
            if int(k) == expect:
                seq.append((k, lab))
                expect += 1
        numbered = seq

    if "[y/n]" in low or "(y/n)" in low:
        add("y", "Yes, confirm", "primary")
        add("n", "No, stop this order", "secondary")
        title = "Please confirm"
    elif numbered and (m_range or "option number" in low or "number" in low):
        for k, lab in numbered:
            add(k, f"{k}.  {lab}", "primary" if k == "1" else "secondary")
        for key, label in re.findall(r"\b([A-Z])\s*=\s*([^,()]+?)(?=,|\(|$)", last):
            if key not in ("Q",) or True:
                add(key.lower(), _clean(label), None)
        if "type q to stop" in low or ("q" in low and "stop" in low):
            add("q", "Stop this order", "danger")
        title = "Choose the correct option"
    else:
        keys_in_brackets = []
        mb = _BRACKET.search(last)
        if mb and "/" in mb.group(1):
            keys_in_brackets = [t.strip() for t in mb.group(1).split("/") if t.strip()]
        legend = {}
        for key, text in _LEGEND.findall(legend_text):
            legend[key] = _clean(re.sub(r"\(.*?\)\s*$", lambda m_: m_.group(0), text))
        if keys_in_brackets:
            for key in keys_in_brackets:
                k = "" if key.lower() == "enter" else key.lower()
                label = legend.get(key if key == "Enter" else key.upper(), "")
                if not label:
                    label = "Continue" if k == "" else key.upper()
                add(k if k else "", label, "primary" if k == "" else None)
            title = "Your decision is needed"
        elif legend:
            for key, text in legend.items():
                k = "" if key == "Enter" else key.lower()
                add(k, text, "primary" if k == "" else None)
            title = "Your decision is needed"
        else:
            add("", "Continue", "primary")
            title = "Action needed in the browser"
            free_text = False

    # primary action first, destructive last
    order = {"primary": 0, "secondary": 1, "warn": 2, "danger": 3}
    options.sort(key=lambda o: order.get(o["style"], 1))
    if not options:
        add("", "Continue", "primary")
    return {"title": title, "body": body, "options": options, "freeText": free_text or not numbered and False,
            "prompt": last}
