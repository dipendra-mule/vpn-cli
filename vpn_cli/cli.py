"""Command-line interface for vpn-cli."""

import argparse
import json
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, config, ipinfo, macos, ui, warpctl

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_IP_UNCHANGED = 3

_LOOKUP_CACHE: Dict[str, Dict[str, str]] = {}


def _paint(text: str, code: str, stream: Any) -> str:
    return ui.paint(text, code, stream=stream)


def _ok(message: str) -> None:
    print("{} {}".format(_paint("OK", "32", sys.stdout), message))


def _warn(message: str) -> None:
    print(
        "{} {}".format(_paint("WARN", "33", sys.stderr), message),
        file=sys.stderr,
    )


def _error(message: str) -> None:
    print(
        "{} {}".format(_paint("ERROR", "31", sys.stderr), message),
        file=sys.stderr,
    )


def _badge(level: str) -> str:
    codes = {"OK": "green", "WARN": "yellow", "FAIL": "red", "INFO": "cyan"}
    return "[{}]".format(
        ui.paint(level, codes.get(level), stream=sys.stdout)
    )


def _lookup_safe(ip: Optional[str]) -> Dict[str, str]:
    if not ip:
        return {}
    if ip not in _LOOKUP_CACHE:
        _LOOKUP_CACHE[ip] = ipinfo.lookup(ip)
    return _LOOKUP_CACHE[ip]


def _describe(ip: Optional[str]) -> str:
    return ipinfo.describe(ip, _lookup_safe(ip))


def _snapshot() -> Tuple[Optional[str], Dict[str, str]]:
    info: Dict[str, str] = {}
    try:
        info = ipinfo.trace()
    except ipinfo.NetworkError:
        pass
    ip = info.get("ip")
    if not ip:
        ip = ipinfo.public_ip()
    return ip, info


def _wait_trace_warp(want_on: bool, timeout: float = 15.0) -> Dict[str, str]:
    deadline = time.monotonic() + timeout
    last: Dict[str, str] = {}
    while True:
        try:
            candidate = ipinfo.trace(timeout=6)
        except ipinfo.NetworkError:
            candidate = {}
        if candidate:
            last = candidate
            if (candidate.get("warp") == "on") == want_on:
                return candidate
        if time.monotonic() >= deadline:
            return last
        time.sleep(1)


def _register_device(say) -> bool:
    say("First run: registering this device with free WARP...")
    try:
        proc = warpctl.run(
            ["--accept-tos", "registration", "new"], timeout=60
        )
    except warpctl.WarpError as exc:
        _error("WARP registration failed: {}".format(exc))
        return False
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
        _error("WARP registration failed: {}".format(detail or "exit {}".format(proc.returncode)))
        print(
            "Open the Cloudflare WARP app once, accept the privacy policy, "
            "then run `vpn connect` again."
        )
        return False
    return True


