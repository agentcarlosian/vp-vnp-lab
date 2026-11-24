"""Entrypoint for `python -m lean_orch`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
