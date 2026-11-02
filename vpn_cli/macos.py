"""macOS helpers: inspect VPN services registered with the system."""

import re
import subprocess
from typing import Dict, List

STATUS_RE = re.compile(r"\((Connected|Disconnected|Connecting|Disconnecting)\)")
NAME_RE = re.compile(r'"([^"]+)"')


def parse_scutil_list(output: str) -> List[Dict[str, str]]:
    services: List[Dict[str, str]] = []
    for line in output.splitlines():
        status_match = STATUS_RE.search(line)
        name_match = NAME_RE.search(line)
        if not status_match or not name_match:
            continue
        services.append(
            {
                "name": name_match.group(1),
                "status": status_match.group(1),
                "raw": line.strip(),
            }
        )
    return services


def vpn_services() -> List[Dict[str, str]]:
    try:
        proc = subprocess.run(
            ["scutil", "--nc", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return parse_scutil_list(proc.stdout or "")


def is_warp_service(name: str) -> bool:
    lowered = name.lower()
    return "warp" in lowered or "cloudflare" in lowered
