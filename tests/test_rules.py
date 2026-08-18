from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aurora_rules import active_matches  # noqa: E402
from aurora_tun_bypass import direct_process_rule  # noqa: E402


class ActiveRulesTests(unittest.TestCase):
    def test_requires_exact_name_on_direct_proxy(self) -> None:
        raw = json.dumps(
            {
                "rules": [
                    {"payload": "process_name=[my_new.exe Weixin.exe]", "proxy": "direct"},
                    {"payload": "process_name=[my.exe]", "proxy": "proxy"},
                ]
            }
        )
        self.assertEqual(
            active_matches(raw, ["my.exe", "my_new.exe", "weixin.exe"]),
            {"my.exe": False, "my_new.exe": True, "weixin.exe": True},
        )

    def test_rejects_missing_rules_shape(self) -> None:
        with self.assertRaises(ValueError):
            active_matches("{}", ["my.exe"])


class ConfigShapeTests(unittest.TestCase):
    def test_requires_one_direct_process_rule(self) -> None:
        config = {
            "route": {
                "rules": [
                    {"outbound": "direct", "process_name": []},
                    {"outbound": "direct", "process_name": []},
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "found 2"):
            direct_process_rule(config, "tun_config")


if __name__ == "__main__":
    unittest.main()
