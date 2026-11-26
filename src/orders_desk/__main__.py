"""Entry point.  `python -m orders_desk` opens the app; `--worker <task> ...` runs a task headless."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        from .worker import run_worker
        return run_worker(argv[1:])
    from .app import run_gui
    return run_gui(argv)


if __name__ == "__main__":
    sys.exit(main())
