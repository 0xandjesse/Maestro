#!/usr/bin/env python3
"""
Update songbird maestro config to point at the correct gateway API port,
then restart the maestro-songbird transport.

Called as an ExecStartPost on hermes-gateway-songbird.service, or manually.
Reads the actual bound port from the songbird config.yaml gateway.api_server.port.
"""
import json
import pathlib
import subprocess
import sys
import time

SONGBIRD_CONFIG = pathlib.Path("/home/andjesse/.hermes/profiles/songbird/config.yaml")
MAESTRO_CONFIG  = pathlib.Path("/home/andjesse/.maestro/configs/songbird.json")


def get_configured_port() -> int:
    """Read gateway.api_server.port from songbird config.yaml."""
    try:
        import yaml
        data = yaml.safe_load(SONGBIRD_CONFIG.read_text())
        return int(data["gateway"]["api_server"]["port"])
    except Exception:
        # Fallback: parse manually
        for line in SONGBIRD_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("port:") and "api_server" in SONGBIRD_CONFIG.read_text():
                try:
                    port = int(line.split(":", 1)[1].strip())
                    if 8000 < port < 9000:
                        return port
                except Exception:
                    continue
    return 8649  # last-known good


def update_maestro_config(port: int):
    config = json.loads(MAESTRO_CONFIG.read_text())
    old = config.get("hermesApiUrl", "")
    config["hermesApiUrl"] = f"http://127.0.0.1:{port}"
    MAESTRO_CONFIG.write_text(json.dumps(config, indent=4))
    print(f"Updated hermesApiUrl: {old} → http://127.0.0.1:{port}")


def restart_transport():
    result = subprocess.run(
        ["systemctl", "--user", "restart", "maestro-songbird"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"restart failed: {result.stderr}", file=sys.stderr)
        return False
    time.sleep(3)
    result2 = subprocess.run(
        ["systemctl", "--user", "is-active", "maestro-songbird"],
        capture_output=True, text=True
    )
    status = result2.stdout.strip()
    print(f"maestro-songbird status: {status}")
    return status == "active"


if __name__ == "__main__":
    port = get_configured_port()
    print(f"Gateway configured port: {port}")
    update_maestro_config(port)
    ok = restart_transport()
    sys.exit(0 if ok else 1)
