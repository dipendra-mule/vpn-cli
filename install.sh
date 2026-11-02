#!/usr/bin/env bash
#
# Install vpn-cli and, if needed, the official Cloudflare WARP client.
# Free, no account, no server required.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_URL="https://downloads.cloudflareclient.com/v1/download/macos/ga"
CLI_LINK="$HOME/.local/bin/vpn"
TMP_DIR=""

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --cli-only   Do not install Cloudflare WARP; only link the vpn command.
  --no-open    Do not launch the WARP app after installing.
  -h, --help   Show this help.

The first run needs an administrator password to install the signed
Cloudflare WARP package. Daily `vpn connect` / `vpn disconnect` do not
need sudo.
EOF
}

CLI_ONLY=0
NO_OPEN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cli-only) CLI_ONLY=1 ;;
    --no-open) NO_OPEN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is for macOS." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found." >&2
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PY_VERSION" in
  3.9|3.1[0-9]) ;;
  *) echo "Python 3.9+ is required (found $PY_VERSION)." >&2; exit 1 ;;
esac

warp_cli_path() {
  command -v warp-cli 2>/dev/null \
    || { [ -x /usr/local/bin/warp-cli ] && echo /usr/local/bin/warp-cli; } \
    || { [ -x /opt/homebrew/bin/warp-cli ] && echo /opt/homebrew/bin/warp-cli; } \
    || true
}

if [ "$CLI_ONLY" -eq 0 ] && [ -z "$(warp_cli_path)" ]; then
  echo "==> Downloading Cloudflare WARP (official signed package)"
  TMP_DIR="$(mktemp -d)"
  PKG="$TMP_DIR/Cloudflare_WARP.pkg"
  curl -fL --progress-bar "$PKG_URL" -o "$PKG"

  echo "==> Checking package signature"
  if ! pkgutil --check-signature "$PKG" >/dev/null 2>&1; then
    echo "Package signature check failed; refusing to install." >&2
    echo "Download WARP manually from https://1.1.1.1/ and rerun with --cli-only." >&2
    exit 1
  fi

  echo "==> Installing Cloudflare WARP"
  if [ "$(id -u)" -eq 0 ]; then
    installer -pkg "$PKG" -target /
  elif [ -t 0 ]; then
    sudo installer -pkg "$PKG" -target /
  else
    osascript -e "do shell script \"installer -pkg '$PKG' -target /\" with administrator privileges"
  fi

  if [ -z "$(warp_cli_path)" ]; then
    for candidate in /usr/local/bin/warp-cli /opt/homebrew/bin/warp-cli; do
      if [ -x "$candidate" ]; then
        WARP_CLI="$candidate"
        break
      fi
    done
    if [ -z "${WARP_CLI:-}" ]; then
      echo "WARP installed, but warp-cli was not found." >&2
      echo "Open Cloudflare WARP once, then rerun: ./install.sh --cli-only" >&2
      exit 1
    fi
  fi
fi

echo "==> Linking the vpn command"
mkdir -p "$HOME/.local/bin"
chmod +x "$ROOT/bin/vpn"
ln -sfn "$ROOT/bin/vpn" "$CLI_LINK"

if [ "$NO_OPEN" -eq 0 ] && [ -d "/Applications/Cloudflare WARP.app" ]; then
  open -a "Cloudflare WARP" >/dev/null 2>&1 || true
fi

PATH_OK=0
case ":$PATH:" in
  *":$HOME/.local/bin:"*) PATH_OK=1 ;;
esac

echo
echo "Installed: $CLI_LINK"
if [ "$PATH_OK" -eq 0 ]; then
  echo "Add this to your shell profile, then restart the terminal:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
echo
echo "Next steps:"
echo "  1. If this is the first WARP install, accept the privacy policy in the app."
echo "  2. Run: vpn doctor"
echo "  3. Run: vpn connect"
echo "  4. Verify: vpn status"
echo
echo "No account, no subscription, no server: free Cloudflare WARP."
