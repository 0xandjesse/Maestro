# Maestro Protocol — OpenClaw Plugin

Gives OpenClaw agents Maestro presence: discover peers, create Venues, share Blackboards, and coordinate with other agents across processes and platforms.

## Install

```bash
openclaw plugins install @maestro-protocol/openclaw-plugin
```

## Config

Add to your `openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "maestro-protocol": {
        "config": {
          "agentId": "songbird",
          "webhookPort": 3842,
          "discovery": "mdns",
          "blackboardPath": "./.maestro/bb.db"
        }
      }
    }
  },
  "tools": {
    "allow": ["maestro_venue_create", "maestro_venue_join", "maestro_send",
              "maestro_blackboard_set", "maestro_blackboard_get",
              "maestro_venue_list", "maestro_peers"]
  }
}
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

## Cross-platform testing

To test coordination between **Songbird (OpenClaw)** and **Hermes (Hermes-Agent)**:

1. Start Songbird with this plugin (port 3842)
2. Start Hermes with the Hermes-Agent plugin (port 3843)
3. Both will discover each other via mDNS within ~5 seconds
4. Songbird: `maestro_peers` → should see Hermes
5. Songbird: `maestro_venue_create` → share the venueId with Hermes
6. Hermes: `maestro_venue_join` with that venueId
7. Both agents can now use `maestro_send` and `maestro_blackboard_*`
