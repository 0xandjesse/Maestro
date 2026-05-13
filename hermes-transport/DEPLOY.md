# Maestro Transport — Hermes-Native Deployment Guide

**Target:** Hermes-Agent VM (Ubuntu, VirtualBox NAT)  
**Author:** Songbird (CTO)  
**Date:** May 8, 2026  

---

## Architecture

Each Hermes-Agent profile gets its own Maestro transport sidecar — a Python process that:
- Listens on a dedicated port for inbound Maestro messages
- Delivers them to the H-A gateway via `/v1/chat/completions`
- Routes replies back to senders via HTTP

No OpenClaw involved. No dependency on Windows-side processes. The transport is a self-contained systemd service that starts with the VM.

```
[Sender Agent]
     │  POST /message
     ▼
[maestro-transport.py]   ← systemd service (per profile)
     │  POST /v1/chat/completions
     ▼
[Hermes-Agent Gateway]
     │  streams response
     ▼
[maestro-transport.py]   ← routes reply back to sender
     │  POST /message
     ▼
[Sender Agent]
```

Songbird (OpenClaw) is just another peer on the mesh — it sends to VM agents via VirtualBox port forwards. VM agents send to Songbird via `http://10.0.2.2:<port>/message` (the Windows host gateway from the VM's perspective).

---

## Port Map

| Agent | Transport Port | H-A API Port | Profile Name |
|---|---|---|---|
| lexicon | 3843 | 8644 | lexicon |
| hermes | 3844 | 8642 | hermes |
| mnemosyne | 3845 | 8642 | mnemosyne |
| proteus | 3846 | 8642 | proteus |

**Songbird (Windows/OpenClaw):** port 3842 — reachable from VM at `http://10.0.2.2:3842/message`

---

## Prerequisites

```bash
pip install aiohttp
```

Verify aiohttp is installed:
```bash
python3 -c "import aiohttp; print(aiohttp.__version__)"
```

---

## Config Files

Create one config per agent at `/home/andjesse/.maestro/configs/<agentId>.json`.

### /home/andjesse/.maestro/configs/lexicon.json
```json
{
    "agentId": "lexicon",
    "port": 3843,
    "hermesApiUrl": "http://127.0.0.1:8644",
    "hermesApiKey": "maestro-local-dev",
    "conversation": "lexicon",
    "registryPath": "/home/andjesse/.maestro/registry.json",
    "version": "3.2",
    "knownPeers": {
        "songbird": "http://10.0.2.2:3842/message"
    }
}
```

### /home/andjesse/.maestro/configs/hermes.json
```json
{
    "agentId": "hermes",
    "port": 3844,
    "hermesApiUrl": "http://127.0.0.1:8642",
    "hermesApiKey": "maestro-local-dev",
    "conversation": "hermes",
    "registryPath": "/home/andjesse/.maestro/registry.json",
    "version": "3.2",
    "knownPeers": {
        "songbird": "http://10.0.2.2:3842/message"
    }
}
```

### /home/andjesse/.maestro/configs/mnemosyne.json
```json
{
    "agentId": "mnemosyne",
    "port": 3845,
    "hermesApiUrl": "http://127.0.0.1:8642",
    "hermesApiKey": "maestro-local-dev",
    "conversation": "mnemosyne",
    "registryPath": "/home/andjesse/.maestro/registry.json",
    "version": "3.2",
    "knownPeers": {
        "songbird": "http://10.0.2.2:3842/message"
    }
}
```

### /home/andjesse/.maestro/configs/proteus.json
```json
{
    "agentId": "proteus",
    "port": 3846,
    "hermesApiUrl": "http://127.0.0.1:8642",
    "hermesApiKey": "maestro-local-dev",
    "conversation": "proteus",
    "registryPath": "/home/andjesse/.maestro/registry.json",
    "version": "3.2",
    "knownPeers": {
        "songbird": "http://10.0.2.2:3842/message"
    }
}
```

---

## Deploy Script

Run this on the VM to create all config files and the transport script in one shot:

```bash
#!/bin/bash
set -e

MAESTRO_DIR="/home/andjesse/.maestro"
SCRIPT_SRC="/path/to/maestro-protocol/hermes-transport/maestro_transport.py"
SCRIPT_DST="$MAESTRO_DIR/maestro_transport.py"

mkdir -p "$MAESTRO_DIR/configs"

# Copy transport script
cp "$SCRIPT_SRC" "$SCRIPT_DST"

# Create config files
for agent in lexicon hermes mnemosyne proteus; do
    cat > "$MAESTRO_DIR/configs/$agent.json" << CONF
$(cat /path/to/maestro-protocol/hermes-transport/DEPLOY.md | grep -A20 "### /home/andjesse/.maestro/configs/$agent.json" | tail -n+2 | sed '/^###/q' | head -n-1)
CONF
done

echo "Done. Run: python3 $SCRIPT_DST --config $MAESTRO_DIR/configs/lexicon.json"
```

*(Or just copy the JSON blocks above manually — easier and less error-prone.)*

---

## Systemd Service Units

Create one service file per agent. Template — replace `AGENT`, `PORT`, and `API_PORT` for each:

### /home/andjesse/.config/systemd/user/maestro-lexicon.service
```ini
[Unit]
Description=Maestro Transport — lexicon
After=network.target hermes-gateway-lexicon.service
Requires=hermes-gateway-lexicon.service

[Service]
Type=simple
WorkingDirectory=/home/andjesse/.maestro
ExecStart=/usr/bin/python3 /home/andjesse/.maestro/maestro_transport.py --config /home/andjesse/.maestro/configs/lexicon.json
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=maestro-lexicon

[Install]
WantedBy=default.target
```

Repeat for hermes, mnemosyne, proteus (changing service name, config path, and `After`/`Requires` dependency).

### Install and enable all four:
```bash
systemctl --user daemon-reload
systemctl --user enable maestro-lexicon maestro-hermes maestro-mnemosyne maestro-proteus
systemctl --user start maestro-lexicon maestro-hermes maestro-mnemosyne maestro-proteus
```

### Verify:
```bash
systemctl --user status maestro-lexicon
curl http://localhost:3843/health
# Expected: {"ok": true, "agentId": "lexicon", "platform": "hermes-agent", ...}
```

---

## VirtualBox Port Forwarding

The VM needs ports 3843-3846 forwarded so Songbird (Windows) can reach VM agents directly.

**Check current forwards:**
```bash
VBoxManage showvminfo "<VM Name>" | grep -i "name.*guest.*3843"
```

**Add forwards (run on Windows host, VM can be running):**
```powershell
VBoxManage modifyvm "<VM Name>" --natpf1 "maestro-lexicon,tcp,,3843,,3843"
VBoxManage modifyvm "<VM Name>" --natpf1 "maestro-hermes,tcp,,3844,,3844"
VBoxManage modifyvm "<VM Name>" --natpf1 "maestro-mnemosyne,tcp,,3845,,3845"
VBoxManage modifyvm "<VM Name>" --natpf1 "maestro-proteus,tcp,,3846,,3846"
```

*(Port 3843 may already be forwarded — check first.)*

---

## OpenClaw Side — After VM Transport Is Running

Once the VM transports are live, **remove the hermesAgents from the OpenClaw Maestro plugin config** — they no longer need to be proxied through OpenClaw. OpenClaw just runs as a peer (`songbird` on port 3842).

The OpenClaw plugin config should become minimal:
```json
{
  "agents": [
    {
      "agentId": "songbird",
      "webhookPort": 3842,
      "discovery": "file",
      "registryPath": "C:\\Users\\there\\.maestro\\registry.json"
    }
  ]
}
```

And Songbird's registry seeds the VM peers statically:
```json
[
  { "agentId": "lexicon",    "webhookEndpoint": "http://127.0.0.1:3843/message" },
  { "agentId": "hermes",     "webhookEndpoint": "http://127.0.0.1:3844/message" },
  { "agentId": "mnemosyne",  "webhookEndpoint": "http://127.0.0.1:3845/message" },
  { "agentId": "proteus",    "webhookEndpoint": "http://127.0.0.1:3846/message" }
]
```

---

## Verification — End-to-End Test

Once everything is running:

1. From VM: `curl http://localhost:3843/health` — should return Lex's health
2. From Windows: `curl http://127.0.0.1:3843/health` — same (via port forward)
3. Send a test Maestro message from Songbird to Lexicon — should arrive in Lex's H-A session
4. Check Lex's reply routes back to Songbird

---

## Conversation Name Convention

The `"conversation"` field in each config maps to the H-A session/conversation name the transport injects into. Each agent should have a named conversation set up in H-A (e.g., a conversation called "lexicon" in the lexicon profile) so Maestro messages land in a consistent context.

If no named conversation exists, H-A will create a new session per message — functional but loses continuity. Better to have a dedicated Maestro conversation per profile.

---

## Troubleshooting

**Transport starts but Hermes doesn't respond:**
- Check `systemctl --user status hermes-gateway-lexicon`
- Verify H-A API key matches what's in the config (`maestro-local-dev`)
- Check H-A API is actually on the right port: `curl http://127.0.0.1:8644/health`

**Reply not routing back to Songbird:**
- Check registry: `cat /home/andjesse/.maestro/registry.json` — is songbird in there?
- Check Windows-side port 3842 is reachable from VM: `curl http://10.0.2.2:3842/health`
- If 10.0.2.2 doesn't work, find the actual Windows host IP: `ip route show default`

**Port already in use:**
- Check what's using it: `ss -tulpn | grep 384`
- Kill the old process or change the port in the config

---

*This is the canonical deployment guide for Hermes-native Maestro transport. OpenClaw is a peer, not a dependency.*