def do_connect(
    timeout: float = 30,
    allow_same: bool = False,
    quiet: bool = False,
) -> Tuple[int, Optional[str], Dict[str, str]]:
    say = (lambda *args, **kwargs: None) if quiet else print

    try:
        warpctl.find_cli()
    except warpctl.WarpNotInstalled:
        _error("Cloudflare WARP is not installed.")
        print("Install it with: ~/vpn-cli/install.sh")
        return EXIT_ERROR, None, {}

    cfg = config.load()
    before_ip, _ = _snapshot()
    if before_ip:
        say("Current IP: {}".format(_describe(before_ip)))

    for service in macos.vpn_services():
        if service["status"] == "Connected" and not macos.is_warp_service(service["name"]):
            _warn(
                "Another VPN is connected ({}). It may conflict with WARP.".format(
                    service["name"]
                )
            )

    try:
        status = warpctl.parse_status(warpctl.status_text())
    except warpctl.WarpError as exc:
        _error("WARP daemon is not reachable: {}".format(exc))
        print(
            "Open the Cloudflare WARP app once, accept the privacy policy, "
            "then retry."
        )
        return EXIT_ERROR, None, {}

    was_connected = warpctl.state_is(status["state"], "Connected")

    if not was_connected:
        mode_error = warpctl.ensure_warp_mode()
        if mode_error:
            _warn("Could not force full-tunnel mode: {}".format(mode_error))

        registration = warpctl.registration_status()
        if registration and any(
            marker in registration.lower()
            for marker in ("not registered", "unregistered", "no registration", "not enrolled")
        ):
            if not _register_device(say):
                return EXIT_ERROR, None, {}

        say("Connecting to Cloudflare WARP...")
        proc = warpctl.connect(timeout=20)
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()

        if proc.returncode != 0 and "terms" in combined:
            proc = warpctl.run(["--accept-tos", "connect"], timeout=20)
            combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()

        if (
            proc.returncode != 0
            and "already" not in combined
            and any(
                marker in combined
                for marker in ("register", "enroll", "terms", "privacy")
            )
        ):
            if not _register_device(say):
                return EXIT_ERROR, None, {}
            proc = warpctl.connect(timeout=20)
            combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()

        if proc.returncode != 0 and "already" not in combined:
            detail = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
            _error(
                "warp-cli connect failed: {}".format(
                    detail or "exit {}".format(proc.returncode)
                )
            )
            return EXIT_ERROR, None, {}

        say("Waiting for the tunnel (up to {}s)...".format(int(timeout)))
        if not warpctl.wait_for_connected(timeout):
            _error(
                "WARP did not reach the Connected state within {}s.".format(int(timeout))
            )
            try:
                raw = warpctl.status_text().strip()
                if raw:
                    print(raw)
            except warpctl.WarpError:
                pass
            return EXIT_ERROR, None, {}
    else:
        say("WARP is already connected.")

    after_trace = _wait_trace_warp(True, 15)
    if after_trace.get("warp") != "on":
        _warn("Tunnel is up, but traffic is not exiting through WARP (DNS-only mode?).")
        try:
            warpctl.disconnect(timeout=20)
            warpctl.wait_for_disconnected(15)
            warpctl.ensure_warp_mode()
            warpctl.connect(timeout=20)
            warpctl.wait_for_connected(timeout)
        except warpctl.WarpError as exc:
            _error("Unable to switch to full-tunnel mode: {}".format(exc))
        after_trace = _wait_trace_warp(True, 15)

    if after_trace.get("warp") != "on":
        _error("WARP reports connected, but the public trace still shows warp=off.")
        return EXIT_ERROR, None, after_trace

    after_ip = after_trace.get("ip") or ipinfo.public_ip()
    if not was_connected and not cfg.get("baseline_ip") and before_ip:
        cfg["baseline_ip"] = before_ip
        config.save(cfg)
    config.record_event(cfg, before_ip, after_ip, after_trace)

    if not quiet:
        print("")
        print(
            ui.status_header(
                "Connected via Cloudflare WARP (colo={})".format(
                    after_trace.get("colo") or "?"
                ),
                "bold_green",
            )
        )
        print(ui.row("Before", _describe(before_ip)))
        print(ui.row("After", _describe(after_ip)))
        print(ui.row("Traffic", "verified through WARP (warp=on)"))

    if (
        not was_connected
        and before_ip
        and after_ip
        and ipinfo.same_ip(before_ip, after_ip)
    ):
        if allow_same:
            _warn("The public IP did not change (Cloudflare reused the same egress IP).")
        else:
            _error("The public IP did not change. Try `vpn rotate` or reconnect.")
            return EXIT_IP_UNCHANGED, after_ip, after_trace
    return EXIT_OK, after_ip, after_trace


