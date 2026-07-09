# ADR-005: Full Agent Maintenance Audit — Get All Agents Online

**Status:** Draft
**Date:** 2026-07-04
**Author:** Lexicon (COO)
**Deciders:** Songbird (CTO), Proteus (Tech Lead)
**Type:** Maintenance Request

---

## Context

The Local Org mesh has 13 active agents (plus ghosts). A full infrastructure audit on 2026-07-04 revealed systemic gaps across the fleet: missing personality.md files, missing publicKeys in the registry, downed transports, port conflicts, and a dead agent's transport still running. These gaps prevent DM token validation, transport routing, and agent session creation.

This ADR is a maintenance request. It documents every gap and the fix for each. No architectural decisions — purely mechanical fixes.

---

## Fleet Inventory

### Active Agents (13)

| Agent | Role | Reports To |
|-------|------|------------|
| lexicon | COO | Jesse |
| songbird | CTO | Lexicon |
| hermes-prime | CMO | Lexicon |
| proteus | Tech Lead | Songbird |
| mnemosyne | CD | Hermes |
| lulu | Media/E&M | Mnemosyne |
| penny-lane | Copy/Research | Mnemosyne |
| stormtrooper | Engineer | Songbird |
| thoth | Writer | Mnemosyne |
| zulu | Engineer | Proteus |
| keystone | Infrastructure | Songbird |
| uatu | Watcher/Observer | Songbird |
| helper | Jesse's Assistant | Songbird |

### Ghosts (Profiles exist, not active — do not touch)

cactus-jack, cee-lo, chatterbox, lex, log, memex, mondo-gecko

### Dead (Do not resurrect)

rosetta — purged 2026-06-23. Transport on port 3849 is a stale process and must be killed.

---

## Gap Matrix

### CRITICAL — Agent Cannot Function

| # | Agent | Gap | Fix |
|---|-------|-----|-----|
| 1 | **lexicon** | personality.md MISSING | `cp ~/.hermes/profiles/lexicon/SOUL.md ~/.hermes/profiles/lexicon/personality.md` |
| 2 | **lexicon** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to lexicon's registry entry |
| 3 | **songbird** | personality.md MISSING | `cp ~/.hermes/profiles/songbird/SOUL.md ~/.hermes/profiles/songbird/personality.md` |
| 4 | **songbird** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to songbird's registry entry |
| 5 | **hermes-prime** | Transport DOWN (3844) | `systemctl --user enable --now maestro-transport@hermes-prime` |
| 6 | **hermes-prime** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to hermes-prime's registry entry |
| 7 | **proteus** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to proteus's registry entry |
| 8 | **stormtrooper** | Transport DOWN (3847) | `systemctl --user enable --now maestro-transport@stormtrooper` |
| 9 | **stormtrooper** | personality.md MISSING | `cp ~/.hermes/profiles/stormtrooper/SOUL.md ~/.hermes/profiles/stormtrooper/personality.md` |
| 10 | **stormtrooper** | DM token MISSING | Issue DM token with targets: lexicon, songbird, proteus |
| 11 | **stormtrooper** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to stormtrooper's registry entry |
| 12 | **helper** | Gateway DOWN (8659) | Start gateway: `hermes gateway run --profile helper` |
| 13 | **helper** | Transport DOWN (3860) | `systemctl --user enable --now maestro-transport@helper` |
| 14 | **helper** | DM token MISSING | Issue DM token with targets: lexicon, songbird |
| 15 | **helper** | publicKey MISSING in registry | Add `"publicKey": "<key>"` to helper's registry entry |
| 16 | **uatu** | Gateway DOWN (8659) | **BLOCKED** — port 8659 conflicts with helper. Reassign uatu to a free gateway port. |
| 17 | **uatu** | Transport DOWN (3860) | **BLOCKED** — port 3860 conflicts with helper. Reassign uatu to a free transport port. |

### PORT CONFLICT

| # | Conflict | Detail |
|---|----------|--------|
| 18 | **helper ↔ uatu** | Both claim gateway 8659 and transport 3860 in `port_map.json`. Only one agent can use these ports. uatu's actual running transport was on 3854 (registry port), not 3860 (port_map port). The port_map is stale for uatu. |

**Resolution for #18:** uatu's registry entry says port 3854. uatu's config (`~/.maestro/configs/uatu.json`) must be checked. If the config also says 3854, then port_map.json is wrong and must be corrected. If the config says 3860, it must be changed to a free port. Either way, helper gets 3860/8659 (it was assigned these ports by Songbird on spin-up). uatu gets new ports.

### STALE PROCESS

