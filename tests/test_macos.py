import unittest

from vpn_cli import macos


SAMPLE = """Available network connection services in the current set (*=enabled):
* (Disconnected)   00000000-0000-0000-0000-000000000000 VPN (com.example.vpn) "ExampleVPN"                     [VPN:com.example.vpn]
"""


class ScutilParsingTests(unittest.TestCase):
    def test_parse_example_vpn_line(self):
        services = macos.parse_scutil_list(SAMPLE)
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["name"], "ExampleVPN")
        self.assertEqual(services[0]["status"], "Disconnected")

    def test_parse_connected_warp_line(self):
        output = (
            '* (Connected)   ABC VPN (com.cloudflare.1dot1dot1dot1.macos) '
            '"CloudflareWARP"   [VPN:com.cloudflare.1dot1dot1dot1.macos]\n'
        )
        services = macos.parse_scutil_list(output)
        self.assertEqual(services[0]["name"], "CloudflareWARP")
        self.assertEqual(services[0]["status"], "Connected")
        self.assertTrue(macos.is_warp_service(services[0]["name"]))

    def test_parse_ignores_header(self):
        self.assertEqual(macos.parse_scutil_list("Available services:\n"), [])

    def test_warp_name_detection(self):
        self.assertTrue(macos.is_warp_service("Cloudflare WARP"))
        self.assertFalse(macos.is_warp_service("ExampleVPN"))


if __name__ == "__main__":
    unittest.main()
