# Maestro Transport

Total package: `git clone` this repo, then run `./install.sh`. Maestro superpowers your Hermes agents.

## What This Is

Maestro is the Hermes inter-agent transport layer: a mesh network that lets your agents talk to each other, coordinate via checklists, log everything, and surface cross-team context to you via Telegram.

Prerequisite: [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed.

## Quick Start

```bash
git clone https://github.com/0xandjesse/Maestro
cd Maestro
./install.sh
```

## What You Get

### Runtime

- **Maestro Gateway Bridge** — listens on `127.0.0.1:8644`, forwards between agents and gateway
- **Maestro Transports** — per-agent connectors (Proteus, Songbird, Hermes, Lexicon, Mnemosyne, Stormtrooper, Rosetta, Penny Lane, Lulu)
- **Blackboard server** — shared state between agents that survives restarts

### Tools

- `send_message_tool.py` — Maestro-aware messaging with sender resolution
- `maestro_memory.py` — agent memory that persists across restarts
- `bb_tool.py` — blackboard read/write for inter-agent coordination
- `checklist_tool.py` — Maestro-tracked task lists with progress reporting

### Commands

Once installed, your agents gain these Telegram commands:

| Command | What it does |
|---|---|
| `/maestrolong` | Full rich Maestro notifications for this agent |
| `/maestroshort` | Condensed notifications (timestamp + sender + 3 words) |
| `/maestrooff` | Suppress Maestro notifications completely |

### Directory Layout

```
maestro-transport/
├── maestro/                    # Maestro transport packages (installed into Python path)
│   ├── __init__.py
│   ├── __main__.py
│   └── secrets.py              # Registry + config management
├── tools/                      # Hermes tool overlays (copied into ~/.hermes/hermes-agent/tools/)
│   ├── send_message_tool.py
│   ├── maestro_memory.py
│   ├── bb_tool.py
│   └── checklist_tool.py
├── maestro_transport.py        # Base transport — all agents inherit from this
├── maestro_transport_clean.py  # Minimal reference impl
├── maestro_gateway_bridge.py   # The bridge (start this first)
├── maestro_status.py           # Health / status checker
├── maestro_team_status.py      # Team summary display
├── atomic_bb_io.py             # Race-safe blackboard I/O
├── hermes_memory.py            # Hermes integration helpers
├── log_writer.py               # Structured logging
├── agent_logger.py             # Per-agent log writers
├── eod_report.py               # End-of-day team report
├── patches/                    # Hermes overlay patches (applied by install.sh)
│   ├── gateway_run.py.patch          # Gateway TG commands + Maestro visibility
│   ├── platforms_telegram.py.patch   # Telegram sender fix
│   ├── agent_audit_log.py.patch      # Audit log integration
│   ├── hermes_cli_commands.py.patch  # CLI command registration
│   ├── tools_memory_tool.py.patch    # Memory tool enhancement
│   └── toolsets.py.patch             # Maestro tool registration
├── tests/                      # Move with the code under test
├── specs/                      # Feature specs (text)
├── grants/                     # Grant proposals
├── scripts/                    # Operational scripts
├── install.sh                  # One-line installer (copies tools + applies patches)
└── README.md                   # You are here
```

## Developer Notes

### One Repo

Everything is in this repo. Hermes stays upstream. We apply **overlay patches**, not forks.

### Keeping Patches Alive

When Hermes upstream changes, regenerate patches:

```bash
cd ~/.hermes/hermes-agent
git diff origin/main -- gateway/run.py > ~/maestro-transport/patches/gateway_run.py.patch
# ... etc for each patch
```

### Adding a New Agent Transport

Create a directory in `maestro_transports/<name>/` containing `maestro_transport.py` that subclasses `MaestroTransport`. The installer will create a systemd service or cron entry to start it.

## Architecture

```
Telegram <--->  Hermes Gateway  <--->  Maestro Bridge (127.0.0.1:8644)
                              |
      +-----------------------+-----------------------+
      |                       |                       |
   Proteus               Songbird                  Hermes
      |                       |                       |
   Maestro Transport      Maestro Transport      Maestro Transport
      |                       |                       |
   Backlog                 CTO                     Operations
```

Each agent runs a transport that speaks to the bridge. The bridge speaks to the gateway. Messages surface to you via Telegram based on your `/maestro*` visibility settings.

## License

Proprietary — NGI0 Zero Commons framework.
