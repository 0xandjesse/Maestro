# Maestro Protocol — Hermes-Agent Plugin

Gives Hermes agents Maestro presence via a Node.js sidecar process. Discover peers, create Venues, share Blackboards, and coordinate with other agents cross-platform.

## Install

Copy to your Hermes plugins directory:

```bash
cp maestro_plugin.py ~/.hermes/plugins/
cp maestro_sidecar.mjs ~/.hermes/plugins/
```

Or add to `cli-config.yaml`:

```yaml
plugins:
  - path: /path/to/maestro/plugins/hermes-agent/maestro_plugin.py
```

## Config (`cli-config.yaml`)

```yaml
maestro:
  agent_id: "hermes"
  webhook_port: 3843        # Different from Songbird's 3842
  discovery: "mdns"
  blackboard_path: ""       # optional: path to SQLite file
  registry_path: ""         # required if discovery=file
```

Enable the toolset:

```yaml
tools:
  enabled:
    - maestro
```

## Tools

| Tool | Description |
|------|-------------|
| `maestro_venue_create` | Create a new Venue (flat or hierarchical) |
| `maestro_venue_join` | Join an existing Venue by ID |
| `maestro_send` | Send direct, broadcast, report, or assign messages |
| `maestro_blackboard_set` | Write to a Venue's shared Blackboard |
| `maestro_blackboard_get` | Read from a Venue's shared Blackboard |
| `maestro_venue_list` | List Venues this agent belongs to |
| `maestro_peers` | List discovered Maestro agents on the network |

## Architecture

```
Hermes-Agent (Python)
       ↓ HTTP REST (localhost)
maestro_sidecar.mjs (Node.js)
       ↓ Maestro SDK
  @maestro-protocol/core
       ↓ HTTP / mDNS
  Other Maestro agents
```

The sidecar starts automatically when the plugin loads and stops when Hermes shuts down.

## Cross-platform testing

See the OpenClaw plugin README for the full cross-platform test flow.