def do_disconnect(
    timeout: float = 30, quiet: bool = False
) -> Tuple[int, Optional[str], Dict[str, str]]:
    say = (lambda *args, **kwargs: None) if quiet else print

    try:
        warpctl.find_cli()
    except warpctl.WarpNotInstalled:
        _error("Cloudflare WARP is not installed.")
        return EXIT_ERROR, None, {}

    try:
        status = warpctl.parse_status(warpctl.status_text())
    except warpctl.WarpError as exc:
        _error("WARP daemon is not reachable: {}".format(exc))
        return EXIT_ERROR, None, {}

    before_ip, _ = _snapshot()
    if not warpctl.state_is(
        status["state"], "Connected", "Connecting", "Reconnecting"
    ):
        if not quiet:
            print("")
            print(ui.status_header("Disconnected", "bold_red"))
            print(ui.row("WARP client", "not connected"))
            print(ui.row("Public IP", _describe(before_ip)))
        return EXIT_OK, before_ip, {}

    say("Disconnecting from WARP...")
    proc = warpctl.disconnect(timeout=20)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    if proc.returncode != 0 and "not connected" not in combined:
        detail = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
        _error(
            "warp-cli disconnect failed: {}".format(
                detail or "exit {}".format(proc.returncode)
            )
        )
        return EXIT_ERROR, None, {}

    if not warpctl.wait_for_disconnected(timeout):
        _warn("WARP did not report Disconnected within {}s.".format(int(timeout)))

    trace_info = _wait_trace_warp(False, 15)
    after_ip = trace_info.get("ip") or ipinfo.public_ip()
    if not quiet:
        print("")
        print(ui.status_header("Disconnected", "bold_red"))
        print(ui.row("Public IP", _describe(after_ip)))
        if trace_info.get("warp") == "on":
            print(ui.row("Traffic", "still using WARP (warp=on)"))
        elif trace_info:
            print(ui.row("Traffic", "normal ISP route (warp=off)"))
        else:
            print(ui.row("Traffic", "verification unavailable"))
    if trace_info.get("warp") == "on":
        _warn("Trace still reports warp=on; traffic may still be tunnelled.")
    return EXIT_OK, after_ip, trace_info


def cmd_connect(args: argparse.Namespace) -> int:
    cfg = config.load()
    timeout = args.timeout or int(cfg.get("connect_timeout", 30))
    code, _, _ = do_connect(timeout, allow_same=args.allow_same)
    return code


def cmd_disconnect(args: argparse.Namespace) -> int:
    cfg = config.load()
    timeout = args.timeout or int(cfg.get("connect_timeout", 30))
    code, _, _ = do_disconnect(timeout)
    return code


def cmd_reconnect(args: argparse.Namespace) -> int:
    cfg = config.load()
    timeout = args.timeout or int(cfg.get("connect_timeout", 30))
    code, _, _ = do_disconnect(timeout, quiet=True)
    if code != EXIT_OK:
        return code
    code, _, _ = do_connect(timeout)
    return code


def cmd_rotate(args: argparse.Namespace) -> int:
    cfg = config.load()
    timeout = args.timeout or int(cfg.get("connect_timeout", 30))
    attempts = max(1, int(args.attempts))
    previous = cfg.get("warp_ip") or _snapshot()[0]
    print("Current WARP IP: {}".format(previous or "unknown"))

    for attempt in range(1, attempts + 1):
        code, _, _ = do_disconnect(timeout, quiet=True)
        if code != EXIT_OK:
            print("  attempt {}: could not reset the tunnel".format(attempt))
            continue
        code, after_ip, _ = do_connect(timeout, allow_same=True, quiet=True)
        if code != EXIT_OK:
            print("  attempt {}: connect failed".format(attempt))
            continue
        print("  attempt {}: {}".format(attempt, after_ip or "unknown"))
        if previous and after_ip and not ipinfo.same_ip(previous, after_ip):
            _ok("New IP: {} -> {}".format(previous, after_ip))
            print("  {}".format(_describe(after_ip)))
            return EXIT_OK
        previous = after_ip or previous

    _warn(
        "Cloudflare reused the same egress IP across attempts. "
        "Free WARP does not guarantee a new IP on every reconnect."
    )
    return EXIT_IP_UNCHANGED


