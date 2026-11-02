import io
import os
import unittest
from unittest import mock

from vpn_cli import ui


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class UiTests(unittest.TestCase):
    def test_paint_is_plain_when_not_a_tty(self):
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            self.assertEqual(ui.paint("hello", "bold_green", io.StringIO()), "hello")

    def test_paint_adds_green_on_tty(self):
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            self.assertEqual(
                ui.paint("Connected", "bold_green", FakeTTY()),
                "\033[1;32mConnected\033[0m",
            )

    def test_no_color_wins_over_tty(self):
        env = {"TERM": "xterm-256color", "NO_COLOR": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                ui.paint("Connected", "bold_green", FakeTTY()), "Connected"
            )

    def test_force_color_overrides_non_tty(self):
        env = {"TERM": "xterm-256color", "CLICOLOR_FORCE": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                ui.paint("Disconnected", "bold_red", io.StringIO()),
                "\033[1;31mDisconnected\033[0m",
            )

    def test_status_style(self):
        self.assertEqual(ui.status_style("Connected", True), "bold_green")
        self.assertEqual(ui.status_style("Connected", None), "bold_yellow")
        self.assertEqual(ui.status_style("Connected", False), "bold_red")
        self.assertEqual(ui.status_style("Disconnected"), "bold_red")
        self.assertEqual(ui.status_style("Connecting"), "bold_yellow")
        self.assertEqual(ui.status_style("Unable to connect"), "bold_red")

    def test_status_label(self):
        self.assertEqual(ui.status_label("Connected", True), "Connected")
        self.assertEqual(
            ui.status_label("Connected", None), "Connected (unverified)"
        )
        self.assertEqual(ui.status_label("Connected", False), "Not protected")
        self.assertEqual(ui.status_label("Disconnected"), "Disconnected")
        self.assertEqual(ui.status_label(None), "Unknown")

    def test_strip_ansi(self):
        self.assertEqual(ui.strip_ansi("\033[1;32mOK\033[0m"), "OK")

    def test_row_aligns_labels(self):
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            self.assertEqual(
                ui.row("Public IP", "1.2.3.4", stream=io.StringIO()),
                "  Public IP    1.2.3.4",
            )


if __name__ == "__main__":
    unittest.main()
