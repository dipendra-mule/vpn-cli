"""Small JSON config store for vpn-cli."""

import copy
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "connect_timeout": 30,
    "command_timeout": 20,
    "baseline_ip": None,
    "warp_ip": None,
    "history": [],
}


def config_dir() -> Path:
    override = os.environ.get("VPN_CLI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "vpn-cli"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    path = config_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update(data)
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        pass
    if not isinstance(cfg.get("history"), list):
        cfg["history"] = []
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def record_event(
    cfg: Dict[str, Any],
    before_ip: Optional[str],
    after_ip: Optional[str],
    trace_info: Dict[str, str],
) -> None:
    history = cfg.setdefault("history", [])
    history.append(
        {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "before_ip": before_ip,
            "after_ip": after_ip,
            "warp": (trace_info or {}).get("warp"),
            "loc": (trace_info or {}).get("loc"),
            "colo": (trace_info or {}).get("colo"),
        }
    )
    del history[:-50]
    if after_ip:
        cfg["warp_ip"] = after_ip
    save(cfg)
