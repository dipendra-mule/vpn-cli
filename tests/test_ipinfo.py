import unittest

from vpn_cli import ipinfo


class TraceParsingTests(unittest.TestCase):
    def test_parse_trace(self):
        text = (
            "fl=abc123\n"
            "h=www.cloudflare.com\n"
            "ip=2001:db8::1\n"
            "loc=XX\n"
            "colo=XXX\n"
            "warp=off\n"
        )
        parsed = ipinfo.parse_trace(text)
        self.assertEqual(parsed["ip"], "2001:db8::1")
        self.assertEqual(parsed["loc"], "XX")
        self.assertEqual(parsed["colo"], "XXX")
        self.assertEqual(parsed["warp"], "off")

    def test_parse_trace_ignores_blank_and_noise(self):
        parsed = ipinfo.parse_trace("\nnot-a-pair\nip=1.2.3.4\n")
        self.assertEqual(parsed, {"ip": "1.2.3.4"})


class IpComparisonTests(unittest.TestCase):
    def test_same_ipv4(self):
        self.assertTrue(ipinfo.same_ip("1.2.3.4", "1.2.3.4"))

    def test_same_ipv6_normalized(self):
        self.assertTrue(ipinfo.same_ip("2001:db8::1", "2001:0db8:0:0:0:0:0:1"))

    def test_different(self):
        self.assertFalse(ipinfo.same_ip("1.2.3.4", "1.2.3.5"))

    def test_none_is_never_same(self):
        self.assertFalse(ipinfo.same_ip(None, "1.2.3.4"))

    def test_normalize(self):
        self.assertEqual(ipinfo.normalize_ip("2001:0db8::1"), "2001:db8::1")
        self.assertIsNone(ipinfo.normalize_ip(""))


class DescribeTests(unittest.TestCase):
    def test_describe_with_metadata(self):
        text = ipinfo.describe(
            "1.2.3.4",
            {"org": "Example", "city": "Example City", "country": "XX"},
        )
        self.assertEqual(text, "1.2.3.4 (Example, Example City, XX)")

    def test_describe_without_metadata(self):
        self.assertEqual(ipinfo.describe("1.2.3.4"), "1.2.3.4")

    def test_describe_unknown(self):
        self.assertEqual(ipinfo.describe(None), "unknown")


if __name__ == "__main__":
    unittest.main()