def _collect_status() -> Dict[str, Any]:
    cfg = config.load()
    data: Dict[str, Any] = {
        "warp_installed": False,
        "warp_cli": None,
        "warp_version": None,
        "state": None,
        "mode": None,
        "registration": None,
        "protocol": None,
        "reason": None,
        "ip": None,
        "ip_meta": {},
        "trace": {},
        "warp_on": None,
        "baseline_ip": cfg.get("baseline_ip"),
        "ip_changed_from_baseline": None,
        "config_path": str(config.config_path()),
    }

    try:
        data["warp_cli"] = warpctl.find_cli()
        data["warp_installed"] = True
    except warpctl.WarpNotInstalled:
        pass

    if data["warp_installed"]:
        data["warp_version"] = warpctl.version()
        try:
            parsed = warpctl.parse_status(warpctl.status_text())
            data["state"] = parsed["state"]
            data["mode"] = parsed["mode"]
            data["registration"] = parsed["registration"]
            data["protocol"] = parsed["protocol"]
            data["reason"] = parsed.get("reason")
        except warpctl.WarpError:
            pass
        if not data["registration"]:
            data["registration"] = warpctl.registration_status()
        settings = warpctl.settings_summary()
        data["mode"] = data["mode"] or settings.get("mode")
        data["protocol"] = data["protocol"] or settings.get("protocol")

    trace_info: Dict[str, str] = {}
    try:
        trace_info = ipinfo.trace()
    except ipinfo.NetworkError:
        pass
    data["trace"] = trace_info
    if trace_info:
        data["warp_on"] = trace_info.get("warp") == "on"
    ip = trace_info.get("ip") or ipinfo.public_ip()
    data["ip"] = ip
    data["ip_meta"] = _lookup_safe(ip)

    baseline = data["baseline_ip"]
    if baseline and ip:
        data["ip_changed_from_baseline"] = not ipinfo.same_ip(baseline, ip)
    return data


def _status_summary(data: Dict[str, Any]) -> str:
    state = (data.get("state") or "").strip().lower()
    warp_on = data.get("warp_on")
    trace_info = data.get("trace") or {}

    if state == "connected":
        if warp_on is True:
            bits = ["warp=on"]
            if trace_info.get("colo"):
                bits.append("colo {}".format(trace_info["colo"]))
            if trace_info.get("loc"):
                bits.append("loc {}".format(trace_info["loc"]))
            return "verified through WARP ({})".format(" · ".join(bits))
        if warp_on is False:
            return "tunnel is up, but traffic is not using WARP (warp=off)"
        return "client is connected; Cloudflare trace could not verify traffic"

    if state == "disconnected":
        if warp_on is True:
            return "client is disconnected, but trace still reports warp=on"
        if warp_on is False:
            return "normal ISP route (warp=off)"
        return "normal ISP route (verification unavailable)"

    if state in ui.TRANSITION_STATES:
        return "changing state..."
    if state.startswith("unable") or state == "no network":
        return "connection failed"
    if not state:
        return "state unknown"
    return (data.get("state") or "").strip()


def cmd_status(args: argparse.Namespace) -> int:
    data = _collect_status()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return EXIT_OK

    if not data["warp_installed"]:
        print(ui.title("VPN STATUS"))
        print("")
        print(ui.status_header("Not installed", "bold_red"))
        print(ui.row("Public IP", _describe(data["ip"])))
        print("  Install it with: ~/vpn-cli/install.sh")
        return EXIT_OK

    state = data["state"] or "Unknown"
    warp_on = data.get("warp_on")

    print(ui.title("VPN STATUS"))
    print("")
    print(
        ui.status_header(
            ui.status_label(state, warp_on),
            ui.status_style(state, warp_on),
        )
    )
    print(ui.row("Traffic", _status_summary(data)))
    print("")

    client = [state]
    if data["mode"]:
        client.append(data["mode"])
    if data["protocol"]:
        client.append(data["protocol"])
    print(ui.row("WARP client", " · ".join(client)))
    if data["reason"]:
        print(ui.row("Reason", data["reason"]))
    if data["registration"]:
        print(ui.row("Registration", data["registration"]))
    print(ui.row("Public IP", _describe(data["ip"])))

    baseline = data["baseline_ip"]
    if baseline:
        changed = data["ip_changed_from_baseline"]
        label = "changed" if changed else "unchanged"
        print(ui.row("Baseline", "{} ({})".format(baseline, label)))
    print(ui.row("Config", data["config_path"]))
    return EXIT_OK


