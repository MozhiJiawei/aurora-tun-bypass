---
name: aurora-tun-bypass
description: Inspect, diagnose, safely patch, and restore Aurora Slim's encrypted Windows TUN configuration, and investigate its in-memory refresh behavior. Use when selected Windows executables must bypass Aurora TUN, when process_name rules disappear after Aurora or Windows restarts, or when a durable in-memory injection point must be verified against Aurora's internal GetSBConfig/SetConfig refresh chain.
---

# Aurora TUN Bypass

Safely add Windows executable names to Aurora Slim's existing TUN `direct` rule while preserving global proxying for all unmatched traffic.

## Workflow

1. Confirm that the user wants a configuration change, not only diagnosis. Identify every executable involved, including launchers and child processes. Prefer `Get-CimInstance Win32_Process` or `Get-Process` to discover names; do not guess from window titles alone.
2. Run the dependency check from the workspace root:

   ```powershell
   python skills/aurora-tun-bypass/verify_dependencies.py
   ```

3. Inspect only the routing summary. Do not dump the decrypted top-level configuration:

   ```powershell
   python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py inspect
   ```

4. Dry-run the requested change and write artifacts under `.tmp/aurora-tun-bypass/<task>/`:

   ```powershell
   python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py patch `
     --process my.exe --process my_new.exe `
     --output-dir .tmp/aurora-tun-bypass/mhxy
   ```

5. Before any live persistence or injection work, read [docs/behavior-findings.md](docs/behavior-findings.md). Treat it as the maintained source of truth for verified Aurora behavior and append newly verified findings during the investigation.
6. Use `--reload-core --apply` only as a diagnostic probe. Current Aurora Slim `5.2.4` testing proves that `startsb` regenerates the file from internal state and removes the external patch; a successful disk write is not a successful live repair.
7. For durable enforcement, install `install-memory-hook`. It dynamically resolves the current Go `Box.SetConfig` symbol, merges process names into each in-memory configuration refresh, and stays attached for the Aurora process lifetime. Re-running the command merges new targets and replaces the running maintainer cleanly. The old file watcher is removed and must not be used.
8. Verify every runtime experiment with `GET http://127.0.0.1:19090/rules`, then force one `stopsb/startsb` refresh and verify again. Require `status.json` to report `active_rules_verified` with `ok: true`.

   ```powershell
   python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py restore `
     --backup .tmp/aurora-tun-bypass/mhxy/backups/aurora-config-<timestamp>.enc `
     --apply
   ```

## Safety Rules

- Make no live-file or process-memory change without explicit user authorization. Use file apply only as a diagnostic probe; use the memory hook for durable behavior.
- `install-memory-hook` adds an HKCU Run entry and a local Frida runtime under `%LOCALAPPDATA%\AuroraTunBypass`. Do this only for an authorized persistence request and report the installed process and status.
- Never include the user's encrypted configuration, decrypted JSON, account data, or backups in source control.
- Patch only existing `direct` rules containing a `process_name` list. Stop if the expected route shape is missing; do not invent a rule automatically.
- Preserve all unrelated configuration fields and whether each nested TUN config is stored as a JSON string or object.
- Target `global_tun_config` and `tun_config` by default. Use repeated `--config-key` flags only when inspection proves another key is required.
- Treat embedded format details as version-sensitive. Read [references/aurora-format.md](references/aurora-format.md) before adapting the script to another Aurora edition or after an Aurora update.
- Use `--config` with a copied file for tests. Do not forward-test against a live installation.

## Completion Standard

- For a file diagnostic, require a clean dry-run, backup before apply, successful decrypt/digest/round-trip checks, and report that it is not persistent.
- For persistent enforcement, require the HKCU Run entry, exactly one live maintainer, `active_rules_verified` with `ok: true`, and exact target-name matches in active direct `/rules` both before and after one forced Aurora core refresh.
- For uninstall, require the startup entry and live maintainer to be gone; reload the core so injected rules are discarded immediately.
- In every mode, confirm unmatched traffic still uses Aurora's existing proxy fallback. Disk inspection alone never satisfies persistent completion.
