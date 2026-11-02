"""Thin, defensive wrapper around Cloudflare's warp-cli."""

import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional

CLI_CANDIDATES = (
    "warp-cli",
    "/usr/local/bin/warp-cli",
    "/opt/homebrew/bin/warp-cli",
    "/Applications/Cloudflare WARP.app/Contents/Resources/warp-cli",
    "/Applications/Cloudflare WARP.app/Contents/MacOS/warp-cli",
)

STATE_RE = re.compile(r"^\s*(?:Status update|Status)\s*:\s*(.+?)\s*$", re.I | re.M)
MODE_RE = re.compile(r"^\s*(?:Mode|WARP mode)\s*:\s*(.+?)\s*$", re.I | re.M)
REGISTRATION_RE = re.compile(
    r"^\s*Registration(?:\s+status)?\s*:\s*(.+?)\s*$", re.I | re.M
)
PROTOCOL_RE = re.compile(
    r"^\s*(?:Tunnel protocol|Protocol)\s*:\s*(.+?)\s*$", re.I | re.M
)
REASON_RE = re.compile(r"^\s*Reason\s*:\s*(.+?)\s*$", re.I | re.M)
SETTINGS_PROTOCOL_RE = re.compile(
    r"WARP tunnel protocol\s*:\s*(\S+)", re.I
)
SETTINGS_MODE_RE = re.compile(
    r"^\s*(?:\([^)]*\)\s*)?Mode\s*:\s*(\S+)", re.I | re.M
)
KNOWN_STATES = (
    "connected",
    "disconnected",
    "connecting",
    "disconnecting",
    "reconnecting",
)


class WarpError(RuntimeError):
    """Raised when warp-cli fails or cannot be reached."""


class WarpNotInstalled(WarpError):
    """Raised when warp-cli is not present on this machine."""


def find_cli() -> str:
    for candidate in CLI_CANDIDATES:
        if os.path.sep in candidate:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    raise WarpNotInstalled(
        "warp-cli was not found. Install Cloudflare WARP first "
        "(run ~/vpn-cli/install.sh)."
    )


def run(
    args: List[str], timeout: Optional[float] = None
) -> subprocess.CompletedProcess:
    cli = find_cli()
    command = [cli] + list(args)
    effective_timeout = timeout if timeout is not None else 20
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WarpError(
            "warp-cli timed out after {}s: {}".format(
                effective_timeout, " ".join(args)
            )
        ) from exc
    except OSError as exc:
        raise WarpError(str(exc)) from exc


def _output(proc: subprocess.CompletedProcess) -> str:
    return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def version() -> Optional[str]:
    for args in (["--version"], ["version"], ["-v"]):
        try:
            proc = run(args, timeout=5)
        except WarpError:
            continue
        text = _output(proc)
        if proc.returncode == 0 and text:
            return text.splitlines()[0].strip()
    return None


def help_text() -> str:
    try:
        proc = run(["--help"], timeout=8)
    except WarpError:
        return ""
    return _output(proc)


def status_text() -> str:
    proc = run(["status"], timeout=10)
    text = _output(proc)
    if proc.returncode != 0:
        raise WarpError(text or "warp-cli status exited {}".format(proc.returncode))
    return text


def parse_status(text: str) -> Dict[str, Optional[str]]:
    state: Optional[str] = None
    match = STATE_RE.search(text)
    if match:
        state = match.group(1).strip()
    else:
        for line in text.splitlines():
            if line.strip().lower() in KNOWN_STATES:
                state = line.strip()
                break
    if state:
        state = state.rstrip(".")

    mode_match = MODE_RE.search(text)
    registration_match = REGISTRATION_RE.search(text)
    protocol_match = PROTOCOL_RE.search(text)
    reason_match = REASON_RE.search(text)
    return {
        "state": state,
        "mode": mode_match.group(1).strip() if mode_match else None,
        "registration": (
            registration_match.group(1).strip() if registration_match else None
        ),
        "protocol": (
            protocol_match.group(1).strip() if protocol_match else None
        ),
        "reason": reason_match.group(1).strip() if reason_match else None,
        "raw": text,
    }