def cmd_ip(args: argparse.Namespace) -> int:
    data = _collect_status()
    if args.json:
        print(
            json.dumps(
                {"ip": data["ip"], "meta": data["ip_meta"]},
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_OK
    print(_describe(data["ip"]))
    return EXIT_OK


def cmd_doctor(_args: argparse.Namespace) -> int:
    failures: List[str] = []

    def report(level: str, label: str, detail: str = "") -> None:
        if level == "FAIL":
            failures.append(label)
        print(
            "{} {}{}".format(
                _badge(level), label, ": {}".format(detail) if detail else ""
            )
        )

    mac_version = platform.mac_ver()[0] or "unknown"
    report("INFO", "Platform", "macOS {} ({})".format(mac_version, platform.machine()))
    report("INFO", "Python", platform.python_version())

    installed = True
    try:
        cli = warpctl.find_cli()
        report("OK", "warp-cli", cli)
        report("OK", "warp-cli version", warpctl.version() or "unknown")
    except warpctl.WarpNotInstalled:
        installed = False
        report("FAIL", "warp-cli", "not installed")
        print("       Install it with: ~/vpn-cli/install.sh")

    if installed:
        if warpctl.daemon_reachable():
            report("OK", "WARP daemon", "reachable")
        else:
            report("FAIL", "WARP daemon", "not reachable")
            print("       Open the Cloudflare WARP app once and accept the privacy policy.")

        try:
            parsed = warpctl.parse_status(warpctl.status_text())
            state = parsed["state"] or "unknown"
            reason = parsed.get("reason")
            normalized = state.lower()
            detail = state + (": {}".format(reason) if reason else "")
            if normalized.startswith("unable") or normalized == "no network":
                report("WARN", "WARP state", detail)
            elif normalized == "connected":
                report(
                    "OK",
                    "WARP state",
                    ui.paint(state, "bold_green", stream=sys.stdout),
                )
            elif normalized == "disconnected":
                report(
                    "INFO",
                    "WARP state",
                    ui.paint(state, "bold_red", stream=sys.stdout),
                )
            else:
                report(
                    "INFO",
                    "WARP state",
                    ui.paint(detail, "bold_yellow", stream=sys.stdout),
                )
            if parsed["mode"]:
                if parsed["mode"].lower().startswith("warp"):
                    report("OK", "WARP mode", parsed["mode"])
                else:
                    report(
                        "WARN",
                        "WARP mode",
                        "{} (full-tunnel mode is 'warp')".format(parsed["mode"]),
                    )
            if parsed["protocol"]:
                report("INFO", "Tunnel protocol", parsed["protocol"])
        except warpctl.WarpError as exc:
            report("FAIL", "WARP status", str(exc))

        registration = warpctl.registration_status()
        if registration:
            level = (
                "WARN"
                if "not registered" in registration.lower()
                else "INFO"
            )
            report(level, "Registration", registration)

        protocol = warpctl.tunnel_protocol()
        if protocol:
            report("INFO", "Protocol check", protocol)

    trace_info: Dict[str, str] = {}
    try:
        trace_info = ipinfo.trace()
        report(
            "OK",
            "Public trace",
            "warp={} ip={} loc={} colo={}".format(
                trace_info.get("warp", "?"),
                trace_info.get("ip", "?"),
                trace_info.get("loc", "?"),
                trace_info.get("colo", "?"),
            ),
        )
    except ipinfo.NetworkError as exc:
        report("FAIL", "Public trace", str(exc))

    ip = trace_info.get("ip") or ipinfo.public_ip()
    if ip:
        meta = _lookup_safe(ip)
        report("OK", "Public IP", ipinfo.describe(ip, meta))
    else:
        report("WARN", "Public IP", "unavailable")

    conflicts = [
        service
        for service in macos.vpn_services()
        if service["status"] == "Connected"
        and not macos.is_warp_service(service["name"])
    ]
    if conflicts:
        for service in conflicts:
            report(
                "WARN",
                "Conflicting VPN",
                "{} is Connected".format(service["name"]),
            )
    else:
        report("OK", "Conflicting VPNs", "none connected")

    path = config.config_path()
    if path.exists():
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            report("WARN", "Config permissions", "{} ({:o})".format(path, mode))
        else:
            report("OK", "Config", "{} ({:o})".format(path, mode))
    else:
        report("INFO", "Config", "{} (not created yet)".format(path))

    if failures:
        message = "{} check(s) failed: {}".format(
            len(failures), ", ".join(failures)
        )
        _error(message)
        return EXIT_ERROR
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.clear:
        cfg["baseline_ip"] = None
        config.save(cfg)
        print("Baseline cleared.")
        return EXIT_OK
    ip, _ = _snapshot()
    if not ip:
        _error("Could not determine the current public IP.")
        return EXIT_ERROR
    cfg["baseline_ip"] = ip
    config.save(cfg)
    _ok("Baseline set to {}.".format(ip))
    return EXIT_OK


def cmd_version(_args: argparse.Namespace) -> int:
    print("vpn-cli {}".format(__version__))
    try:
        version = warpctl.version()
    except warpctl.WarpNotInstalled:
        print("warp-cli: not installed")
        return EXIT_OK
    print("warp-cli: {}".format(version or "unknown"))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vpn",
        description="Personal VPN CLI powered by free Cloudflare WARP.",
        epilog=(
            "Examples: vpn connect | vpn status | vpn ip | "
            "vpn disconnect | vpn rotate"
        ),
    )
    parser.add_argument(
        "--version", action="version", version="vpn-cli {}".format(__version__)
    )
    sub = parser.add_subparsers(dest="command", required=True)

    connect = sub.add_parser(
        "connect",
        aliases=["up", "on"],
        help="Connect and verify the public IP changed",
    )
    connect.add_argument("--timeout", type=int, help="Seconds to wait for the tunnel")
    connect.add_argument(
        "--allow-same",
        action="store_true",
        help="Succeed even if the public IP does not change",
    )
    connect.set_defaults(func=cmd_connect)

    disconnect = sub.add_parser(
        "disconnect",
        aliases=["down", "off"],
        help="Disconnect and restore the original route",
    )
    disconnect.add_argument("--timeout", type=int, help="Seconds to wait")
    disconnect.set_defaults(func=cmd_disconnect)

    reconnect = sub.add_parser("reconnect", help="Disconnect and connect again")
    reconnect.add_argument("--timeout", type=int, help="Seconds to wait")
    reconnect.set_defaults(func=cmd_reconnect)

    rotate = sub.add_parser(
        "rotate", help="Reconnect until the public IP changes (best effort)"
    )
    rotate.add_argument("--attempts", type=int, default=3, help="Maximum reconnects")
    rotate.add_argument("--timeout", type=int, help="Seconds to wait per attempt")
    rotate.set_defaults(func=cmd_rotate)

    status = sub.add_parser("status", help="Show WARP state and public IP")
    status.add_argument("--json", action="store_true", help="Machine-readable output")
    status.set_defaults(func=cmd_status)

    ip_parser = sub.add_parser("ip", help="Print the current public IP")
    ip_parser.add_argument("--json", action="store_true", help="Machine-readable output")
    ip_parser.set_defaults(func=cmd_ip)

    doctor = sub.add_parser("doctor", help="Diagnose the VPN setup")
    doctor.set_defaults(func=cmd_doctor)

    baseline = sub.add_parser(
        "baseline", help="Record the current IP as your home IP"
    )
    baseline.add_argument("--clear", action="store_true", help="Forget the baseline")
    baseline.set_defaults(func=cmd_baseline)

    version = sub.add_parser("version", help="Show CLI and warp-cli versions")
    version.set_defaults(func=cmd_version)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except warpctl.WarpNotInstalled as exc:
        _error(str(exc))
        return EXIT_ERROR
    except warpctl.WarpError as exc:
        _error(str(exc))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
