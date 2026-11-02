"""Small terminal formatting helpers (colors, labels, aligned rows)."""

import os
import re
import sys
from typing import Any, Optional

ANSI_RE = re.compile(r"\033\[[0-9;]*m")

STYLES = {
    "bold": "1",
    "dim": "2",
    "green": "32",
    "red": "31",
    "yellow": "33",
    "cyan": "36",
    "bold_green": "1;32",
    "bold_red": "1;31",
    "bold_yellow": "1;33",
}

TRANSITION_STATES = ("connecting", "reconnecting", "disconnecting")
UNABLE_STATES = ("unable to connect", "no network")


def color_enabled(stream: Any) -> bool:
    """Return True when ANSI colors should be written to *stream*."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    if os.environ.get("CLICOLOR") == "0":
        return False
    if os.environ.get("CLICOLOR_FORCE", "") not in ("", "0"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, style: Optional[str] = None, stream: Any = None) -> str:
    """Wrap *text* in an ANSI style when the target stream supports it."""
    if not style:
        return text
    target = sys.stdout if stream is None else stream
    if not color_enabled(target):
        return text
    code = STYLES.get(style, style)
    return "\033[{}m{}\033[0m".format(code, text)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _normalized(state: Optional[str]) -> str:
    return (state or "").strip().lower()


def connection_style(state: Optional[str]) -> str:
    """Color for a raw client state, without egress verification."""
    normalized = _normalized(state)
    if normalized == "connected":
        return "bold_green"
    if normalized == "disconnected":
        return "bold_red"
    if normalized in TRANSITION_STATES:
        return "bold_yellow"
    if normalized.startswith("unable") or normalized in UNABLE_STATES:
        return "bold_red"
    return "bold_yellow"


def status_style(state: Optional[str], warp_on: Optional[bool] = None) -> str:
    """Color for the status headline, including traffic verification."""
    normalized = _normalized(state)
    if normalized == "connected":
        if warp_on is True:
            return "bold_green"
        if warp_on is False:
            return "bold_red"
        return "bold_yellow"
    return connection_style(state)


def status_label(state: Optional[str], warp_on: Optional[bool] = None) -> str:
    """Human label for the status headline."""
    normalized = _normalized(state)
    if normalized == "connected":
        if warp_on is True:
            return "Connected"
        if warp_on is False:
            return "Not protected"
        return "Connected (unverified)"
    if normalized == "disconnected":
        return "Disconnected"
    if not normalized:
        return "Unknown"
    return (state or "").strip()


def title(text: str, stream: Any = None) -> str:
    return paint("  {}".format(text), "dim", stream)


def status_header(label: str, style: str, stream: Any = None) -> str:
    return "  {} {}".format(
        paint("●", style, stream),
        paint(label, style, stream),
    )


def row(label: str, value: str, width: int = 13, stream: Any = None) -> str:
    return "  {}{}".format(
        paint(label.ljust(width), "dim", stream),
        value,
    )
