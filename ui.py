#!/usr/bin/env python3
"""Standalone entry point: `python ui.py` launches the browser UI.

No install/dependencies required (stdlib only). Opens
http://127.0.0.1:8765/ and a browser tab automatically.
"""

from cardpack.webui import main

if __name__ == "__main__":
    raise SystemExit(main())
