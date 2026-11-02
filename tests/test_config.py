import json
import os
import tempfile
import unittest
from unittest import mock

from vpn_cli import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"VPN_CLI_CONFIG_DIR": self.tmp.name}
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_defaults_when_missing(self):
        cfg = config.load()
        self.assertEqual(cfg["connect_timeout"], 30)
        self.assertIsNone(cfg["baseline_ip"])
        self.assertEqual(cfg["history"], [])

    def test_roundtrip(self):
        cfg = config.load()
        cfg["baseline_ip"] = "1.2.3.4"
        config.save(cfg)
        self.assertEqual(config.load()["baseline_ip"], "1.2.3.4")

        with open(config.config_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        self.assertEqual(stored["baseline_ip"], "1.2.3.4")

    def test_permissions_are_private(self):
        config.save(config.load())
        mode = config.config_path().stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_corrupt_file_falls_back_to_defaults(self):
        path = config.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(config.load()["connect_timeout"], 30)

    def test_history_is_trimmed(self):
        cfg = config.load()
        for index in range(60):
            config.record_event(
                cfg,
                "203.0.113.10",
                "104.28.1.{}".format(index),
                {"warp": "on", "loc": "XX", "colo": "XXX"},
            )
        cfg = config.load()
        self.assertEqual(len(cfg["history"]), 50)
        self.assertEqual(cfg["warp_ip"], "104.28.1.59")


if __name__ == "__main__":
    unittest.main()
