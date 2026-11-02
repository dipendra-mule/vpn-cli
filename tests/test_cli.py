import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from vpn_cli import cli, config


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"VPN_CLI_CONFIG_DIR": self.tmp.name}
        )
        self.env.start()
        cli._LOOKUP_CACHE.clear()

        self.state = {
            "warp": False,
            "before_ip": "203.0.113.10",
            "after_ip": "104.28.1.2",
        }
        self.connect_calls = 0

        def fake_status():
            if self.state["warp"]:
                return (
                    "Status update: Connected\n"
                    "Mode: Warp\n"
                    "Registration status: Registered\n"
                    "Protocol: WireGuard\n"
                )
            return (
                "Status update: Disconnected\n"
                "Mode: Warp\n"
                "Registration status: Registered\n"
            )

        def fake_trace(timeout=8):
            ip = (
                self.state["after_ip"]
                if self.state["warp"]
                else self.state["before_ip"]
            )
            if self.state["warp"]:
                return {"ip": ip, "warp": "on", "loc": "XX", "colo": "XXX"}
            return {"ip": ip, "warp": "off", "loc": "XX", "colo": "XXX"}

        def fake_connect(timeout=30):
            self.connect_calls += 1
            self.state["warp"] = True
            return subprocess.CompletedProcess(["warp-cli", "connect"], 0, "", "")

        def fake_disconnect(timeout=30):
            self.state["warp"] = False
            return subprocess.CompletedProcess(
                ["warp-cli", "disconnect"], 0, "", ""
            )

        def fake_public_ip(timeout=8):
            if self.state["warp"]:
                return self.state["after_ip"]
            return self.state["before_ip"]

        self.patchers = [
            mock.patch.object(cli.macos, "vpn_services", return_value=[]),
            mock.patch.object(
                cli.warpctl, "find_cli", return_value="/usr/local/bin/warp-cli"
            ),
            mock.patch.object(cli.warpctl, "status_text", side_effect=fake_status),
            mock.patch.object(cli.warpctl, "ensure_warp_mode", return_value=None),
            mock.patch.object(
                cli.warpctl, "registration_status", return_value="Registered"
            ),
            mock.patch.object(cli.warpctl, "connect", side_effect=fake_connect),
            mock.patch.object(
                cli.warpctl, "disconnect", side_effect=fake_disconnect
            ),
            mock.patch.object(cli.warpctl, "wait_for_connected", return_value=True),
            mock.patch.object(
                cli.warpctl, "wait_for_disconnected", return_value=True
            ),
            mock.patch.object(
                cli.warpctl, "version", return_value="warp-cli 2026.8.2115.0"
            ),
            mock.patch.object(cli.ipinfo, "trace", side_effect=fake_trace),
            mock.patch.object(cli.ipinfo, "public_ip", side_effect=fake_public_ip),
            mock.patch.object(cli.ipinfo, "lookup", return_value={}),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.env.stop()
        self.tmp.cleanup()

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def run_cli_colored(self, argv):
        env = {
            "TERM": "xterm-256color",
            "CLICOLOR": "1",
            "CLICOLOR_FORCE": "1",
            "NO_COLOR": "",
        }
        with mock.patch.dict(os.environ, env):
            return self.run_cli(argv)

    def test_connect_changes_ip_and_records_history(self):
        code, out, _ = self.run_cli(["connect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(self.state["warp"])
        self.assertIn("Connected via Cloudflare WARP", out)
        cfg = config.load()
        self.assertEqual(cfg["baseline_ip"], "203.0.113.10")
        self.assertEqual(cfg["warp_ip"], "104.28.1.2")
        self.assertEqual(len(cfg["history"]), 1)

    def test_connect_returns_3_when_ip_is_unchanged(self):
        self.state["after_ip"] = "203.0.113.10"
        code, _, err = self.run_cli(["connect"])
        self.assertEqual(code, cli.EXIT_IP_UNCHANGED)
        self.assertIn("did not change", err)

    def test_connect_allow_same_succeeds(self):
        self.state["after_ip"] = "203.0.113.10"
        code, _, _ = self.run_cli(["connect", "--allow-same"])
        self.assertEqual(code, cli.EXIT_OK)

    def test_already_connected_skips_connect(self):
        self.state["warp"] = True
        code, out, _ = self.run_cli(["connect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("already connected", out)
        self.assertEqual(self.connect_calls, 0)

    def test_disconnect(self):
        self.state["warp"] = True
        code, out, _ = self.run_cli(["disconnect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertFalse(self.state["warp"])
        self.assertIn("Disconnected", out)

    def test_disconnect_when_not_connected(self):
        code, out, _ = self.run_cli(["disconnect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("not connected", out)

    def test_rotate_gets_new_ip(self):
        code, out, _ = self.run_cli(["rotate", "--attempts", "2"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("New IP", out)

    def test_status_json(self):
        code, out, _ = self.run_cli(["status", "--json"])
        self.assertEqual(code, cli.EXIT_OK)
        data = json.loads(out)
        self.assertTrue(data["warp_installed"])
        self.assertEqual(data["state"], "Disconnected")
        self.assertEqual(data["ip"], "203.0.113.10")

    def test_status_human_is_plain_when_piped(self):
        code, out, _ = self.run_cli(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("VPN STATUS", out)
        self.assertNotIn("\033[", out)

    def test_status_connected_is_green(self):
        self.state["warp"] = True
        code, out, _ = self.run_cli_colored(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;32m", out)
        self.assertIn("Connected", out)
        self.assertIn("verified through WARP", out)

    def test_status_disconnected_is_red(self):
        code, out, _ = self.run_cli_colored(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;31m", out)
        self.assertIn("Disconnected", out)
        self.assertIn("normal ISP route", out)

    def test_status_connected_unverified_is_yellow(self):
        self.state["warp"] = True
        with mock.patch.object(
            cli.ipinfo,
            "trace",
            side_effect=cli.ipinfo.NetworkError("offline"),
        ):
            code, out, _ = self.run_cli_colored(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;33m", out)
        self.assertIn("Connected (unverified)", out)

    def test_status_warp_off_is_not_protected(self):
        self.state["warp"] = True
        trace = {
            "ip": self.state["after_ip"],
            "warp": "off",
            "loc": "XX",
            "colo": "XXX",
        }
        with mock.patch.object(cli.ipinfo, "trace", return_value=trace):
            code, out, _ = self.run_cli_colored(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;31m", out)
        self.assertIn("Not protected", out)
        self.assertIn("traffic is not using WARP", out)

    def test_status_shows_unable_reason(self):
        status = (
            "Status update: Unable to connect\n"
            "Reason: no network\n"
            "Mode: Warp\n"
            "Registration status: Registered\n"
        )
        with mock.patch.object(cli.warpctl, "status_text", return_value=status):
            code, out, _ = self.run_cli(["status"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Unable to connect", out)
        self.assertIn("Reason", out)
        self.assertIn("no network", out)

    def test_connect_output_is_green(self):
        code, out, _ = self.run_cli_colored(["connect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;32m", out)
        self.assertIn("Connected via Cloudflare WARP", out)
        self.assertIn("verified through WARP", out)

    def test_disconnect_output_is_red(self):
        self.state["warp"] = True
        code, out, _ = self.run_cli_colored(["disconnect"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("\033[1;31m", out)
        self.assertIn("Disconnected", out)
        self.assertIn("normal ISP route", out)

    def test_status_json_has_no_ansi(self):
        code, out, _ = self.run_cli(["status", "--json"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertNotIn("\033[", out)
        self.assertIn('"warp_on"', out)

    def test_connect_without_warp_installed(self):
        with mock.patch.object(
            cli.warpctl,
            "find_cli",
            side_effect=cli.warpctl.WarpNotInstalled("missing"),
        ):
            code, _, err = self.run_cli(["connect"])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("not installed", err)

    def test_doctor_reports_missing_warp(self):
        with mock.patch.object(
            cli.warpctl,
            "find_cli",
            side_effect=cli.warpctl.WarpNotInstalled("missing"),
        ):
            code, out, _ = self.run_cli(["doctor"])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("FAIL", out)


if __name__ == "__main__":
    unittest.main()
