import subprocess
import unittest
from unittest import mock

from vpn_cli import warpctl


class ParseStatusTests(unittest.TestCase):
    def test_status_update_connected(self):
        parsed = warpctl.parse_status(
            "Status update: Connected\nMode: Warp\nProtocol: WireGuard\n"
        )
        self.assertEqual(parsed["state"], "Connected")
        self.assertEqual(parsed["mode"], "Warp")
        self.assertEqual(parsed["protocol"], "WireGuard")

    def test_status_update_disconnected(self):
        parsed = warpctl.parse_status("Status update: Disconnected\n")
        self.assertEqual(parsed["state"], "Disconnected")

    def test_plain_state_line(self):
        self.assertEqual(warpctl.parse_status("Connected\n")["state"], "Connected")
        self.assertEqual(
            warpctl.parse_status("Disconnected\n")["state"], "Disconnected"
        )

    def test_registration_line(self):
        parsed = warpctl.parse_status(
            "Status update: Disconnected\nRegistration status: Registered\n"
        )
        self.assertEqual(parsed["registration"], "Registered")

    def test_unable_to_connect(self):
        parsed = warpctl.parse_status("Status update: Unable to connect\n")
        self.assertEqual(parsed["state"], "Unable to connect")

    def test_reason_line(self):
        parsed = warpctl.parse_status(
            "Status update: Unable\nReason: Registration Missing due to: Daemon Startup\n"
        )
        self.assertEqual(parsed["state"], "Unable")
        self.assertEqual(
            parsed["reason"], "Registration Missing due to: Daemon Startup"
        )


class StateHelperTests(unittest.TestCase):
    def test_state_is_case_insensitive(self):
        self.assertTrue(warpctl.state_is("Connected", "connected"))
        self.assertFalse(warpctl.state_is("Disconnected", "Connected"))

    def test_state_is_none(self):
        self.assertFalse(warpctl.state_is(None, "Connected"))


class ModeTests(unittest.TestCase):
    @mock.patch(
        "vpn_cli.warpctl.status_text",
        return_value="Status update: Disconnected\nMode: Warp\n",
    )
    @mock.patch("vpn_cli.warpctl.run")
    @mock.patch("vpn_cli.warpctl.help_text", return_value="mode set-mode")
    def test_ensure_warp_mode_uses_mode_command(self, _help, run_mock, _status):
        run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertIsNone(warpctl.ensure_warp_mode())
        self.assertEqual(run_mock.call_args[0][0], ["mode", "warp"])

    @mock.patch(
        "vpn_cli.warpctl.status_text",
        return_value="Status update: Disconnected\nMode: 1.1.1.1\n",
    )
    @mock.patch("vpn_cli.warpctl.run")
    @mock.patch("vpn_cli.warpctl.help_text", return_value="set-mode")
    def test_ensure_warp_mode_reports_failure(self, _help, run_mock, _status):
        run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertIsNotNone(warpctl.ensure_warp_mode())


if __name__ == "__main__":
    unittest.main()


class SettingsTests(unittest.TestCase):
    @mock.patch("vpn_cli.warpctl.run")
    def test_settings_summary(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            [],
            0,
            "(user set)\tMode: Warp\n"
            "(network policy)\tWARP tunnel protocol: MASQUE\n",
            "",
        )
        self.assertEqual(
            warpctl.settings_summary(),
            {"mode": "Warp", "protocol": "MASQUE"},
        )

    @mock.patch("vpn_cli.warpctl.run")
    def test_registration_status_account_type(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            [], 0, "Account type: Free\nID: abc\n", ""
        )
        self.assertEqual(warpctl.registration_status(), "Registered (Free)")

    @mock.patch("vpn_cli.warpctl.run")
    def test_registration_status_missing(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            [], 1, "", "Error: Missing registration. Try running: warp-cli registration new"
        )
        self.assertEqual(warpctl.registration_status(), "Not registered")
