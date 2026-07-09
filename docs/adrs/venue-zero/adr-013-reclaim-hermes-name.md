# ADR-013: Reclaim Hermes Name

**Status:** Draft
**Date:** 2026-07-05
**Author:** Songbird (CTO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead), Lexicon (COO)

---

## Context

The name "Hermes" is overloaded across our stack:

1. **Hermes Agent** — the upstream agent framework by Nous Research (`hermes-agent`). This is the binary, the CLI, the gateway, the venv at `~/.hermes/hermes-agent/`.
2. **Hermes Home** — the config/data directory at `~/.hermes/`. Contains profiles, skills, plugins, memories, cron jobs.
3. **hermes-prime** — one of our 18 Maestro agents. Named after the framework it runs on, creating confusion between "the Hermes agent" (the software) and "Hermes" (the agent in our mesh).

This overload causes real problems:
- "Restart Hermes" is ambiguous — restart the gateway? The transport? hermes-prime?
- "Hermes config" could mean `~/.hermes/config.yaml` or `~/.maestro/configs/hermes-prime.json`
- New contributors can't tell whether a reference is to the framework or the agent
- Logs, docs, and conversations constantly need disambiguation

## Decision

### Rename hermes-prime to a distinct name

The agent currently named "hermes-prime" will be renamed to break the ambiguity with the Hermes framework. The new name must:

1. Not collide with any existing agent name
2. Not collide with any framework term (hermes, gateway, transport, bridge, etc.)
3. Be distinct and memorable
4. Fit the naming convention of the mesh (mythological, literary, or thematic)

**Proposed names (for CEO approval):**

| Name | Origin | Notes |
|------|--------|-------|
| **atlas** | Greek Titan who holds up the sky | Conveys load-bearing, infrastructure role |
| **aegis** | Zeus's shield | Protection, defense, oversight |
| **chimera** | Multi-headed beast | Composite nature — runs multiple services |
| **oracle** | Delphic Oracle | Knowledge, answers, guidance |

**Recommendation: atlas.** hermes-prime is the infrastructure backbone — it runs the most services, has the most peers, and is the first agent spun up. Atlas holding up the sky is the right metaphor.

### What changes

1. **Agent name:** `hermes-prime` → `atlas` (or CEO's choice)
2. **Config file:** `~/.maestro/configs/hermes-prime.json` → `~/.maestro/configs/atlas.json`
3. **Profile directory:** `~/.hermes/profiles/hermes-prime/` → `~/.hermes/profiles/atlas/`
4. **Systemd unit:** `maestro-transport@hermes-prime` → `maestro-transport@atlas`
5. **Gateway unit:** `hermes-gateway-hermes-prime` → `hermes-gateway-atlas`
6. **Registry entry:** `registry.json` updated
7. **Port map:** `port_map.json` updated (ports stay the same — 3844/8641)
8. **knownPeers:** Every officer's config updated to reference `atlas` instead of `hermes-prime`
9. **contacts.json:** Updated
10. **agent_emojis.json:** Updated (if we ever use it)

### What does NOT change

- Ports (3844 transport, 8641 gateway)
- DM token
- Public key
- Role (officer)
- Known peers list (just the name reference updates)

### Migration procedure

1. Stop hermes-prime transport and gateway
2. Rename config file, profile directory, systemd units
3. Update all references in configs, registry, port_map, contacts
4. Update knownPeers in all 4 other officer configs
5. Start atlas transport and gateway
6. Verify mesh health — all 18 agents should still see atlas as a peer
7. Smoke test: send a message through atlas, verify delivery

### Rollback

If the rename breaks the mesh:
1. Stop atlas
2. Revert all name changes
3. Restart hermes-prime
4. Mesh self-heals via registry re-registration

## Consequences

**Positive:**
- Zero ambiguity between the Hermes framework and the agent
- "Restart Hermes" unambiguously means the gateway/CLI
- "hermes-prime" no longer appears in logs, docs, or conversations
- New contributors don't need to learn the disambiguation

**Negative:**
- One-time migration cost (stop, rename, update refs, restart)
- All 5 officers need config updates (knownPeers references)
- Brief mesh disruption during migration (~2 minutes)

**Risks:**
- Known peers reference stale name → mitigated by updating all 5 officer configs
- Registry has stale entry → mitigated by re-registration on startup
- Someone references "hermes-prime" in a script or cron job → mitigated by grep audit
