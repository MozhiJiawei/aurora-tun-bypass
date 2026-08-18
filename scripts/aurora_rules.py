"""Pure helpers for validating Aurora's active routing rules."""

from __future__ import annotations

import json
import re


PROCESS_NAMES = re.compile(r"(?:^|\s)process_name=\[([^\]]*)\]")


def direct_process_names(raw: str) -> set[str]:
    """Return exact, case-folded process names from active direct rules."""
    payload = json.loads(raw)
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        raise ValueError("Aurora /rules response does not contain a rules list")
    names: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or str(rule.get("proxy", "")).casefold() != "direct":
            continue
        match = PROCESS_NAMES.search(str(rule.get("payload", "")))
        if match:
            names.update(name.casefold() for name in match.group(1).split() if name)
    return names


def active_matches(raw: str, targets: list[str]) -> dict[str, bool]:
    names = direct_process_names(raw)
    return {target: target.casefold() in names for target in targets}
