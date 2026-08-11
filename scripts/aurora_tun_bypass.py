#!/usr/bin/env python3
"""Inspect, patch, or restore Aurora Slim encrypted TUN routing config."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

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
        rules = route_rules(config, key)
        target = next(
            (
                rule
                for rule in rules
                if isinstance(rule, dict)
                and rule.get("outbound") == "direct"
                and isinstance(rule.get("process_name"), list)
            ),
            None,
        )
        if target is None:
            raise ValueError(f"no existing direct process_name rule found in {key}")
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
    found = set()
    for line in completed.stdout.splitlines():
        image = line.split(",", 1)[0].strip().strip('"').casefold()
        if image in RUNNING_IMAGES:
            found.add(image)
    return sorted(found)


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
    try:
        shutil.copyfile(source, target)
    finally:
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
        if running and config == DEFAULT_CONFIG.resolve() and not args.allow_running:
            raise RuntimeError(
                "Aurora is running ("
                + ", ".join(running)
                + "). Exit Aurora completely or pass --allow-running explicitly."
            )
        backup = timestamped_backup(config, output_dir)
        try:
            replace_preserving_attributes(candidate, config)
            written, _ = decrypt_config(config.read_bytes())
            if written != data:
                raise ValueError(
                    "written Aurora config does not match the validated candidate"
                )
        except Exception:
            replace_preserving_attributes(backup, config)
            raise
        result.update(status="applied", backup=str(backup), running_images=running)
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
    patch_parser.set_defaults(handler=command_patch)

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
