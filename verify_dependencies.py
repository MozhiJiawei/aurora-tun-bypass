#!/usr/bin/env python3
"""Verify external prerequisites for aurora-tun-bypass."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


CONFIG_BASENAME = ".a80ac3211ccf83b91dffd138706f16d66660dfe8"
CONFIG = Path.home() / ".aurora-slim" / CONFIG_BASENAME
LOCAL_LIB = Path(os.environ.get("LOCALAPPDATA", "")) / "AuroraTunBypass" / "lib"


def local_frida_imports() -> bool:
    if not LOCAL_LIB.is_dir():
        return False
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import frida",
            str(LOCAL_LIB),
        ],
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def main() -> int:
    checks = [
        {"name": "Windows", "ok": os.name == "nt", "value": platform.system()},
        {
            "name": "Python package: cryptography",
            "ok": importlib.util.find_spec("cryptography") is not None,
        },
        {
            "name": "Python package: frida (importable or locally installed)",
            "ok": importlib.util.find_spec("frida") is not None or local_frida_imports(),
            "value": str(LOCAL_LIB),
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
            "Install frida into .tmp/aurora-tun-bypass before install-memory-hook if missing.",
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