def state_is(state: Optional[str], *names: str) -> bool:
    if not state:
        return False
    wanted = {name.strip().lower() for name in names}
    return state.strip().lower() in wanted


def is_connected() -> bool:
    return state_is(parse_status(status_text())["state"], "Connected")


def registration_status() -> Optional[str]:
    for args in (
        ["registration", "show"],
        ["registration", "status"],
        ["account"],
    ):
        try:
            proc = run(args, timeout=8)
        except WarpError:
            continue
        text = _output(proc)
        lowered = text.lower()
        if "missing registration" in lowered or "not registered" in lowered:
            return "Not registered"
        if proc.returncode != 0 or not text:
            continue
        if "usage" in lowered:
            continue
        match = REGISTRATION_RE.search(text)
        if match:
            return match.group(1).strip()
        first_line = text.splitlines()[0].strip()
        if first_line.lower().startswith("account type:"):
            account_type = first_line.split(":", 1)[1].strip()
            return "Registered ({})".format(account_type)
        return first_line
    return None


def settings_summary() -> Dict[str, str]:
    try:
        proc = run(["settings"], timeout=8)
    except WarpError:
        return {}
    if proc.returncode != 0:
        return {}
    text = _output(proc)
    summary: Dict[str, str] = {}
    mode_match = SETTINGS_MODE_RE.search(text)
    if mode_match:
        summary["mode"] = mode_match.group(1).strip()
    protocol_match = SETTINGS_PROTOCOL_RE.search(text)
    if protocol_match:
        summary["protocol"] = protocol_match.group(1).strip()
    return summary


def tunnel_protocol() -> Optional[str]:
    try:
        proc = run(["settings"], timeout=8)
    except WarpError:
        return None
    text = _output(proc)
    if proc.returncode != 0 or not text:
        return None
    match = SETTINGS_PROTOCOL_RE.search(text)
    if match:
        return match.group(1).strip()
    try:
        proc = run(["tunnel", "protocol"], timeout=8)
    except WarpError:
        return None
    text = _output(proc)
    if proc.returncode != 0 or not text or "usage" in text.lower():
        return None
    match = PROTOCOL_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.splitlines()[0].strip()


def daemon_reachable() -> bool:
    try:
        status_text()
        return True
    except WarpError:
        return False


def connect(timeout: float = 30) -> subprocess.CompletedProcess:
    return run(["connect"], timeout=timeout)


def disconnect(timeout: float = 30) -> subprocess.CompletedProcess:
    return run(["disconnect"], timeout=timeout)


def wait_for_connected(timeout: float = 30, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = parse_status(status_text())["state"]
        except WarpError:
            state = None
        if state_is(state, "Connected"):
            return True
        if state_is(state, "Unable to connect", "No network") or (
            state or ""
        ).lower().startswith("unable"):
            return False
        time.sleep(interval)
    return False


def wait_for_disconnected(timeout: float = 30, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = parse_status(status_text())["state"]
        except WarpError:
            state = None
        if state_is(state, "Disconnected"):
            return True
        time.sleep(interval)
    return False


def ensure_warp_mode() -> Optional[str]:
    """Force full-tunnel mode. Returns an error string, or None on success."""
    help_output = help_text().lower()
    candidates = []
    if re.search(r"(^|\s)mode(\s|$)", help_output):
        candidates.append(["mode", "warp"])
    if "set-mode" in help_output:
        candidates.append(["set-mode", "warp"])
    if not candidates:
        candidates = [["mode", "warp"], ["set-mode", "warp"]]

    errors = []
    for args in candidates:
        try:
            proc = run(args, timeout=10)
        except WarpError as exc:
            errors.append(str(exc))
            continue
        if proc.returncode != 0:
            errors.append(_output(proc) or "exit {}".format(proc.returncode))
            continue
        try:
            mode = parse_status(status_text()).get("mode")
        except WarpError:
            return None
        if not mode or mode.strip().lower().startswith("warp"):
            return None
        errors.append("mode is still {}".format(mode))
    return errors[-1] if errors else "could not change WARP mode"
