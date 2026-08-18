#!/usr/bin/env python3
"""Inspect, patch, or restore Aurora Slim encrypted TUN routing config."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from aurora_rules import active_matches as parse_active_matches

if os.name == "nt":
    import winreg

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    from cryptography.hazmat.decrepit.ciphers import modes
except ImportError:  # cryptography < 43
    from cryptography.hazmat.primitives.ciphers import modes


DIGEST_KEY = b"Ahe$s^bNe#4QEAaw3CA4fewC"
DATA_KEY = b"5oQ428M%*oQ9wAO#&aNJGAwH"
CONFIG_BASENAME = "." + hashlib.sha1(
    b"APPDATA.CONFIG.FILENAME.AIRPORT"
).hexdigest()
DEFAULT_CONFIG = Path.home() / ".aurora-slim" / CONFIG_BASENAME
DEFAULT_CONFIG_KEYS = ("global_tun_config", "tun_config")
RUNNING_IMAGES = {"aurora.exe", "aurora_slim.exe", "aurora-slim.exe"}
FILE_ATTRIBUTE_HIDDEN = 0x2
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
LOCAL_API_BASE = "http://127.0.0.1:18090/api"
WATCH_RUN_VALUE = "AuroraTunBypass"


def decrypt_cfb(blob: bytes, key: bytes) -> bytes:
    if len(blob) < 16:
        raise ValueError("encrypted block is shorter than its 16-byte IV")
    iv, ciphertext = blob[:16], blob[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CFB(iv)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def encrypt_cfb(plaintext: bytes, key: bytes) -> bytes:
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
    return iv + encryptor.update(plaintext) + encryptor.finalize()


def decrypt_config(raw: bytes) -> tuple[dict[str, Any], bytes]:
    if len(raw) < 96:
        raise ValueError("Aurora config is too short")
    stored_digest = decrypt_cfb(raw[:80], DIGEST_KEY)
    plaintext = decrypt_cfb(raw[80:], DATA_KEY)
    actual_digest = hashlib.sha256(plaintext).hexdigest().encode("ascii")
    if stored_digest != actual_digest:
        raise ValueError("Aurora config digest verification failed")
    value = json.loads(plaintext)
    if not isinstance(value, dict):
        raise ValueError("Aurora config root is not a JSON object")
    return value, plaintext


def encrypt_config(data: dict[str, Any]) -> bytes:
    plaintext = json.dumps(
        data, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(plaintext).hexdigest().encode("ascii")
    return encrypt_cfb(digest, DIGEST_KEY) + encrypt_cfb(plaintext, DATA_KEY)


def parse_nested_config(data: dict[str, Any], key: str) -> tuple[dict[str, Any], bool]:
    if key not in data:
        raise KeyError(f"missing Aurora config key: {key}")
    stored = data[key]
    was_string = isinstance(stored, str)
    value = json.loads(stored) if was_string else stored
    if not isinstance(value, dict):
        raise ValueError(f"{key} is not a JSON object")
    return value, was_string


def route_rules(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    route = config.get("route")
    if not isinstance(route, dict) or not isinstance(route.get("rules"), list):
        raise ValueError(f"{key} does not contain route.rules")
    return route["rules"]


def direct_process_rule(config: dict[str, Any], key: str) -> dict[str, Any]:
    matches = [
        rule
        for rule in route_rules(config, key)
        if isinstance(rule, dict)
        and rule.get("outbound") == "direct"
        and isinstance(rule.get("process_name"), list)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one direct process_name rule in {key}; found {len(matches)}"
        )
    return matches[0]


def routing_summary(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in keys:
        config, _ = parse_nested_config(data, key)
        rules = route_rules(config, key)
        summaries = []
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            if "process_name" in rule or index == len(rules) - 1:
                summaries.append(
                    {
                        "index": index,
                        "outbound": rule.get("outbound"),
                        "process_name": rule.get("process_name"),
                    }
                )
        result[key] = {"rule_count": len(rules), "relevant_rules": summaries}
    return result


def normalize_process_names(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        name = raw.strip()
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError(f"process must be a basename, not a path: {raw!r}")
        if name.casefold() not in {item.casefold() for item in normalized}:
            normalized.append(name)
    if not normalized:
        raise ValueError("at least one --process is required")
    return normalized


def patch_processes(
    data: dict[str, Any], keys: list[str], processes: list[str]
) -> list[str]:
    changes: list[str] = []
    for key in keys:
        config, was_string = parse_nested_config(data, key)
        target = direct_process_rule(config, key)
        existing = {str(item).casefold() for item in target["process_name"]}
        for process in processes:
            if process.casefold() not in existing:
                target["process_name"].append(process)
                existing.add(process.casefold())
                changes.append(f"{key}:{process}")
        data[key] = (
            json.dumps(config, ensure_ascii=False, separators=(",", ":"))
            if was_string
            else config
        )
    return changes


def missing_processes(
    data: dict[str, Any], keys: list[str], processes: list[str]
) -> list[str]:
    missing: list[str] = []
    for key in keys:
        config, _ = parse_nested_config(data, key)
        target = direct_process_rule(config, key)
        existing = {str(item).casefold() for item in target["process_name"]}
        missing.extend(
            f"{key}:{process}"
            for process in processes
            if process.casefold() not in existing
        )
    return missing


def running_aurora_images() -> list[str]:
    if os.name != "nt":
        return []
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    found: set[str] = set()
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2:
            continue
        image = row[0].strip().casefold()
        if image in RUNNING_IMAGES:
            found.add(image)
    return sorted(found)


def local_api_post(endpoint: str, timeout: float = 20.0) -> dict[str, Any]:
    request = Request(f"{LOCAL_API_BASE}/{endpoint}", data=b"", method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Aurora local API {endpoint} failed: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("code") != 1:
        raise RuntimeError(f"Aurora local API {endpoint} returned failure")
    return payload


def get_windows_attributes(path: Path) -> int | None:
    if os.name != "nt":
        return None
    value = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if value == INVALID_FILE_ATTRIBUTES:
        raise ctypes.WinError()
    return int(value)


def set_windows_attributes(path: Path, attributes: int | None) -> None:
    if os.name == "nt" and attributes is not None:
        if not ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes):
            raise ctypes.WinError()


def replace_preserving_attributes(source: Path, target: Path) -> None:
    attributes = get_windows_attributes(target)
    if attributes is not None:
        set_windows_attributes(target, attributes & ~FILE_ATTRIBUTE_HIDDEN)
    staged = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, staged)
        with staged.open("rb+") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)
        if target.exists():
            set_windows_attributes(target, attributes)


def timestamped_backup(
    config: Path, output_dir: Path, prefix: str = "aurora-config"
) -> Path:
    backup_dir = output_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{prefix}-{stamp}.enc"
    suffix = 1
    while backup.exists():
        backup = backup_dir / f"{prefix}-{stamp}-{suffix}.enc"
        suffix += 1
    shutil.copy2(config, backup)
    return backup


def write_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def watch_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not available")
    return Path(local_app_data) / "AuroraTunBypass"


def atomic_copy(source: Path, target: Path) -> None:
    staged = target.with_suffix(target.suffix + ".new")
    shutil.copy2(source, staged)
    os.replace(staged, target)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    staged = path.with_suffix(path.suffix + ".new")
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staged, path)


def installed_injector_pids(installed_injector: Path) -> list[int]:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    records = json.loads(completed.stdout)
    if isinstance(records, dict):
        records = [records]
    needle = str(installed_injector).casefold()
    return [
        int(record["ProcessId"])
        for record in records
        if isinstance(record, dict)
        and needle in str(record.get("CommandLine") or "").casefold()
    ]


def stop_installed_injector(install_dir: Path, timeout: float = 8.0) -> list[int]:
    installed_injector = install_dir / "aurora_memory_injector.pyw"
    stop_file = install_dir / "stop.request"
    stop_file.touch()
    deadline = time.monotonic() + timeout
    pids = installed_injector_pids(installed_injector)
    while pids and time.monotonic() < deadline:
        time.sleep(0.25)
        pids = installed_injector_pids(installed_injector)
    forced = list(pids)
    for pid in forced:
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    stop_file.unlink(missing_ok=True)
    return forced


def remove_startup_entry() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, WATCH_RUN_VALUE)
        return True
    except FileNotFoundError:
        return False


def wait_for_memory_hook(status_file: Path, pid: int, targets: list[str], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            value = json.loads(status_file.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                last = value
                if (
                    value.get("event") == "active_rules_verified"
                    and value.get("injector_pid") == pid
                    and value.get("ok") is True
                    and all(value.get("matches", {}).get(name) is True for name in targets)
                ):
                    return value
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"memory hook did not verify active direct rules; last status: {last.get('event', 'none')}")


def command_install_memory_hook(args: argparse.Namespace) -> int:
    if os.name != "nt":
        raise RuntimeError("memory-hook installation is supported only on Windows")
    requested = normalize_process_names(args.process)
    install_dir = watch_install_dir().resolve()
    injector_source = Path(__file__).with_name("aurora_memory_injector.py")
    rules_source = Path(__file__).with_name("aurora_rules.py")
    if not injector_source.is_file() or not rules_source.is_file():
        raise RuntimeError("memory injector sources are incomplete")
    frida_spec = importlib.util.find_spec("frida")
    lib_dir = install_dir / "lib"
    installed_frida = lib_dir / "frida"
    if frida_spec is not None and frida_spec.submodule_search_locations:
        frida_source = Path(next(iter(frida_spec.submodule_search_locations))).resolve()
    elif installed_frida.is_dir():
        frida_source = installed_frida.resolve()
    else:
        raise RuntimeError(
            "frida is unavailable; install it into a temporary dependency directory "
            "and put that directory on PYTHONPATH before running install-memory-hook"
        )
    installed_injector = install_dir / "aurora_memory_injector.pyw"
    installed_rules = install_dir / "aurora_rules.py"
    settings_file = install_dir / "settings.json"
    status_file = install_dir / "status.json"
    install_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if settings_file.is_file() and not args.replace_processes:
        try:
            existing = list(json.loads(settings_file.read_text(encoding="utf-8")).get("processes", []))
        except (OSError, json.JSONDecodeError, AttributeError):
            existing = []
    processes = normalize_process_names(existing + requested)

    stop_installed_injector(install_dir)
    atomic_copy(injector_source, installed_injector)
    atomic_copy(rules_source, installed_rules)
    if frida_source != installed_frida.resolve():
        shutil.copytree(frida_source, installed_frida, dirs_exist_ok=True)
    smoke = subprocess.run(
        [
            str(Path(sys.executable).with_name("python.exe")),
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import frida; print(frida.__version__)",
            str(lib_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if smoke.returncode != 0:
        raise RuntimeError(f"installed Frida import failed: {smoke.stderr.strip()}")
    atomic_write_json(settings_file, {"processes": processes})

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    command = subprocess.list2cmdline([str(interpreter), str(installed_injector)])
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
    ) as key:
        winreg.SetValueEx(key, WATCH_RUN_VALUE, 0, winreg.REG_SZ, command)
    status_file.unlink(missing_ok=True)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    if interpreter.name.casefold() == "python.exe":
        creationflags |= subprocess.CREATE_NO_WINDOW
    injector = subprocess.Popen(
        [str(interpreter), str(installed_injector)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    verified = wait_for_memory_hook(status_file, injector.pid, processes, args.verify_timeout)
    write_json(
        {
            "status": "memory_hook_installed",
            "install_dir": str(install_dir),
            "settings": str(settings_file),
            "injector_pid": injector.pid,
            "processes": processes,
            "startup": "HKCU Run",
            "active_rules_verified": verified.get("ok"),
        }
    )
    return 0


def command_uninstall_memory_hook(args: argparse.Namespace) -> int:
    if os.name != "nt":
        raise RuntimeError("memory-hook installation is supported only on Windows")
    install_dir = watch_install_dir().resolve()
    settings_file = install_dir / "settings.json"
    targets: list[str] = []
    if settings_file.is_file():
        try:
            targets = normalize_process_names(
                list(json.loads(settings_file.read_text(encoding="utf-8")).get("processes", []))
            )
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            targets = []
    startup_removed = remove_startup_entry()
    forced_pids = stop_installed_injector(install_dir)
    if args.reload_core and running_aurora_images():
        local_api_post("stopsb")
        local_api_post("startsb")
        time.sleep(1)
    matches: dict[str, bool] = {}
    if targets:
        try:
            with urlopen("http://127.0.0.1:19090/rules", timeout=3) as response:
                matches = parse_active_matches(response.read().decode("utf-8", "replace"), targets)
        except Exception:
            matches = {name: False for name in targets}
    write_json(
        {
            "status": "memory_hook_uninstalled",
            "startup_removed": startup_removed,
            "forced_pids": forced_pids,
            "core_reloaded": bool(args.reload_core),
            "targets_still_direct": [name for name, present in matches.items() if present],
        }
    )
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    config = args.config.resolve()
    data, plaintext = decrypt_config(config.read_bytes())
    write_json(
        {
            "status": "inspected",
            "config": str(config),
            "digest_ok": True,
            "plaintext_bytes": len(plaintext),
            "routing": routing_summary(data, args.config_key),
        }
    )
    return 0


def command_patch(args: argparse.Namespace) -> int:
    config = args.config.resolve()
    output_dir = args.output_dir.resolve()
    processes = normalize_process_names(args.process)
    original = config.read_bytes()
    data, _ = decrypt_config(original)
    changes = patch_processes(data, args.config_key, processes)
    patched = encrypt_config(data)
    round_trip, _ = decrypt_config(patched)
    if round_trip != data:
        raise ValueError("encrypted round-trip verification failed")

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / "patched-config.enc"
    candidate.write_bytes(patched)
    result: dict[str, Any] = {
        "status": "dry_run",
        "config": str(config),
        "changes": changes,
        "already_present": not changes,
        "candidate": str(candidate),
        "digest_ok": True,
        "round_trip_ok": True,
        "routing": routing_summary(data, args.config_key),
    }

    if args.apply:
        running = running_aurora_images()
        is_live_default = running and config == DEFAULT_CONFIG.resolve()
        if is_live_default and not (args.allow_running or args.reload_core):
            raise RuntimeError(
                "Aurora is running ("
                + ", ".join(running)
                + "). Pass --reload-core only for a diagnostic probe, or "
                "--allow-running for an unsafe raw write."
            )
        core_stopped = False
        if is_live_default and args.reload_core:
            local_api_post("stopsb")
            core_stopped = True
            time.sleep(0.5)
        backup = timestamped_backup(config, output_dir)
        try:
            replace_preserving_attributes(candidate, config)
            written, _ = decrypt_config(config.read_bytes())
            if written != data:
                raise ValueError(
                    "written Aurora config does not match the validated candidate"
                )
            if core_stopped:
                local_api_post("startsb")
                core_stopped = False
                time.sleep(args.stability_wait)
                stable, _ = decrypt_config(config.read_bytes())
                missing = missing_processes(stable, args.config_key, processes)
                if missing:
                    raise ValueError(
                        "Aurora rewrote the requested rules after core reload: "
                        + ", ".join(missing)
                    )
        except Exception:
            replace_preserving_attributes(backup, config)
            if core_stopped:
                try:
                    local_api_post("startsb")
                except Exception:
                    pass
            raise
        result.update(
            status="applied",
            backup=str(backup),
            running_images=running,
            core_reloaded=bool(is_live_default and args.reload_core),
            stability_check_ok=True,
        )
    write_json(result)
    return 0


def command_restore(args: argparse.Namespace) -> int:
    if not args.apply:
        raise ValueError("restore requires --apply")
    config = args.config.resolve()
    backup = args.backup.resolve()
    restored, _ = decrypt_config(backup.read_bytes())
    running = running_aurora_images()
    if running and config == DEFAULT_CONFIG.resolve() and not args.allow_running:
        raise RuntimeError(
            "Aurora is running ("
            + ", ".join(running)
            + "). Exit Aurora completely or pass --allow-running explicitly."
        )
    snapshot_root = backup.parent.parent if backup.parent.name == "backups" else backup.parent
    pre_restore = timestamped_backup(config, snapshot_root, prefix="pre-restore")
    try:
        replace_preserving_attributes(backup, config)
        written, _ = decrypt_config(config.read_bytes())
        if written != restored:
            raise ValueError("restored Aurora config does not match the backup")
    except Exception:
        replace_preserving_attributes(pre_restore, config)
        raise
    write_json(
        {
            "status": "restored",
            "config": str(config),
            "backup": str(backup),
            "pre_restore_backup": str(pre_restore),
            "digest_ok": True,
            "running_images": running,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely manage Aurora Slim process-based TUN bypass rules."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--config-key",
        action="append",
        default=None,
        help="Nested TUN config key; repeat to target multiple keys.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Print a redacted route summary.")
    inspect_parser.set_defaults(handler=command_inspect)

    patch_parser = subparsers.add_parser("patch", help="Add process names to direct rules.")
    patch_parser.add_argument("--process", action="append", required=True)
    patch_parser.add_argument("--output-dir", type=Path, required=True)
    patch_parser.add_argument("--apply", action="store_true")
    patch_parser.add_argument("--allow-running", action="store_true")
    patch_parser.add_argument(
        "--reload-core",
        action="store_true",
        help="Stop and restart Aurora's proxy core around a live apply.",
    )
    patch_parser.add_argument(
        "--stability-wait",
        type=float,
        default=3.0,
        help="Seconds to wait before verifying the reloaded live config.",
    )
    patch_parser.set_defaults(handler=command_patch)

    memory_parser = subparsers.add_parser(
        "install-memory-hook",
        help="Install the persistent SetConfig in-memory injection maintainer.",
    )
    memory_parser.add_argument("--process", action="append", required=True)
    memory_parser.add_argument(
        "--replace-processes",
        action="store_true",
        help="Replace installed targets instead of merging them.",
    )
    memory_parser.add_argument("--verify-timeout", type=float, default=25.0)
    memory_parser.set_defaults(handler=command_install_memory_hook)

    uninstall_parser = subparsers.add_parser(
        "uninstall-memory-hook", help="Stop the maintainer and remove its startup entry."
    )
    uninstall_parser.add_argument(
        "--reload-core",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reload Aurora core to discard the injected in-memory rules (default: true).",
    )
    uninstall_parser.set_defaults(handler=command_uninstall_memory_hook)

    restore_parser = subparsers.add_parser("restore", help="Restore a validated backup.")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--apply", action="store_true")
    restore_parser.add_argument("--allow-running", action="store_true")
    restore_parser.set_defaults(handler=command_restore)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.config_key = args.config_key or list(DEFAULT_CONFIG_KEYS)
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