| # | Issue | Fix |
|---|-------|-----|
| 19 | **rosetta** transport on 3849 still running | `systemctl --user stop maestro-transport@rosetta; systemctl --user disable maestro-transport@rosetta`. Kill stale PID 403031 if systemd doesn't catch it. |

### REGISTRY FORMAT — publicKey Standardization

The existing publicKeys in the registry use key `4a23b4879e54d682e3bab36c9493ccdb881657587d1a804bc3ca6595aaba6363` (mnemosyne, lulu, penny-lane, thoth, zulu, keystone, uatu). This key was generated during the DM token rollout. The same key should be used for all agents that need publicKeys added (lexicon, songbird, hermes-prime, proteus, stormtrooper, helper).

**Fix:** Add `"publicKey": "4a23b4879e54d682e3bab36c9493ccdb881657587d1a804bc3ca6595aaba6363"` to the registry entries for: lexicon, songbird, hermes-prime, proteus, stormtrooper, helper.

---

## Fix Sequence (MANDATORY ORDER)

Fixes must be applied in this order. Dependencies exist.

### Phase 1: Registry publicKeys (no restarts needed)

```
1. Add publicKey to: lexicon, songbird, hermes-prime, proteus, stormtrooper, helper
   File: ~/.maestro/registry.json
   Key: 4a23b4879e54d682e3bab36c9493ccdb881657587d1a804bc3ca6595aaba6363
```

### Phase 2: personality.md files (no restarts needed)

```
2. cp ~/.hermes/profiles/lexicon/SOUL.md ~/.hermes/profiles/lexicon/personality.md
3. cp ~/.hermes/profiles/songbird/SOUL.md ~/.hermes/profiles/songbird/personality.md
4. cp ~/.hermes/profiles/stormtrooper/SOUL.md ~/.hermes/profiles/stormtrooper/personality.md
```

### Phase 3: Kill stale rosetta transport

```
5. systemctl --user stop maestro-transport@rosetta
6. systemctl --user disable maestro-transport@rosetta
7. Verify port 3849 is free: ss -tlnp | grep 3849
```

### Phase 4: Resolve uatu/helper port conflict

```
8. Determine uatu's actual assigned ports from ~/.maestro/configs/uatu.json
9. If uatu config says 3854/8654: update port_map.json to match (uatu: 3854/8654, helper: 3860/8659)
10. If uatu config says 3860/8659: reassign uatu to free ports, update config + port_map + registry
11. Verify no other agent claims 3860/8659
```

### Phase 5: Start downed transports

```
12. systemctl --user enable --now maestro-transport@hermes-prime
13. systemctl --user enable --now maestro-transport@stormtrooper
14. systemctl --user enable --now maestro-transport@helper
15. systemctl --user enable --now maestro-transport@uatu
```

### Phase 6: Start downed gateways

```
16. hermes gateway run --profile helper &
17. hermes gateway run --profile uatu &
```

### Phase 7: Issue missing DM tokens

```
18. Issue DM token for stormtrooper (targets: lexicon, songbird, proteus)
19. Issue DM token for helper (targets: lexicon, songbird)
```

### Phase 8: Verification

```
20. All 13 transports return health: curl http://127.0.0.1:<port>/health
21. All 13 gateways return health: curl http://localhost:<port>/health
22. All 13 agents have personality.md
23. All 13 agents have publicKey in registry
24. All 13 agents have DM tokens
25. Connectivity test: ping each agent via send_message
```

---

## Ownership

| Phase | Owner | Notes |
|-------|-------|-------|
| Registry edits | Proteus | Mechanical JSON edits. Songbird reviews. |
| personality.md copies | Proteus | File copies. Verify SOUL.md exists first. |
| Rosetta cleanup | Proteus | systemctl + kill if needed. |
| Port conflict resolution | Songbird | Requires port assignment decision. |
| Transport starts | Proteus | systemctl enable --now. |
| Gateway starts | Proteus | hermes gateway run. |
| DM token issuance | Songbird | Token generation + signing. |
| Verification | Lexicon | COO verifies all 25 checks pass. |

---

## Consequences

**If fixed:** All 13 agents online. DM token validation works mesh-wide. Pipeline tests can run without infrastructure gaps. No agent is blocked by missing personality.md or publicKey.

**If not fixed:** The pipeline test will fail again. Agents will 403 on DM validation. Lexicon and Songbird — the two most critical officers — cannot receive DM replies because their transports lack personality.md (sessions never spawn). The mesh is degraded until these fixes are applied.

**Risk:** These are mechanical fixes. The risk is in execution errors (typo in registry, wrong port assignment) — not in architectural decisions. A verification pass after each phase catches errors immediately.
