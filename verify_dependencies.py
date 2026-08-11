#!/usr/bin/env python3
"""Verify external prerequisites for aurora-tun-bypass."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
from pathlib import Path


CONFIG_BASENAME = ".a80ac3211ccf83b91dffd138706f16d66660dfe8"
CONFIG = Path.home() / ".aurora-slim" / CONFIG_BASENAME


def main() -> int:
    checks = [
        {"name": "Windows", "ok": os.name == "nt", "value": platform.system()},
        {
            "name": "Python package: cryptography",
            "ok": importlib.util.find_spec("cryptography") is not None,
        },
        {"name": "Aurora config exists", "ok": CONFIG.is_file(), "value": str(CONFIG)},
        {"name": "Aurora config readable", "ok": CONFIG.is_file() and os.access(CONFIG, os.R_OK)},
    ]
    ok = all(item["ok"] for item in checks)
    result = {
        "ok": ok,
        "required": checks,
        "warnings": [] if ok else [
            "Install cryptography with 'python -m pip install cryptography' if missing.",
            "Run this skill on the Windows account where Aurora Slim stores its config.",
        ],
        "not_checked": [
            "Aurora account or subscription",
            "proxy-node availability",
            "target application's runtime process names",
            "compatibility with Aurora versions other than the documented version",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

