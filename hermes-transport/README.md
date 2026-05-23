# Maestro Transport for Hermes-Agent

Gives a Hermes-Agent instance a native Maestro identity — making it a full protocol peer rather than an API target.

## Requirements

- **Node.js 18+** (built-in `fetch` + `http` — no npm install needed)
- Hermes gateway running with API server enabled

## Setup (on the VM)

1. Copy this directory to the VM:
   ```bash
   scp -r hermes-transport/ andjesse@<vm-ip>:~/maestro-transport/
   ```
   Or just clone the repo on the VM and `cd hermes-transport/`.

2. Edit `maestro_transport.json` with your config:
   ```json
   {
     "agentId": "hermes-lex",
     "port": 3844,
     "hermesApiUrl": "http://127.0.0.1:8642",
     "hermesApiKey": "maestro-local-dev",
     "conversation": "maestro",
     "registryPath": "/home/andjesse/.maestro/registry.json",
     "version": "3.2",
     "knownPeers": {
       "songbird": "http://10.0.2.2:3842/message"
     }
   }
   ```

3. Run it:
   ```bash
   node maestro-transport.mjs
   # or with explicit config:
   node maestro-transport.mjs --config maestro_transport.json
   ```

4. On the Windows host, add a VirtualBox port forward:
   - Host: `127.0.0.1:3845` → Guest: `10.0.2.15:3844`
   - (Use 3845 on Windows since 3844 may be used by other services)

5. Ensure `hermes-lex` is registered in the Windows-side registry so OpenClaw agents can reach it.

## How it works

```
[OpenClaw Songbird / Lexicon]
    → POST http://127.0.0.1:3845/message (Windows port forward)
    → VirtualBox NAT → 10.0.2.15:3844
    → maestro-transport.mjs _handleMessage()
    → Hermes API POST /v1/chat/completions
    → reply routed back to sender via registry lookup
```

The transport maintains the shared registry file so it can look up sender endpoints for reply routing.

## Persistence (systemd)

```ini
# /etc/systemd/system/maestro-transport.service
[Unit]
Description=Maestro Transport for Hermes-Agent
After=network.target

[Service]
Type=simple
User=andjesse
WorkingDirectory=/home/andjesse/maestro-transport
ExecStart=/usr/bin/node maestro-transport.mjs
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now maestro-transport
sudo journalctl -u maestro-transport -f
```

Or simple crontab:
```bash
@reboot node /home/andjesse/maestro-transport/maestro-transport.mjs >> /tmp/maestro-transport.log 2>&1 &
```

## Python version

`maestro_transport.py` is kept for reference but is no longer the primary transport.
It required `aiohttp` (unavailable by default on Debian without `--break-system-packages`).
The Node version has zero external dependencies.
