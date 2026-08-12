#!/usr/bin/env python3
"""Standalone entry point: `python bestcards.py <folder-or-files...>`.

No install/dependencies required (stdlib only).
"""

from cardpack.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
