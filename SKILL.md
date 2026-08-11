---
name: aurora-tun-bypass
description: Inspect, patch, and restore Aurora Slim's encrypted Windows configuration so selected executable names bypass TUN proxying through existing direct-routing rules. Use when Codex needs to exclude a Windows game or application from Aurora TUN global or smart proxy mode, add process_name entries such as my.exe and my_new.exe, verify Aurora's encrypted configuration digest, create a safe backup, or roll back an Aurora routing-rule change.
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

5. Ask the user to exit Aurora completely, including its tray process. Re-run the same command with `--apply`. The script refuses to modify the live default config while Aurora is running unless `--allow-running` is explicitly supplied. Prefer exiting Aurora over overriding this guard.
6. Confirm `digest_ok: true`, `round_trip_ok: true`, the expected process names, and the reported backup path. Ask the user to reopen Aurora and reconnect.
7. If routing is wrong, exit Aurora and restore the exact backup. The restore command creates a second pre-restore snapshot before replacement:

   ```powershell
   python skills/aurora-tun-bypass/scripts/aurora_tun_bypass.py restore `
     --backup .tmp/aurora-tun-bypass/mhxy/backups/aurora-config-<timestamp>.enc `
     --apply
   ```

## Safety Rules

- Make no live-file change without explicit user authorization.
- Never include the user's encrypted configuration, decrypted JSON, account data, or backups in source control.
- Patch only existing `direct` rules containing a `process_name` list. Stop if the expected route shape is missing; do not invent a rule automatically.
- Preserve all unrelated configuration fields and whether each nested TUN config is stored as a JSON string or object.
- Target `global_tun_config` and `tun_config` by default. Use repeated `--config-key` flags only when inspection proves another key is required.
- Treat embedded format details as version-sensitive. Read [references/aurora-format.md](references/aurora-format.md) before adapting the script to another Aurora edition or after an Aurora update.
- Use `--config` with a copied file for tests. Do not forward-test against a live installation.

## Completion Standard

- Dependency check passes.
- Dry-run reports the intended additions and no unexpected config keys.
- Apply creates a timestamped backup before replacement.
- The written file decrypts successfully, its SHA-256 digest matches, and encryption round-trip validation passes.
- Aurora is restarted by the user and the target application works while unmatched traffic remains proxied.
