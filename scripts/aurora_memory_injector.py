from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path


INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "AuroraTunBypass"
LOCAL_LIB = INSTALL_DIR / "lib"
if LOCAL_LIB.is_dir():
    sys.path.insert(0, str(LOCAL_LIB))

import frida  # type: ignore[import-not-found]  # noqa: E402
from aurora_rules import active_matches as parse_active_matches  # noqa: E402


SET_CONFIG_SYMBOL = "aurora-client/common/singbox.(*Box).SetConfig"
IMAGE_NAME = "Aurora.exe"
CONTROL_API = "http://127.0.0.1:18090/api"
RULES_API = "http://127.0.0.1:19090/rules"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_ALREADY_EXISTS = 183
INJECTOR_MUTEX = "Local\\AuroraTunBypassMemoryInjector"
PID_FILE = INSTALL_DIR / "injector.pid"
STOP_FILE = INSTALL_DIR / "stop.request"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
kernel32.OpenProcess.restype = ctypes.c_void_p


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def find_processes(image_name: str) -> list[int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    result: list[int] = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() == image_name.casefold():
                result.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def process_path(pid: int) -> Path:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def find_go_symbol_rva(executable: Path, wanted: str) -> int:
    data = executable.read_bytes()
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("target is not a PE file")
    optional = pe_offset + 24
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise ValueError("target is not a 64-bit PE file")
    image_base = struct.unpack_from("<Q", data, optional + 24)[0]

    signature = b"\xf1\xff\xff\xff\x00\x00\x01\x08"
    search_at = 0
    while True:
        base = data.find(signature, search_at)
        if base < 0:
            break
        search_at = base + 1
        try:
            (
                _, _, _, _, _, nfunc, _, text_start, funcname_offset,
                _, _, _, pcln_offset,
            ) = struct.unpack_from("<I4B8Q", data, base)
        except struct.error:
            continue
        if not (1_000 < nfunc < 1_000_000 and image_base <= text_start < image_base + len(data)):
            continue
        functab = base + pcln_offset
        names = base + funcname_offset
        if functab + nfunc * 8 > len(data):
            continue
        for index in range(nfunc):
            entry_offset, function_offset = struct.unpack_from("<II", data, functab + index * 8)
            metadata = functab + function_offset
            if metadata + 8 > len(data):
                continue
            metadata_entry, name_offset = struct.unpack_from("<Ii", data, metadata)
            if metadata_entry != entry_offset:
                continue
            name_at = names + name_offset
            if not 0 <= name_at < len(data):
                continue
            name_end = data.find(b"\0", name_at, name_at + 512)
            if name_end < 0:
                continue
            if data[name_at:name_end].decode("utf-8", "replace") == wanted:
                return text_start + entry_offset - image_base
    raise ValueError(f"Go symbol not found: {wanted}")


def build_script(rva: int, targets: list[str]) -> str:
    return r"""
const targets = %s;
const allocations = [];
function utf8Length(value) {
  let length = 0;
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < 0x80) length += 1;
    else if (code < 0x800) length += 2;
    else if (code >= 0xd800 && code <= 0xdbff) { length += 4; i += 1; }
    else length += 3;
  }
  return length;
}
const module = Process.getModuleByName('Aurora.exe');
const address = module.base.add(%d);
Interceptor.attach(address, {
  onEnter() {
    try {
      const originalLength = parseInt(this.context.rcx.toString(), 16);
      const config = JSON.parse(this.context.rbx.readUtf8String(originalLength));
      const rules = config.route && Array.isArray(config.route.rules) ? config.route.rules : [];
      const matching = rules.filter(rule =>
        rule && rule.outbound === 'direct' && Array.isArray(rule.process_name));
      if (matching.length !== 1) {
        send({event: 'shape_mismatch', matching_rules: matching.length});
        return;
      }
      const targetRule = matching[0];
      let changed = false;
      const existing = new Set(targetRule.process_name.map(name => String(name).toLowerCase()));
      for (const name of targets) {
        if (!existing.has(name.toLowerCase())) {
          targetRule.process_name.push(name);
          existing.add(name.toLowerCase());
          changed = true;
        }
      }
      if (!changed) { send({event: 'already_present'}); return; }
      const modified = JSON.stringify(config);
      const length = utf8Length(modified);
      const replacement = Memory.allocUtf8String(modified);
      allocations.push(replacement);
      this.context.rbx = replacement;
      this.context.rcx = ptr(length);
      this.context.rdi = ptr(length);
      send({event: 'injected', length: length, count: targets.length});
    } catch (error) { send({event: 'inject_error', error: String(error)}); }
  }
});
send({event: 'hook_ready', target: address.toString()});
""" % (json.dumps(targets), rva)


def request_json(url: str, timeout: float = 2) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def active_matches(targets: list[str]) -> dict[str, bool]:
    try:
        raw = request_json(RULES_API)
        return parse_active_matches(raw, targets)
    except Exception:
        return {name: False for name in targets}


def post(path: str, timeout: float = 15) -> None:
    request = urllib.request.Request(f"{CONTROL_API}/{path}", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


class Reporter:
    def __init__(self, status_path: Path, log_path: Path) -> None:
        self.status_path = status_path
        self.log_path = log_path
        self.lock = threading.Lock()

    def emit(self, event: str, **details: object) -> None:
        record = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "injector_pid": os.getpid(),
            **details,
        }
        with self.lock:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            self._append_log(record)

    def log(self, event: str, **details: object) -> None:
        record = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **details}
        with self.lock:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self._append_log(record)

    def _append_log(self, record: dict[str, object]) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 1_000_000:
            self.log_path.replace(self.log_path.with_suffix(".previous.log"))
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def maintain(targets: list[str], reporter: Reporter, once: bool) -> int:
    current_pid: int | None = None
    session = None
    detached = threading.Event()
    while True:
        if STOP_FILE.exists():
            reporter.emit("stop_requested")
            return 0
        pids = find_processes(IMAGE_NAME)
        pid = pids[0] if pids else None
        if pid is None:
            if once:
                reporter.emit("aurora_not_running")
                return 2
            time.sleep(1)
            continue
        if pid != current_pid or session is None or detached.is_set():
            current_pid = pid
            detached.clear()
            try:
                executable = process_path(pid)
                rva = find_go_symbol_rva(executable, SET_CONFIG_SYMBOL)
                session = frida.attach(pid)
                session.on("detached", lambda *args: detached.set())
                script = session.create_script(build_script(rva, targets))

                def on_message(message: dict[str, object], data: object) -> None:
                    payload = message.get("payload", message)
                    if isinstance(payload, dict) and payload.get("event") in {
                        "inject_error", "shape_mismatch"
                    }:
                        reporter.emit("hook_error", pid=pid, payload=payload)
                    else:
                        reporter.log("hook_message", pid=pid, payload=payload)

                script.on("message", on_message)
                script.load()
                reporter.emit("hook_attached", pid=pid, executable=str(executable), symbol_rva=hex(rva))
                time.sleep(1)
                matches = active_matches(targets)
                if not all(matches.values()):
                    post("stopsb")
                    post("startsb")
                deadline = time.monotonic() + 12
                matches = active_matches(targets)
                while time.monotonic() < deadline and not all(matches.values()):
                    time.sleep(0.25)
                    matches = active_matches(targets)
                reporter.emit("active_rules_verified", pid=pid, matches=matches, ok=all(matches.values()))
                if once:
                    time.sleep(3)
                    return 0 if all(matches.values()) else 2
            except Exception as exc:
                reporter.emit("attach_error", pid=pid, error=f"{type(exc).__name__}: {exc}")
                session = None
                if once:
                    return 2
                time.sleep(5)
                continue
        for _ in range(10):
            if STOP_FILE.exists():
                reporter.emit("stop_requested")
                return 0
            time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep Aurora SetConfig process bypass rules patched in memory.")
    parser.add_argument("--settings", type=Path, default=INSTALL_DIR / "settings.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    mutex = kernel32.CreateMutexW(None, False, INJECTOR_MUTEX)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return 3
    try:
        STOP_FILE.unlink(missing_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
        settings = json.loads(args.settings.read_text(encoding="utf-8"))
        targets = list(dict.fromkeys(str(name) for name in settings["processes"]))
        reporter = Reporter(INSTALL_DIR / "status.json", INSTALL_DIR / "injector.log")
        return maintain(targets, reporter, args.once)
    finally:
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
