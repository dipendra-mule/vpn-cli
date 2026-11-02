# vpn — free VPN CLI (macOS)

A small command-line VPN that changes your public IP using **Cloudflare WARP**
(free tier). No account, no subscription, no server, no Homebrew.

```
$ vpn connect
Current IP: 203.0.113.10 (Example ISP, Example City, XX)
Waiting for the tunnel (up to 30s)...

  ● Connected via Cloudflare WARP (colo=XXX)
    Before       203.0.113.10 (Example ISP, Example City, XX)
    After        104.28.x.x (Cloudflare, Example City, XX)
    Traffic      verified through WARP (warp=on)
```

The CLI verifies the change through Cloudflare's trace endpoint
(`warp=on`) instead of trusting `warp-cli` alone.

## Status colors

`vpn status` uses a green headline when WARP is connected and verified,
red when disconnected (or the tunnel is up but traffic is not using WARP),
and yellow while connecting or when the trace check cannot verify traffic.
The state word is always printed, so the output still works without color.

```bash
vpn status                 # colored in a terminal
vpn status | cat           # plain when piped
NO_COLOR=1 vpn status      # disable color explicitly
```

```
$ vpn status

  VPN STATUS

  ● Connected
    Traffic      verified through WARP (warp=on · colo XXX · loc XX)

    WARP client  Connected · Warp · MASQUE
    Registration Registered (Free)
    Public IP    104.28.x.x (Cloudflare, Example City, XX)
    Baseline     203.0.113.10 (changed)
    Config       /Users/you/.config/vpn-cli/config.json
```

## Requirements

- macOS (tested on macOS 26.6, Tahoe; WARP supports Sonoma 14+)
- Python 3.9+ (uses only the standard library)
- Admin password once, for the WARP installer

## Install

```bash
cd ~/vpn-cli
./install.sh
```

The installer:

1. Downloads the official signed Cloudflare WARP package
   (`downloads.cloudflareclient.com/v1/download/macos/ga`).
2. Verifies the package signature with `pkgutil --check-signature`.
3. Installs it with the system installer.
4. Symlinks `bin/vpn` to `~/.local/bin/vpn` (already on your PATH).

Already have WARP? Link only:

```bash
./install.sh --cli-only
```

If `~/vpn-cli` is not where you want it, move the folder and rerun `install.sh`.

### First run

If this is the first WARP install, open the app once and accept the privacy
policy (the installer launches it for you). Then:

```bash
vpn doctor
vpn connect
```

`vpn connect` registers the device automatically if needed. The first
registration runs `warp-cli --accept-tos registration new`, which accepts
Cloudflare's Terms of Service for the free client on your behalf.

## Commands

| Command | What it does |
| --- | --- |
| `vpn connect` | Connect and verify that the public IP changed (`up`/`on` aliases) |
| `vpn disconnect` | Disconnect and restore the original route (`down`/`off`) |
| `vpn reconnect` | Disconnect, then connect again |
| `vpn rotate` | Reconnect until the IP changes (best effort, `--attempts 3`) |
| `vpn status` | WARP state, mode, registration, trace, current IP, baseline |
| `vpn ip` | Print the current public IP and its org/location |
| `vpn status --json` | Machine-readable status |
| `vpn ip --json` | Machine-readable IP |
| `vpn doctor` | Diagnose install, daemon, mode, DNS/trace, conflicting VPNs |
| `vpn baseline` | Record the current IP as your home IP (`--clear` to forget) |
| `vpn version` | Show CLI and `warp-cli` versions |

Exit codes: `0` success, `1` error, `3` connected but the IP did not change.

### Examples

```bash
vpn connect --timeout 45
vpn connect --allow-same        # succeed even if Cloudflare reuses an IP
vpn rotate --attempts 5
vpn status --json | jq .ip
```

## How it works

1. `warp-cli connect` starts the WARP tunnel (the default MASQUE protocol
   works on networks that block WireGuard/UDP).
2. `https://www.cloudflare.com/cdn-cgi/trace` must return `warp=on`.
3. The CLI compares the IP before and after and records the event in
   `~/.config/vpn-cli/config.json`.
4. If the client is in DNS-only mode, the CLI switches it to full-tunnel
   (`mode warp` / `set-mode warp`) and reconnects.

The config stores only preferences, the baseline IP, and the last 50 connect
events. It never stores credentials or tokens and is written with mode `0600`.

## Limitations

- WARP egress IPs are shared. Some sites may show a CAPTCHA or block them.
- You cannot choose an exit country; Cloudflare uses the nearest PoP.
- Reconnects may reuse the same egress IP. `vpn rotate` is best effort.
- WARP is a privacy tunnel, not an anonymity tool.
- Concurrent VPNs (for example another VPN app) can conflict. `vpn doctor`
  warns you when another VPN is connected.

## Troubleshooting

```bash
vpn doctor
vpn status
```

- **`warp-cli` not found**: run `./install.sh` or open Cloudflare WARP once,
  then `./install.sh --cli-only`.
- **Registration / privacy error**: open Cloudflare WARP, accept the privacy
  policy, then `vpn connect` again.
- **Connected but `warp=off`**: the client is in 1.1.1.1 (DNS-only) mode.
  `vpn connect` tries to fix this automatically; you can also run
  `warp-cli mode warp` (or `warp-cli set-mode warp`).
- **Tunnel does not connect on your network**: some ISPs interfere with
  WireGuard/UDP. Switch to MASQUE if your client supports it:

  ```bash
  warp-cli tunnel protocol set MASQUE
  vpn reconnect
  ```

- **Another VPN connected**: disconnect it first; macOS runs one VPN tunnel
  at a time.

## Uninstall

```bash
rm -f ~/.local/bin/vpn
rm -rf ~/.config/vpn-cli
# Optional: remove Cloudflare WARP itself
sudo /Applications/Cloudflare\ WARP.app/Contents/Resources/uninstall.sh
```

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q vpn_cli
./bin/vpn doctor        # run without installing
```

Layout:

```
bin/vpn              executable shim
vpn_cli/cli.py       commands, output, exit codes
vpn_cli/warpctl.py   warp-cli discovery, parsing, connect/disconnect
vpn_cli/ipinfo.py    Cloudflare trace + IP geolocation (stdlib)
vpn_cli/macos.py     scutil VPN service inspection
vpn_cli/config.py    JSON config and connect history
vpn_cli/ui.py        terminal colors, status labels, aligned rows
tests/               unit tests (unittest, no dependencies)
```
