"""Public IP and geolocation helpers using only the standard library."""

import ipaddress
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
IPIFY_URL = "https://api.ipify.org?format=json"
IPINFO_URL = "https://ipinfo.io/{ip}/json"
USER_AGENT = "vpn-cli/1.0 (personal macOS)"


class NetworkError(RuntimeError):
    """Raised when a public IP endpoint cannot be reached."""


def _fetch(url: str, timeout: float = 8.0) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NetworkError(str(exc)) from exc


def parse_trace(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def trace(timeout: float = 8.0) -> Dict[str, str]:
    return parse_trace(_fetch(TRACE_URL, timeout))


def ipify(timeout: float = 8.0) -> Optional[str]:
    try:
        payload = json.loads(_fetch(IPIFY_URL, timeout))
    except (NetworkError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    ip = payload.get("ip")
    return ip if isinstance(ip, str) and ip else None


def public_ip(timeout: float = 8.0) -> Optional[str]:
    try:
        ip = trace(timeout).get("ip")
        if ip:
            return ip
    except NetworkError:
        pass
    return ipify(timeout)


def normalize_ip(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text or None


def same_ip(first: Optional[str], second: Optional[str]) -> bool:
    left = normalize_ip(first)
    right = normalize_ip(second)
    return bool(left and right and left == right)


def lookup(ip: Optional[str], timeout: float = 6.0) -> Dict[str, str]:
    if not ip:
        return {}
    try:
        payload = json.loads(_fetch(IPINFO_URL.format(ip=ip), timeout))
    except (NetworkError, ValueError):
        return {}
    if not isinstance(payload, dict) or not payload.get("ip"):
        return {}
    keys = ("ip", "city", "region", "country", "org")
    return {key: str(payload[key]) for key in keys if payload.get(key)}


def describe(ip: Optional[str], meta: Optional[Dict[str, str]] = None) -> str:
    if not ip:
        return "unknown"
    parts = []
    meta = meta or {}
    for key in ("org", "city", "region", "country"):
        value = meta.get(key)
        if value and value not in parts:
            parts.append(value)
    if not parts:
        return ip
    return "{} ({})".format(ip, ", ".join(parts))
