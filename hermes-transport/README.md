# Maestro Transport for Hermes-Agent

Gives a Hermes-Agent instance a native Maestro identity — making it a full protocol peer rather than an API target.

## Requirements

- Python 3.8+
- `aiohttp` (already installed in Hermes-Agent's venv)
- Hermes gateway running with API server enabled

## Setup (on the VM)

1. Copy this directory to the VM:
   ```bash
   scp -r hermes-transport/ andjesse@<vm-ip>:~/maestro-transport/
   ```
   Or just clone the repo on the VM.

2. Edit `maestro_transport.json` with your config:
   ```json
   {
     "agentId": "hermes-lex",
     "port": 3844,
     "hermesApiUrl": "http://127.0.0.1:8642",
     "hermesApiKey": "maestro-local-dev",
     "conversation": "maestro",
     "registryPath": "/home/andjesse/.maestro/registry.json"
   }
   ```

3. Run using Hermes-Agent's venv (has aiohttp already):
   ```bash
   /home/andjesse/.hermes/hermes-agent/venv/bin/python maestro_transport.py
   ```

4. On the Windows host, add a VirtualBox port forward:
   - Host: `127.0.0.1:3845` → Guest: `10.0.2.15:3844`
   - (Use 3845 on Windows since 3844 is used by the Windows-side hermes proxy)

5. Register `hermes-lex` in the Windows-side registry so OpenClaw agents can reach it:
   ```json
   // Add to .maestro/registry.json on Windows:
   {
     "hermes-lex": {
       "agentId": "hermes-lex",
       "webhookEndpoint": "http://127.0.0.1:3845/message"
     }
   }
   ```

## How it works

```
[OpenClaw Lex / Songbird]
    → POST http://127.0.0.1:3845/message (Windows port forward)
    → VirtualBox NAT → 10.0.2.15:3844
    → maestro_transport.py handle_message()
    → Hermes API POST /v1/runs
    → SSE stream run.completed
    → POST reply back to sender's /message endpoint
```

The transport also maintains a local registry file so it can look up sender endpoints for reply routing.

## Persistence

Add to crontab or systemd:
```bash
@reboot /home/andjesse/.hermes/hermes-agent/venv/bin/python /home/andjesse/maestro-transport/maestro_transport.py >> /tmp/maestro-transport.log 2>&1 &
```
